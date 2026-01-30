"""Compressed prompt builder for OLIVER.CORE v5.2.

Builds ~150-250 token prompts from DNA + expander + context + history.
Replaces the ~1800 token verbose system prompt for text mode.

v5.2: Enriched client context with memory fields (setor, localizacao,
      objecoes levantadas, proximo passo combinado, preferencias).
v5.3: Dynamic brand per tenant via get_dna()/get_expanders().
"""

import logging
from datetime import datetime, timezone, timedelta
from app.ai.oliver_core.dna import get_dna, get_expanders
from app.config import config

log = logging.getLogger('oliver.compressor')

# --- Timezone by country code / Brazilian DDD ---
_COUNTRY_TZ = {
    '1': -5, '44': 0, '351': 0, '34': 1, '33': 1, '49': 1, '39': 1,
    '81': 9, '86': 8, '91': 5, '971': 4, '972': 2, '27': 2, '234': 1,
    '52': -6, '54': -3, '56': -4, '57': -5, '58': -4, '51': -5,
}

_GREETING = {
    'morning': {'pt': 'bom dia', 'en': 'good morning', 'es': 'buenos dias'},
    'afternoon': {'pt': 'boa tarde', 'en': 'good afternoon', 'es': 'buenas tardes'},
    'evening': {'pt': 'boa noite', 'en': 'good evening', 'es': 'buenas noches'},
}


def _get_local_time(phone):
    """Detect local time from phone number and return prompt hint."""
    if not phone:
        return ''
    # Strip non-digits
    digits = ''.join(c for c in phone if c.isdigit())
    if not digits:
        return ''

    offset_h = -3  # default: Brazil (São Paulo)

    # Brazil: starts with 55
    if digits.startswith('55') and len(digits) >= 4:
        offset_h = -3  # All Brazil is UTC-3 (simplified)
    else:
        # Try country codes (longest first)
        for code_len in (3, 2, 1):
            code = digits[:code_len]
            if code in _COUNTRY_TZ:
                offset_h = _COUNTRY_TZ[code]
                break

    tz = timezone(timedelta(hours=offset_h))
    now = datetime.now(tz)
    hour = now.hour

    if 6 <= hour < 12:
        period = 'morning'
    elif 12 <= hour < 18:
        period = 'afternoon'
    else:
        period = 'evening'

    return f'HORA_LOCAL:{now.strftime("%H:%M")} SAUDACAO_CORRETA:{_GREETING[period].get("pt", "oi")}'


# --- Language labels (compact) ---
_LANG_LABELS = {
    'pt': 'IDIOMA:portugues brasileiro. PROIBIDO qualquer palavra em ingles ou outro idioma. 100% portugues.',
    'en': 'IDIOMA:English only. ZERO words in Portuguese or any other language. 100% English.',
    'es': 'IDIOMA:espanol solamente. PROHIBIDO palabras en otro idioma. 100% espanol.',
}


def build_compressed_prompt(phase, intent_type, agent_config, conversation,
                            lead, language='pt', sentiment='neutral',
                            tenant_brand=None, agent_modifier='',
                            client_facts=None):
    """Build a compressed system prompt (~150-250 tokens).

    Layers:
        0. DNA (~80 tokens) — always
        0.5 Agent modifier (v6.0) — specialist mode if active
        1. Expander (~40-60 tokens) — based on intent
        2. Client context (~30-50 tokens) — compressed lead/conversation data
        2.5 Client facts (v6.0) — extracted memory facts
        3. History (~40 tokens) — last N exchanges, truncated
        + Language, sentiment, base tenant prompt, reflection correction
    """
    parts = []

    empresa = tenant_brand or 'QuantrexNow'

    # Layer 0: DNA (always, with dynamic brand)
    parts.append(get_dna(empresa))

    # Tenant base prompt (if exists, prepend — it defines the business context)
    base_prompt = agent_config.get('system_prompt', '')
    if base_prompt:
        # Truncate to ~200 chars to keep it compact
        truncated = base_prompt[:200].rsplit(' ', 1)[0] if len(base_prompt) > 200 else base_prompt
        parts.append(f'[BASE]{truncated}')

    # Layer 0.5: Agent modifier (v6.0 — specialist mode)
    if agent_modifier:
        parts.append(f'[AGENT]{agent_modifier}')

    # Layer 1: Expander (on-demand, with dynamic brand)
    expanders = get_expanders(empresa)
    expander_key = intent_type or phase
    expander = expanders.get(expander_key) or expanders.get(phase, '')
    if expander:
        parts.append(f'[FASE]{expander}')

    # Layer 2: Client context (compressed)
    ctx = compress_lead_context(lead, conversation)
    if ctx:
        parts.append(ctx)

    # Layer 2.5: Client facts from memory (v6.0)
    if client_facts:
        from app.ai.oliver_core.memory_service import format_facts_for_prompt
        facts_str = format_facts_for_prompt(client_facts)
        if facts_str:
            parts.append(facts_str)

    # Layer 3: History (compressed)
    messages = conversation.get('messages', [])
    max_exchanges = config.ENGINE_V51_MAX_COMPRESSED_HISTORY
    hist = compress_history(messages, max_exchanges)
    if hist:
        parts.append(hist)

    # Language
    lang_label = _LANG_LABELS.get(language, _LANG_LABELS['pt'])
    parts.append(lang_label)

    # Local time for the contact (based on phone number)
    contact_phone = conversation.get('contact_phone', '')
    local_time = _get_local_time(contact_phone)
    if local_time:
        parts.append(local_time)

    # Sentiment (only if non-neutral)
    if sentiment and sentiment != 'neutral':
        parts.append(f'SENT:{sentiment}')

    # Creator rule (compact)
    parts.append('CRIADOR:Thiago. Se perguntarem quem te criou, responda THIAGO.')
    parts.append('REGRA:Sempre pergunte o nome do lead se nao souber. Nunca repita conteudo ja dito.')

    # Reflection correction (v6.0 — appended if retry)
    reflection_correction = conversation.get('reflection_correction', '')
    if reflection_correction:
        parts.append(reflection_correction)

    return '\n'.join(parts)


def compress_lead_context(lead, conversation):
    """Build compressed client context line.

    v5.2 format:
        [CTX]N:{nome}|E:{empresa}|D:{dor}|F:{fase}|S:{setor}|L:{loc}|FL:{flags}
        [MEM]OBJ:{objecoes}|PROX:{proximo_passo}|PREF:{preferencias}
    """
    nome = ''
    empresa = ''
    dor = ''
    setor = ''
    localizacao = ''
    objecoes = ''
    proximo_passo = ''
    preferencias = ''
    fase = conversation.get('stage', 'new')
    flags = []

    if lead:
        nome = lead.get('name', '') or ''
        empresa = lead.get('company', '') or ''
        meta = lead.get('metadata', {}) or {}
        if isinstance(meta, str):
            import json
            try:
                meta = json.loads(meta)
            except (ValueError, TypeError):
                meta = {}
        dor = meta.get('dor', '') or ''
        setor = meta.get('setor', '') or ''
        localizacao = meta.get('localizacao', '') or ''
        objecoes = meta.get('objecoes', '') or ''
        proximo_passo = meta.get('proximo_passo', '') or ''
        preferencias = meta.get('preferencias', '') or ''

    contact_name = conversation.get('contact_name', '')
    if not nome and contact_name:
        from app.ai.prompts import is_real_name
        nome = contact_name if is_real_name(contact_name) else ''

    if not nome:
        flags.append('!nome')

    ctx = f'[CTX]N:{nome or "?"}|E:{empresa or "?"}|D:{dor or "?"}|F:{fase}|S:{setor or "?"}|L:{localizacao or "?"}'
    if flags:
        ctx += f'|FL:{",".join(flags)}'

    # Memory layer: only include if there's something to remember
    mem_parts = []
    if objecoes:
        mem_parts.append(f'OBJ:{objecoes}')
    if proximo_passo:
        mem_parts.append(f'PROX:{proximo_passo}')
    if preferencias:
        mem_parts.append(f'PREF:{preferencias}')
    if mem_parts:
        ctx += f'\n[MEM]{"|".join(mem_parts)}'

    return ctx


def compress_history(messages, max_exchanges=3):
    """Build compressed history from last N exchanges.

    Format:
        [HIST]
        C>{msg truncated to 80 chars}
        O>{msg truncated to 80 chars}
    """
    if not messages:
        return ''

    # Take last N*2 messages (N exchanges = N user + N assistant)
    recent = messages[-(max_exchanges * 2):]
    if not recent:
        return ''

    lines = ['[HIST]']
    for msg in recent:
        role = msg.get('role', 'user')
        content = msg.get('content', '')
        if not content:
            continue
        prefix = 'C' if role == 'user' else 'O'
        truncated = content[:80] + '...' if len(content) > 80 else content
        # Remove newlines for compactness
        truncated = truncated.replace('\n', ' ').strip()
        lines.append(f'{prefix}>{truncated}')

    return '\n'.join(lines) if len(lines) > 1 else ''
