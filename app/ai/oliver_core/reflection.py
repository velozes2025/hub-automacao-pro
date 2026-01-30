"""OLIVER.CORE v6.0 — Reflection / Self-Correction Loop.

Validates AI responses before sending. Pure regex checks (<5ms, no LLM).
If issues found, triggers max 1 retry with correction guidance.

Checks:
    1. repeated_question — asking something already answered
    2. contradicts_facts — response contradicts known client facts
    3. too_long — response exceeds 500 chars (WhatsApp text mode)
    4. forbidden_patterns — markdown, lists, numbered items
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


# All checks in order
_CHECKS = [
    _check_repeated_question,
    _check_contradicts_facts,
    _check_too_long,
    _check_forbidden_patterns,
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
