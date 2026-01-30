"""OLIVER.CORE v5.2 — Adaptive Multi-Tenant Engine.

Decision engine that sits between message_handler and supervisor.
Text-mode: intent detection -> cache -> compressed prompt -> supervisor.
Audio-mode: passthrough to supervisor (v5.0 voice path unchanged).

v5.2: Returning client detection via message_count, enriched memory context.
"""

import logging
from app.config import config
from app.ai import supervisor
from app.ai.prompts import detect_sentiment
from app.ai.oliver_core.intent_detector import detect_intent
from app.ai.oliver_core.cache import try_cache
from app.ai.oliver_core.compressor import build_compressed_prompt
from app.ai.oliver_core.tiers import get_tier_config, resolve_max_history
from app.ai.oliver_core.sistema_v51 import SISTEMA_V51_TEXT
from app.ai.oliver_core import metrics

log = logging.getLogger('oliver.engine')


def process_v51(conversation, agent_config, language='pt', api_key=None,
                source='text', tenant_settings=None):
    """Main v5.1 engine entry point.

    For text mode: intent detection -> cache check -> compressed prompt -> supervisor.
    For audio mode: passthrough to supervisor (v5.0 voice spec handles it).

    Args:
        conversation: dict with messages, contact_name, contact_phone, stage, lead, etc.
        agent_config: dict with system_prompt, model, max_tokens, persona, tools_enabled.
        language: detected language code ('pt', 'en', 'es').
        api_key: optional per-tenant API key override.
        source: 'text' or 'audio'.
        tenant_settings: tenant settings JSONB dict.

    Returns:
        dict with: text, input_tokens, output_tokens, model, cost, tool_calls, sentiment,
                   and optional: cache_hit, engine_version, intent.
    """
    # --- Engine disabled? Passthrough to legacy supervisor ---
    if not config.ENGINE_V51_ENABLED:
        return supervisor.process(conversation, agent_config, language, api_key, source)

    # --- Audio mode: passthrough to supervisor (v5.0 voice path) ---
    if source == 'audio':
        result = supervisor.process(conversation, agent_config, language, api_key, source)
        result['engine_version'] = 'v5.0-voice'
        return result

    # --- TEXT MODE: v5.1 engine ---
    tenant_id = conversation.get('tenant_id', '')
    tier_config = get_tier_config(tenant_settings)
    lead = conversation.get('lead')
    stage = conversation.get('stage', 'new')

    # Extract last user message and count total messages (for returning client detection)
    messages = conversation.get('messages', [])
    last_user_msg = ''
    for msg in reversed(messages):
        if msg.get('role') == 'user' and msg.get('content'):
            last_user_msg = msg['content']
            break
    message_count = len(messages)

    # Detect sentiment
    sentiment = detect_sentiment(last_user_msg) if last_user_msg else 'neutral'

    # Detect intent (v5.2: message_count enables returning client detection)
    phase, intent_type = detect_intent(last_user_msg, stage, lead, message_count)
    log.info(f'[V5.2] phase={phase} intent={intent_type} sentiment={sentiment}')

    # --- Try cache (0 tokens) ---
    cache_enabled = tier_config.get('cache_enabled', True) and config.ENGINE_V51_CACHE_ENABLED
    if cache_enabled:
        cached_response = try_cache(phase, intent_type, lead, language)
        if cached_response:
            metrics.record(
                tenant_id=tenant_id, cache_hit=True,
                tokens_used=0, tokens_baseline=config.ENGINE_V51_TOKEN_BASELINE,
                phase=phase, intent_type=intent_type or '',
            )
            return {
                'text': cached_response,
                'input_tokens': 0,
                'output_tokens': 0,
                'model': 'cache',
                'cost': 0.0,
                'tool_calls': [],
                'sentiment': sentiment,
                'cache_hit': True,
                'engine_version': 'v5.2',
                'intent': intent_type or phase,
            }

    # --- Cache miss: build compressed prompt ---
    compressed_prompt = build_compressed_prompt(
        phase=phase,
        intent_type=intent_type,
        agent_config=agent_config,
        conversation=conversation,
        lead=lead,
        language=language,
        sentiment=sentiment,
    )

    # Override max_history with tier-aware limit
    tier_max_history = resolve_max_history(tier_config, agent_config)
    patched_config = dict(agent_config)
    patched_config['max_history_messages'] = tier_max_history

    # Call supervisor with compressed system prompt
    result = supervisor.process(
        conversation=conversation,
        agent_config=patched_config,
        language=language,
        api_key=api_key,
        source=source,
        system_prompt_override=compressed_prompt,
    )

    # Record metrics
    metrics.record(
        tenant_id=tenant_id, cache_hit=False,
        tokens_used=result.get('input_tokens', 0),
        tokens_baseline=config.ENGINE_V51_TOKEN_BASELINE,
        phase=phase, intent_type=intent_type or '',
    )

    result['cache_hit'] = False
    result['engine_version'] = 'v5.2'
    result['intent'] = intent_type or phase
    return result
