"""System prompt assembly and text utilities."""

import re
import logging

log = logging.getLogger('ai.prompts')

# --- Fake name detection ---

_FAKE_NAMES = {
    'automation', 'bot', 'business', 'company', 'enterprise', 'admin',
    'test', 'teste', 'user', 'usuario', 'client', 'cliente', 'support',
    'suporte', 'info', 'contact', 'contato', 'shop', 'store', 'loja',
    'marketing', 'sales', 'vendas', 'service', 'servico', 'official',
    'oficial', 'news', 'tech', 'digital', 'group', 'grupo', 'team',
    'equipe', 'manager', 'gerente', 'assistant', 'assistente', 'help',
    'ajuda', 'welcome', 'delivery', 'app', 'web', 'dev', 'api',
}

_BIZ_PATTERN = re.compile(r'\b(llc|ltd|inc|corp|sa|ltda|eireli|mei|co\.)\b', re.IGNORECASE)


def is_real_name(name):
    """Detect if a push_name looks like a real person name."""
    if not name or len(name.strip()) < 2:
        return False
    n = name.strip().lower()
    if n in _FAKE_NAMES:
        return False
    if not re.search(r'[a-zA-ZÀ-ÿ]', name):
        return False
    if len(name.strip()) == 1:
        return False
    if _BIZ_PATTERN.search(n):
        return False
    return True


# --- Language detection ---

_EN_WORDS = re.compile(
    r'\b(hi|hello|hey|how|what|where|when|why|can|could|would|should|the|is|are|'
    r'do|does|have|has|yes|no|please|thanks|thank|you|your|need|help|want|looking|'
    r'business|company)\b',
    re.IGNORECASE,
)
_ES_WORDS = re.compile(
    r'\b(hola|como|estas|donde|cuando|porque|puedo|quiero|necesito|gracias|bueno|'
    r'bien|empresa|negocio|ayuda|por favor|tengo|tiene|hacer|estoy)\b',
    re.IGNORECASE,
)
_PT_WORDS = re.compile(
    r'\b(oi|ola|tudo|bem|como|voce|onde|quando|porque|preciso|quero|obrigado|bom|'
    r'empresa|ajuda|por favor|tenho|tem|fazer|estou|nao|sim)\b',
    re.IGNORECASE,
)


def detect_language(text):
    """Detect language via simple heuristics. Returns 'pt', 'en', or 'es'."""
    t = text.lower()
    scores = {
        'en': len(_EN_WORDS.findall(t)),
        'es': len(_ES_WORDS.findall(t)),
        'pt': len(_PT_WORDS.findall(t)),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else 'pt'


# --- System prompt builder ---

def build_system_prompt(agent_config, conversation, lead=None, language='pt'):
    """Build the full system prompt for a Claude call.

    Combines:
    - agent_config.system_prompt (base prompt from tenant)
    - agent_config.persona (name, role, tone)
    - Conversation context (contact name, history count, stage)
    - Lead info if available
    - Language instruction
    """
    base = agent_config.get('system_prompt', '')
    persona = agent_config.get('persona', {})
    contact_name = conversation.get('contact_name', '')
    messages = conversation.get('messages', [])
    stage = conversation.get('stage', 'new')

    # Name handling
    nome = contact_name if is_real_name(contact_name) else ''
    nome_instrucao = ''
    if not nome:
        nome_instrucao = (
            'IMPORTANTE: Voce NAO sabe o nome dessa pessoa. '
            'Pergunte o nome dela de forma natural antes de continuar. '
            'NAO invente nenhum nome, NAO use apelidos do perfil como nome. '
        )

    # Context block
    total_msgs = len(messages)
    if total_msgs > 1:
        ctx = (
            f'\n\nCONTEXTO: Ja trocaram {total_msgs} msgs. '
            f'Idioma detectado: {language}. '
            f'{f"Nome do cliente: {nome}. Chame pelo nome. " if nome else nome_instrucao}'
            f'NAO se apresente de novo. Continue a conversa naturalmente. '
            f'Seja proativo, sugira, pergunte.'
        )
    else:
        persona_name = persona.get('name', 'Oliver')
        ctx = (
            f'\n\nCONTEXTO: Primeiro contato. '
            f'Idioma detectado: {language}. RESPONDA NESSE IDIOMA. '
            f'{f"Nome do cliente: {nome}. " if nome else nome_instrucao}'
            f'Se apresente: {persona_name}. '
            f'Pergunte o ramo do negocio e como pode ajudar. So nesta primeira vez.'
        )

    # Lead context
    lead_ctx = ''
    if lead:
        lead_name = lead.get('name', '')
        lead_company = lead.get('company', '')
        lead_stage = lead.get('stage', '')
        parts = []
        if lead_name:
            parts.append(f'Nome registrado: {lead_name}')
        if lead_company:
            parts.append(f'Empresa: {lead_company}')
        if lead_stage:
            parts.append(f'Estagio no funil: {lead_stage}')
        if parts:
            lead_ctx = f'\n\nDADOS DO LEAD: {". ".join(parts)}.'

    # Stage context
    stage_ctx = ''
    if stage and stage != 'new':
        stage_ctx = f'\n\nESTAGIO DA CONVERSA: {stage}. Adapte seu tom e abordagem.'

    return base + ctx + lead_ctx + stage_ctx
