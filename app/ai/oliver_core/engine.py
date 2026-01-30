"""OLIVER.CORE v6.0 — Adaptive Multi-Tenant Engine.

Decision engine that sits between message_handler and supervisor.
Text-mode: intent detection -> cache -> compressed prompt -> supervisor.
Audio-mode: passthrough to supervisor (v5.0 voice path unchanged).

v5.2: Returning client detection via message_count, enriched memory context.
v5.3: Dynamic brand per tenant, multi-agent orchestration (TECH/FIN).
v6.0: State machine + agent router + client memory + reflection loop.
"""

import json
import logging
import threading
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


def _resolve_tenant_brand(tenant_settings, agent_config, conversation):
    """Resolve tenant brand name with priority chain.

    Priority:
        1. tenant_settings.brand_name (explicit brand override)
        2. agent_config.persona.company_name (from persona config)
        3. conversation.tenant_name (from DB join)
        4. Fallback: 'QuantrexNow'
    """
    # 1. Explicit brand_name in tenant settings
    if tenant_settings and isinstance(tenant_settings, dict):
        brand = tenant_settings.get('brand_name')
        if brand:
            return brand

    # 2. Persona company_name
    persona = agent_config.get('persona', {})
    if isinstance(persona, str):
        try:
            persona = json.loads(persona) if persona else {}
        except (ValueError, TypeError):
            persona = {}
    if isinstance(persona, dict):
        company = persona.get('company_name')
        if company:
            return company

    # 3. Tenant name from conversation context
    tenant_name = conversation.get('tenant_name', '')
    if tenant_name:
        return tenant_name

    # 4. Fallback
    return 'QuantrexNow'


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

    # Resolve tenant brand (dynamic per tenant)
    tenant_brand = _resolve_tenant_brand(tenant_settings, agent_config, conversation)

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
        cached_response = try_cache(phase, intent_type, lead, language,
                                    tenant_brand=tenant_brand)
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
        tenant_brand=tenant_brand,
        agent_modifier=conversation.get('agent_modifier', ''),
        client_facts=conversation.get('client_facts'),
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


# ======================================================================
# OLIVER.CORE v6.0 — State Machine + Agent Router + Memory + Reflection
# ======================================================================

def process_v60(conversation, agent_config, language='pt', api_key=None,
                source='text', tenant_settings=None):
    """v6.0 wrapper: state machine -> agent router -> v5.1 -> reflection -> memory.

    When ENGINE_V60_ENABLED=false (default), delegates directly to process_v51().
    Each sub-system (state machine, memory, reflection) has its own feature flag.

    Args: same as process_v51()
    Returns: same as process_v51() with engine_version='v6.0'
    """
    # --- v6.0 disabled? Passthrough to v5.1 ---
    if not config.ENGINE_V60_ENABLED:
        return process_v51(conversation, agent_config, language, api_key,
                          source, tenant_settings)

    # --- Audio mode: v5.1 handles it (v6.0 is text-only for now) ---
    if source == 'audio':
        return process_v51(conversation, agent_config, language, api_key,
                          source, tenant_settings)

    conversation_id = str(conversation.get('id', ''))
    tenant_id = str(conversation.get('tenant_id', ''))
    lead = conversation.get('lead')
    lead_id = str(lead['id']) if lead and lead.get('id') else None

    # Extract last user message for intent detection
    messages = conversation.get('messages', [])
    last_user_msg = ''
    for msg in reversed(messages):
        if msg.get('role') == 'user' and msg.get('content'):
            last_user_msg = msg['content']
            break
    stage = conversation.get('stage', 'new')
    message_count = len(messages)

    # Detect intent (shared with v5.1)
    phase, intent_type = detect_intent(last_user_msg, stage, lead, message_count)

    # --- 1. State Machine: resolve node ---
    state = None
    state_phase = phase  # default: use intent detector's phase
    if config.ENGINE_V60_STATE_MACHINE_ENABLED:
        try:
            from app.ai.oliver_core import state_machine
            state = state_machine.get_or_create_state(conversation_id, tenant_id)
            if state:
                state = state_machine.evaluate_transition(
                    state, intent_type, conversation)
                state_phase = state_machine.get_phase_for_node(
                    state.get('current_node', 'ABERTURA'))
                log.info(f'[V6.0] node={state["current_node"]} '
                         f'agent={state.get("active_agent", "oliver")} '
                         f'phase={state_phase}')
        except Exception as e:
            log.error(f'[V6.0] State machine error: {e}')

    # --- 2. Agent Router: resolve agent modifier ---
    agent_modifier = ''
    if state and config.ENGINE_V60_STATE_MACHINE_ENABLED:
        try:
            from app.ai.oliver_core import agent_router
            agent_id = agent_router.resolve_agent(state, intent_type)
            agent_modifier = agent_router.get_prompt_modifier(agent_id)
        except Exception as e:
            log.error(f'[V6.0] Agent router error: {e}')

    # --- 3. Memory: load facts (sync, fast) ---
    facts = {}
    if config.ENGINE_V60_MEMORY_ENABLED and lead_id:
        try:
            from app.ai.oliver_core import memory_service
            facts = memory_service.get_facts(lead_id)
            if facts:
                log.debug(f'[V6.0] Loaded {len(facts)} facts for lead {lead_id[:8]}')
        except Exception as e:
            log.error(f'[V6.0] Memory load error: {e}')

    # --- 4. Enrich conversation and call v5.1 ---
    enriched = dict(conversation)
    enriched['agent_modifier'] = agent_modifier
    enriched['client_facts'] = facts
    if state:
        enriched['state_node'] = state.get('current_node', 'ABERTURA')

    result = process_v51(enriched, agent_config, language, api_key,
                        source, tenant_settings)

    # --- 5. Reflection: validate response ---
    if config.ENGINE_V60_REFLECTION_ENABLED and source == 'text':
        try:
            from app.ai.oliver_core import reflection
            issues = reflection.validate(result['text'], conversation, facts)
            if issues and reflection.has_errors(issues):
                log.info(f'[V6.0] Reflection found {len(issues)} issues, retrying')

                # Build correction guidance and retry once
                correction = reflection.build_correction_guidance(issues, facts)
                retry_conversation = dict(enriched)
                retry_conversation['reflection_correction'] = correction

                retry_result = process_v51(
                    retry_conversation, agent_config, language, api_key,
                    source, tenant_settings)

                # Log reflection
                reflection.log_reflection(
                    conversation_id, tenant_id,
                    original_response=result['text'],
                    issues=issues,
                    was_retried=True,
                    final_response=retry_result['text'],
                )

                # Accumulate token counts
                retry_result['input_tokens'] += result.get('input_tokens', 0)
                retry_result['output_tokens'] += result.get('output_tokens', 0)
                retry_result['cost'] += result.get('cost', 0)
                result = retry_result
            elif issues:
                # Log warnings without retry
                reflection.log_reflection(
                    conversation_id, tenant_id,
                    original_response=result['text'],
                    issues=issues,
                    was_retried=False,
                )
        except Exception as e:
            log.error(f'[V6.0] Reflection error: {e}')

    # --- 6. Memory: extract facts (async, background) ---
    if config.ENGINE_V60_MEMORY_ENABLED and lead_id and messages:
        try:
            from app.ai.oliver_core import memory_service
            threading.Thread(
                target=memory_service.extract_and_save_facts,
                args=(lead_id, tenant_id, messages, api_key),
                name=f'memory-{lead_id[:8]}',
                daemon=True,
            ).start()
        except Exception as e:
            log.error(f'[V6.0] Memory extraction trigger error: {e}')

    # --- 7. Update state guards (sync, fast) ---
    if state and config.ENGINE_V60_STATE_MACHINE_ENABLED:
        try:
            from app.ai.oliver_core import state_machine
            state_machine.update_guards(state, result['text'], lead, facts)
        except Exception as e:
            log.error(f'[V6.0] Guard update error: {e}')

    result['engine_version'] = 'v6.0'
    return result
