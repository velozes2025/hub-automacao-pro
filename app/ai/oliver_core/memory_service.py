"""OLIVER.CORE v6.0 — Client Memory Service.

Extracts and stores key-value facts about each lead from conversation history.
Hot path: sync DB read (~5ms). Cold path: async Haiku extraction (~1s).

Known fact keys (13):
    nome, empresa, ramo, dor_principal, orcamento, decisor,
    tamanho_equipe, localizacao, stack_tech, objecao_principal,
    proximo_passo, preferencia_comunicacao, contexto_pessoal
"""

import json
import logging

from app.config import config
from app.db import memory as memory_db

log = logging.getLogger('oliver.memory')

# All recognized fact keys
KNOWN_KEYS = [
    'nome', 'empresa', 'ramo', 'dor_principal', 'orcamento',
    'decisor', 'tamanho_equipe', 'localizacao', 'stack_tech',
    'objecao_principal', 'proximo_passo', 'preferencia_comunicacao',
    'contexto_pessoal',
]

# Extraction prompt for Claude Haiku
_EXTRACTION_PROMPT = (
    'Analise as mensagens de conversa abaixo e extraia fatos sobre o cliente.\n'
    'Retorne APENAS um JSON valido com as chaves que voce conseguir identificar.\n'
    'Chaves possiveis: nome, empresa, ramo, dor_principal, orcamento, decisor, '
    'tamanho_equipe, localizacao, stack_tech, objecao_principal, proximo_passo, '
    'preferencia_comunicacao, contexto_pessoal.\n'
    'Se nao conseguir identificar um fato, NAO inclua a chave.\n'
    'Valores devem ser strings curtas (max 100 chars).\n'
    'Responda SOMENTE o JSON, sem explicacao.\n\n'
    'Mensagens:\n'
)

# Model used for extraction (cheapest available)
_EXTRACTION_MODEL = 'claude-3-haiku-20240307'
_EXTRACTION_MAX_TOKENS = 300


def get_facts(lead_id):
    """Get all known facts for a lead (synchronous, fast).

    Returns dict of {fact_key: fact_value}. Empty dict if no facts or error.
    """
    if not lead_id:
        return {}
    try:
        return memory_db.get_facts(lead_id)
    except Exception as e:
        log.error(f'[MEMORY] Failed to get facts for lead {lead_id}: {e}')
        return {}


def extract_and_save_facts(lead_id, tenant_id, messages, api_key=None):
    """Extract facts from messages via Claude Haiku and save to DB.

    This runs in a background thread — never blocks the response.

    Args:
        lead_id: UUID of the lead
        tenant_id: UUID of the tenant
        messages: list of message dicts (role, content)
        api_key: optional per-tenant API key
    """
    if not lead_id or not messages:
        return

    try:
        # Build conversation text from last 6 messages
        recent = messages[-6:]
        conv_text = ''
        for msg in recent:
            role = 'Cliente' if msg.get('role') == 'user' else 'Oliver'
            content = msg.get('content', '')[:200]  # Truncate for cost
            conv_text += f'{role}: {content}\n'

        if not conv_text.strip():
            return

        # Call Haiku for extraction
        from app.ai.client import call_api, estimate_cost
        prompt = _EXTRACTION_PROMPT + conv_text

        data = call_api(
            model=_EXTRACTION_MODEL,
            max_tokens=_EXTRACTION_MAX_TOKENS,
            system_prompt='Voce e um extrator de fatos. Retorne apenas JSON valido.',
            messages=[{'role': 'user', 'content': prompt}],
            api_key=api_key,
        )

        if not data:
            log.warning('[MEMORY] Haiku extraction returned None')
            return

        # Extract text from response
        text = ''
        for block in data.get('content', []):
            if block.get('type') == 'text':
                text += block.get('text', '')

        if not text.strip():
            return

        # Parse JSON from response
        facts = _parse_facts_json(text)
        if not facts:
            log.warning(f'[MEMORY] Failed to parse facts from: {text[:100]}')
            return

        # Save to DB
        memory_db.upsert_facts_batch(lead_id, tenant_id, facts)

        # Log cost
        usage = data.get('usage', {})
        input_tokens = usage.get('input_tokens', 0)
        output_tokens = usage.get('output_tokens', 0)
        cost = estimate_cost(_EXTRACTION_MODEL, input_tokens, output_tokens)
        log.info(f'[MEMORY] Extracted {len(facts)} facts for lead {lead_id[:8]}... '
                 f'(cost=${cost:.6f})')

        # Log consumption
        try:
            from app.db import consumption as consumption_db
            consumption_db.log_usage(
                tenant_id=tenant_id,
                model=_EXTRACTION_MODEL,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
                operation='memory_extraction',
                metadata={'facts_count': len(facts), 'lead_id': str(lead_id)},
            )
        except Exception as e:
            log.error(f'[MEMORY] Failed to log consumption: {e}')

    except Exception as e:
        log.error(f'[MEMORY] Extraction failed for lead {lead_id}: {e}')


def _parse_facts_json(text):
    """Parse JSON from Haiku response. Handles common formatting issues."""
    text = text.strip()

    # Try direct parse
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return _filter_valid_facts(obj)
    except (ValueError, TypeError):
        pass

    # Try extracting JSON from markdown code block
    import re
    json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if json_match:
        try:
            obj = json.loads(json_match.group())
            if isinstance(obj, dict):
                return _filter_valid_facts(obj)
        except (ValueError, TypeError):
            pass

    return None


def _filter_valid_facts(raw):
    """Filter to only known keys with non-empty string values."""
    result = {}
    for key in KNOWN_KEYS:
        val = raw.get(key)
        if val and isinstance(val, str) and val.strip():
            result[key] = val.strip()[:100]  # Cap at 100 chars
    return result if result else None


def format_facts_for_prompt(facts):
    """Format facts dict into compact prompt section.

    Returns string like: [FACTS]nome:Joao|empresa:Padaria|dor:demora
    """
    if not facts:
        return ''
    parts = [f'{k}:{v}' for k, v in facts.items() if v]
    if not parts:
        return ''
    return '[FACTS]' + '|'.join(parts)
