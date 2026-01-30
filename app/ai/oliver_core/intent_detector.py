"""Regex-based intent detection for OLIVER.CORE v5.2.

Maps user messages to (phase, intent_type) tuples. Lightweight — no LLM call.
Falls back to conversation stage when no regex matches.

v5.2: Added OBJ.depois pattern, returning client detection.
v5.3: Added TECH (technical/support) and FIN (financial/payment) delegation patterns.
"""

import re
import logging

log = logging.getLogger('oliver.intent')

# --- Intent patterns (ordered by priority: most specific first) ---

_PATTERNS = [
    # Objections (highest priority — user is pushing back)
    ('OBJ.preco', re.compile(
        r'\b(caro|preco|valor|custo|investimento|quanto custa|expensive|price|'
        r'muito caro|custa quanto|fora do orcamento|budget)\b', re.I)),
    ('OBJ.tempo', re.compile(
        r'\b(sem tempo|nao tenho tempo|ocupado|mais tarde|'
        r'another time|too busy|no time)\b', re.I)),
    ('OBJ.pensar', re.compile(
        r'\b(vou pensar|preciso pensar|deixa eu pensar|avaliar|analisar|'
        r'think about|let me think|need to think)\b', re.I)),
    ('OBJ.socio', re.compile(
        r'\b(socio|parceiro|partner|falar com|consultar|esposa|marido|'
        r'business partner|co-founder)\b', re.I)),
    ('OBJ.tentou', re.compile(
        r'\b(ja tentei|tentei|nao funcionou|nao deu certo|deu errado|'
        r'tried before|didnt work|didnt help|already tried)\b', re.I)),
    ('OBJ.depois', re.compile(
        r'\b(vou ver depois|depois eu vejo|mais pra frente|agora nao|'
        r'outro momento|outra hora|maybe later|not now|later)\b', re.I)),

    # Special situations
    ('SIT.url', re.compile(r'https?://\S+|www\.\S+', re.I)),
    ('SIT.sem_site', re.compile(
        r'\b(nao tenho site|sem site|no website|dont have a site|'
        r'nao tenho pagina|sem pagina)\b', re.I)),
    ('SIT.confuso', re.compile(
        r'\b(nao entendi|como funciona|como faz|como assim|'
        r'nao compreendi|pode explicar|explica|confused|'
        r'dont understand|how does|what do you mean)\b', re.I)),
    ('SIT.apressado', re.compile(
        r'\b(rapido|direto|resumo|resume|objetivo|sem enrolacao|'
        r'quick|straight to the point|briefly|tldr)\b', re.I)),

    # Technical support / specialist delegation
    ('TECH.suporte', re.compile(
        r'\b(suporte|tecnico|tecnica|bug|erro|nao funciona|travou|problema tecnico|'
        r'configuracao|instalar|integrar|api|sistema|plataforma|painel|dashboard|'
        r'technical|support|setup|configure|integration|not working|broken)\b', re.I)),
    ('TECH.dev', re.compile(
        r'\b(desenvolvimento|programacao|codigo|webhook|endpoint|servidor|'
        r'deploy|hosting|dominio|ssl|dns|development|code|server)\b', re.I)),

    # Financial / payment delegation
    ('FIN.pagamento', re.compile(
        r'\b(pagamento|pagar|boleto|cartao|pix|fatura|cobranca|nota fiscal|'
        r'nf|recibo|reembolso|estorno|cancelar assinatura|'
        r'payment|invoice|billing|refund|cancel subscription|credit card)\b', re.I)),
    ('FIN.plano', re.compile(
        r'\b(plano|assinatura|mensalidade|anual|trimestral|trial|teste gratis|'
        r'subscription|plan|pricing|free trial)\b', re.I)),

    # Closing signals
    ('FECH', re.compile(
        r'\b(fechar|contratar|comprar|assinar|comecar|vamos la|'
        r'quero comecar|fecha|deal|buy|sign up|lets go|lets start)\b', re.I)),

    # Proposal interest
    ('PROP', re.compile(
        r'\b(como funciona|quanto fica|proposta|orcamento|planos|'
        r'me explica|tell me more|how does it work|proposal|quote)\b', re.I)),
]

# --- Stage-to-phase mapping (fallback when no regex matches) ---

_STAGE_MAP = {
    'new': 'ABER',
    'qualifying': 'DIAG',
    'nurturing': 'EDUC',
    'closing': 'PROP',
    'support': 'TECH',
    'closed': 'FECH',
}


def detect_intent(message_text, conversation_stage='new', lead=None,
                  message_count=0):
    """Detect intent from user message.

    Args:
        message_text: the user's message
        conversation_stage: current stage from DB ('new', 'qualifying', etc.)
        lead: lead dict or None
        message_count: total messages in conversation (for returning client detection)

    Returns:
        tuple: (phase, intent_type)
            - phase: 'ABER', 'DIAG', 'EDUC', 'PROP', 'FECH', 'OBJ', 'SIT', 'TECH', 'FIN'
            - intent_type: specific type like 'OBJ.preco' or None for generic phases
    """
    if not message_text:
        return _resolve_opening(lead, conversation_stage, message_count)

    msg = message_text.strip()

    # Try regex patterns (priority order)
    for intent_key, pattern in _PATTERNS:
        if pattern.search(msg):
            phase = intent_key.split('.')[0]
            log.debug(f'Intent detected: {intent_key} from "{msg[:50]}"')
            return phase, intent_key

    # Fallback: infer from conversation stage
    phase = _STAGE_MAP.get(conversation_stage, 'DIAG')

    # Opening logic: first contact or returning client
    if conversation_stage == 'new' or phase == 'ABER':
        return _resolve_opening(lead, conversation_stage, message_count)

    log.debug(f'Intent fallback: {phase} (stage={conversation_stage})')
    return phase, None


def _resolve_opening(lead, stage, message_count=0):
    """Determine opening type: new without name, new with name, or returning client."""
    has_name = lead and lead.get('name')

    # Returning client: has a name AND has prior conversation history
    # (message_count > 0 means there were previous messages in DB)
    if has_name and message_count > 0:
        return 'ABER', 'ABER.retorno'

    if has_name:
        return 'ABER', 'ABER.com_nome'
    return 'ABER', 'ABER.sem_nome'
