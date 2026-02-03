"""OLIVER.CORE v6.0 — Reflection / Self-Correction Loop.

Validates AI responses before sending. Pure regex checks (<5ms, no LLM).
If issues found, triggers max 1 retry with correction guidance.

Checks:
    1. repeated_question — asking something already answered
    2. contradicts_facts — response contradicts known client facts
    3. too_long — response exceeds 500 chars (WhatsApp text mode)
    4. forbidden_patterns — markdown, lists, numbered items
    5. language_mix — foreign language sentences in response
"""

import re
import json
import logging

log = logging.getLogger('oliver.reflection')

# --- Issue dataclass ---

class Issue:
    """A detected issue in the AI response."""
    def __init__(self, issue_type, detail, severity='warning'):
        self.type = issue_type
        self.detail = detail
        self.severity = severity  # 'warning' or 'error'

    def to_dict(self):
        return {'type': self.type, 'detail': self.detail, 'severity': self.severity}


# --- Patterns ---

# Common questions Oliver asks (Portuguese)
_QUESTION_PATTERNS = {
    'nome': re.compile(
        r'\b(como (te |eu )?chamo|qual .*nome|com quem .*(falo|converso)|'
        r'como posso te chamar)\b', re.IGNORECASE),
    'ramo': re.compile(
        r'\b(qual .*ramo|qual .*area|qual .*segmento|qual .*nicho|'
        r'qual .*setor|que tipo de negocio|o que .*(faz|trabalha))\b', re.IGNORECASE),
    'dor': re.compile(
        r'\b(qual .*maior (gargalo|dificuldade|problema|desafio)|'
        r'o que te (trouxe|fez buscar)|qual .*principal (dor|problema))\b', re.IGNORECASE),
    'orcamento': re.compile(
        r'\b(quanto .*investir|qual .*orcamento|quanto .*gastar|'
        r'qual .*budget|valor .*disponivel)\b', re.IGNORECASE),
    'localizacao': re.compile(
        r'\b(onde .*(fica|localiz|esta)|qual .*cidade|qual .*estado|'
        r'de onde .*(voce|vc))\b', re.IGNORECASE),
}

# Fact keys that map to question patterns
_FACT_QUESTION_MAP = {
    'nome': 'nome',
    'ramo': 'ramo',
    'dor_principal': 'dor',
    'orcamento': 'orcamento',
    'localizacao': 'localizacao',
}

# Forbidden formatting patterns
_FORBIDDEN = [
    re.compile(r'^\s*\d+[\.\)]\s', re.MULTILINE),       # "1. item" or "1) item"
    re.compile(r'^\s*[-*]\s', re.MULTILINE),              # "- item" or "* item"
    re.compile(r'\*\*[^*]+\*\*'),                          # **bold**
    re.compile(r'__[^_]+__'),                              # __bold__
    re.compile(r'^\s*#{1,6}\s', re.MULTILINE),            # # heading
    re.compile(r'\[.+\]\(.+\)'),                          # [link](url)
    re.compile(r'```'),                                    # code blocks
]

MAX_RESPONSE_LENGTH = 500

# --- Language mix detection ---
# Common English words that indicate a sentence is in English (not loanwords)
_ENGLISH_MARKERS = re.compile(
    r'\b(the|is|are|was|were|have|has|been|would|could|should|'
    r'this|that|these|those|with|from|your|you|they|them|their|'
    r'what|which|where|when|how|does|did|will|shall|'
    r'can|cannot|don\'t|doesn\'t|didn\'t|wouldn\'t|'
    r'I\'m|I\'ll|we\'re|we\'ll|you\'re|you\'ll|'
    r'let me|please|thank you|sorry|hello|goodbye|'
    r'our|here|there|about|also|just|very|really|'
    r'because|therefore|however|although|while)\b', re.IGNORECASE)

# Common Portuguese words that indicate a sentence is in Portuguese
_PORTUGUESE_MARKERS = re.compile(
    r'\b(voce|voces|nosso|nossa|nossos|nossas|'
    r'nao|sim|tambem|aqui|ali|agora|depois|antes|'
    r'muito|pouco|mais|menos|melhor|pior|'
    r'esta|estou|estamos|temos|tenho|'
    r'pode|posso|podemos|vamos|quero|'
    r'porque|entao|assim|ainda|sempre|nunca|'
    r'obrigado|obrigada|desculpe|ola|bom dia|boa tarde|boa noite|'
    r'por favor|como|qual|quem|onde|quando)\b', re.IGNORECASE)

# Common loanwords accepted in Portuguese (not counted as foreign)
_LOANWORDS = {
    'ok', 'okay', 'feedback', 'marketing', 'email', 'online', 'offline',
    'software', 'hardware', 'app', 'site', 'blog', 'link', 'chat',
    'startup', 'design', 'layout', 'input', 'output', 'dashboard',
    'lead', 'leads', 'crm', 'api', 'webhook', 'deploy', 'cloud',
    'streaming', 'download', 'upload', 'status', 'check', 'ticket',
    'performance', 'coaching', 'mentoring', 'briefing', 'insight',
    'deadline', 'meeting', 'follow', 'up', 'followup', 'follow-up',
    'roi', 'kpi', 'b2b', 'b2c', 'saas', 'bot', 'fit', 'pitch',
    'sprint', 'backlog', 'roadmap', 'mindset', 'networking',
}


# --- Validation functions ---

def _check_repeated_question(response, conversation, facts):
    """Check if response asks a question that facts already answer."""
    issues = []
    if not facts:
        return issues

    for fact_key, question_key in _FACT_QUESTION_MAP.items():
        fact_value = facts.get(fact_key)
        if not fact_value:
            continue

        pattern = _QUESTION_PATTERNS.get(question_key)
        if pattern and pattern.search(response):
            issues.append(Issue(
                'repeated_question',
                f'Pergunta sobre "{question_key}" repetida — '
                f'cliente ja informou: {fact_value}',
                severity='error',
            ))
    return issues


def _check_contradicts_facts(response, conversation, facts):
    """Check if response contradicts known facts (e.g., wrong name)."""
    issues = []
    if not facts:
        return issues

    # Check name contradiction
    nome = facts.get('nome')
    if nome and len(nome) > 2:
        # If response contains a different name being used as if it were the client's
        # This is a simple heuristic — check if a capitalized word that looks like
        # a name appears that doesn't match the known name
        nome_lower = nome.lower()
        # Check for direct address with wrong name
        greetings = re.findall(r'(?:oi|ola|prazer|fala)\s+([A-Z][a-z]+)', response)
        for g in greetings:
            if g.lower() != nome_lower and g.lower() not in nome_lower:
                issues.append(Issue(
                    'contradicts_facts',
                    f'Chamou cliente de "{g}" mas nome correto e "{nome}"',
                    severity='error',
                ))
                break

    return issues


def _check_too_long(response, conversation, facts):
    """Check if response exceeds maximum length for WhatsApp."""
    issues = []
    if len(response) > MAX_RESPONSE_LENGTH:
        issues.append(Issue(
            'too_long',
            f'Resposta com {len(response)} chars (max {MAX_RESPONSE_LENGTH})',
            severity='warning',
        ))
    return issues


def _check_forbidden_patterns(response, conversation, facts):
    """Check for markdown, lists, and other forbidden formatting."""
    issues = []
    for pattern in _FORBIDDEN:
        match = pattern.search(response)
        if match:
            issues.append(Issue(
                'forbidden_patterns',
                f'Formato proibido detectado: "{match.group()[:40]}"',
                severity='warning',
            ))
            break  # One is enough
    return issues


def _check_language_mix(response, conversation, facts):
    """Check if response contains sentences in the wrong language.

    Uses marker-word counting per sentence. If a sentence has 3+ English marker
    words and the conversation language is Portuguese (or vice-versa), flag as error.
    Loanwords (ok, feedback, marketing, etc.) are excluded from counting.
    """
    issues = []
    expected_lang = conversation.get('language', 'pt')

    # Split response into sentences (period, exclamation, question, newline)
    sentences = re.split(r'[.!?\n]+', response)

    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 15:  # Skip very short fragments
            continue

        words = set(re.findall(r'[a-zA-ZÀ-ÿ\']+', sentence.lower()))
        # Remove loanwords from consideration
        words_clean = words - _LOANWORDS

        if expected_lang == 'pt':
            # Response should be in Portuguese — check for English sentences
            en_hits = len(_ENGLISH_MARKERS.findall(sentence))
            if en_hits >= 3:
                issues.append(Issue(
                    'language_mix',
                    f'Frase em ingles detectada na resposta (idioma esperado: portugues): '
                    f'"{sentence[:60]}..."',
                    severity='error',
                ))
                break  # One violation is enough

        elif expected_lang == 'en':
            # Response should be in English — check for Portuguese sentences
            pt_hits = len(_PORTUGUESE_MARKERS.findall(sentence))
            if pt_hits >= 3:
                issues.append(Issue(
                    'language_mix',
                    f'Portuguese sentence detected in response (expected: English): '
                    f'"{sentence[:60]}..."',
                    severity='error',
                ))
                break

        elif expected_lang == 'es':
            # Spanish: flag English or Portuguese intrusions
            en_hits = len(_ENGLISH_MARKERS.findall(sentence))
            pt_hits = len(_PORTUGUESE_MARKERS.findall(sentence))
            if en_hits >= 3 or pt_hits >= 3:
                issues.append(Issue(
                    'language_mix',
                    f'Frase en idioma incorrecto detectada (esperado: espanol): '
                    f'"{sentence[:60]}..."',
                    severity='error',
                ))
                break

    return issues


def _check_incomplete_sentence(response, conversation, facts):
    """Check if response ends with an incomplete sentence (cut off mid-thought)."""
    issues = []
    stripped = response.rstrip()
    if not stripped:
        return issues

    # Detect sentences that look cut off: ending with comma, open connector, etc.
    _INCOMPLETE_ENDINGS = re.compile(
        r'(?:,|\.\.\.|para |pra |com |que |de |do |da |no |na |e |ou |mas |por |'
        r'como |quando |se |em |ao |pela |pelo |num |numa |nos |nas |'
        r'disponição para qualquer|disposição para qualquer|'
        r'fico à disposição para)\s*$',
        re.IGNORECASE,
    )
    if _INCOMPLETE_ENDINGS.search(stripped):
        issues.append(Issue(
            'incomplete_sentence',
            f'Mensagem parece cortada/incompleta: termina com "{stripped[-40:]}"',
            severity='error',
        ))
    return issues


# All checks in order
_CHECKS = [
    _check_repeated_question,
    _check_contradicts_facts,
    _check_too_long,
    _check_forbidden_patterns,
    _check_language_mix,
    _check_incomplete_sentence,
]


# --- Public API ---

def validate(response, conversation, facts=None):
    """Run all validation checks on an AI response.

    Args:
        response: the AI response text
        conversation: conversation dict with messages
        facts: dict of known client facts (from memory service)

    Returns:
        list of Issue objects (empty if no issues found)
    """
    if not response:
        return []

    issues = []
    for check_fn in _CHECKS:
        try:
            issues.extend(check_fn(response, conversation, facts or {}))
        except Exception as e:
            log.error(f'[REFLECT] Check {check_fn.__name__} failed: {e}')
    return issues


def build_correction_guidance(issues, facts=None):
    """Build correction prompt from issues list.

    Returns string to append to system prompt for retry.
    """
    if not issues:
        return ''

    lines = ['[CORRECAO] Sua resposta anterior tinha problemas:']
    for issue in issues:
        lines.append(f'- {issue.type}: {issue.detail}')

    # If language mix detected, add explicit language instruction
    has_lang_issue = any(i.type == 'language_mix' for i in issues)
    if has_lang_issue:
        lines.append('IMPORTANTE: Reescreva a resposta INTEIRA no idioma correto da conversa.')
        lines.append('NAO traduza palavra por palavra — reescreva naturalmente.')

    lines.append('Reescreva corrigindo esses pontos.')
    lines.append('Mantenha o mesmo tom e intencao, apenas corrija os problemas.')

    return '\n'.join(lines)


def log_reflection(conversation_id, tenant_id, original_response, issues,
                   was_retried=False, final_response=None):
    """Log reflection results to DB for audit trail."""
    try:
        from app.db import execute
        issues_json = json.dumps([i.to_dict() for i in issues])
        execute(
            """INSERT INTO reflection_logs
               (conversation_id, tenant_id, original_response, issues_found,
                was_retried, final_response)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (str(conversation_id), str(tenant_id), original_response,
             issues_json, was_retried, final_response),
        )
    except Exception as e:
        log.error(f'[REFLECT] Failed to log reflection: {e}')


def has_errors(issues):
    """Check if any issues are severity='error' (warrant retry)."""
    return any(i.severity == 'error' for i in issues)
