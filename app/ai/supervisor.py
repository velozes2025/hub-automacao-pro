"""Agentic supervisor: Claude -> tools -> Claude -> response.

Mini-LangGraph pattern using only the Anthropic API.
No external frameworks needed. Claude IS the supervisor.

Flow:
1. Receive text (or transcribed audio)
2. Load conversation + history + lead + agent_config
3. Build system prompt
4. Call Claude with enabled tools
5. If Claude requests tool_use -> execute -> feed result -> repeat (max N iterations)
6. Extract final response -> return
"""

import logging
from app.config import config
from app.ai.client import call_api, estimate_cost
from app.ai.tools import execute_tool, get_tool_definitions
from app.ai.prompts import build_system_prompt, detect_sentiment

log = logging.getLogger('ai.supervisor')

FALLBACK_RESPONSES = {
    'pt': ['perai, to verificando aqui', 'um seg, ja volto', 'opa, da um momento'],
    'en': ['one sec, checking here', 'hold on, be right back', 'just a moment'],
    'es': ['un momento, estoy verificando', 'espera un segundo', 'dame un momento'],
}
_fallback_idx = 0


def process(conversation, agent_config, language='pt', api_key=None, source='text'):
    """Run the supervisor loop and return the AI response.

    Args:
        conversation: dict with messages, contact_name, contact_phone, stage, lead, etc.
        agent_config: dict with system_prompt, model, max_tokens, persona, tools_enabled, etc.
        language: detected language code
        api_key: optional per-tenant API key override
        source: 'text' or 'audio' — when 'audio', response is optimized for speech

    Returns:
        dict with: text, input_tokens, output_tokens, model, cost, tool_calls
    """
    global _fallback_idx
    total_input = 0
    total_output = 0
    tool_calls = []

    model = agent_config.get('model', config.DEFAULT_MODEL)
    max_tokens = agent_config.get('max_tokens', config.DEFAULT_MAX_TOKENS)
    max_history = agent_config.get('max_history_messages', config.DEFAULT_MAX_HISTORY)

    # Audio responses need more tokens for complete reasoning (begin, middle, end)
    if source == 'audio':
        max_tokens = max(max_tokens, config.DEFAULT_MAX_TOKENS_AUDIO)

    # Detect user sentiment from latest message
    last_user_msg = ''
    for msg in reversed(conversation.get('messages', [])):
        if msg.get('role') == 'user' and msg.get('content'):
            last_user_msg = msg['content']
            break
    sentiment = detect_sentiment(last_user_msg) if last_user_msg else 'neutral'
    if source == 'audio':
        log.info(f'[SENTIMENT] Detected: {sentiment} from: "{last_user_msg[:60]}"')

    # Build system prompt
    lead = conversation.get('lead')
    system_prompt = build_system_prompt(agent_config, conversation, lead, language,
                                        spoken_mode=(source == 'audio'),
                                        sentiment=sentiment)

    # Prepare message history (last N messages)
    raw_messages = conversation.get('messages', [])
    history = []
    for msg in raw_messages[-max_history:]:
        role = msg.get('role', 'user')
        content = msg.get('content', '')
        if role in ('user', 'assistant') and content:
            history.append({'role': role, 'content': content})

    # Get enabled tools
    import json
    tools_enabled = agent_config.get('tools_enabled', '["web_search"]')
    if isinstance(tools_enabled, str):
        tools_enabled = json.loads(tools_enabled)
    tool_defs = get_tool_definitions(tools_enabled)

    # Tool execution context
    tool_context = {
        'tenant_id': str(conversation.get('tenant_id', '')),
        'phone': conversation.get('contact_phone', ''),
        'conversation_id': str(conversation.get('id', '')),
    }

    try:
        # First call
        data = call_api(model, max_tokens, system_prompt, history,
                       tools=tool_defs if tool_defs else None, api_key=api_key)
        if not data:
            raise Exception('API returned None')

        usage = data.get('usage', {})
        total_input += usage.get('input_tokens', 0)
        total_output += usage.get('output_tokens', 0)

        # Agentic loop (max N tool iterations)
        iterations = 0
        while data.get('stop_reason') == 'tool_use' and iterations < config.MAX_TOOL_ITERATIONS:
            iterations += 1

            assistant_content = data.get('content', [])
            tool_results = []

            for block in assistant_content:
                if block.get('type') == 'tool_use':
                    tool_name = block.get('name')
                    tool_input = block.get('input', {})
                    tool_id = block.get('id')

                    log.info(f'Tool call [{iterations}]: {tool_name}({tool_input})')
                    result_text = execute_tool(tool_name, tool_input, tool_context)
                    tool_calls.append({
                        'name': tool_name,
                        'input': tool_input,
                        'result_preview': result_text[:200],
                    })

                    tool_results.append({
                        'type': 'tool_result',
                        'tool_use_id': tool_id,
                        'content': result_text,
                    })

            # Extend message history with assistant + tool results
            extended = history + [
                {'role': 'assistant', 'content': assistant_content},
                {'role': 'user', 'content': tool_results},
            ]

            # Next call
            data = call_api(model, max_tokens, system_prompt, extended,
                           tools=tool_defs if tool_defs else None, api_key=api_key)
            if not data:
                raise Exception('API returned None in tool loop')

            usage = data.get('usage', {})
            total_input += usage.get('input_tokens', 0)
            total_output += usage.get('output_tokens', 0)

        # Extract final text
        final_text = ''
        for block in data.get('content', []):
            if block.get('type') == 'text':
                final_text += block.get('text', '')

        if not final_text:
            raise Exception('Empty response from Claude')

        return {
            'text': final_text.strip(),
            'input_tokens': total_input,
            'output_tokens': total_output,
            'model': model,
            'cost': estimate_cost(model, total_input, total_output),
            'tool_calls': tool_calls,
            'sentiment': sentiment,
        }

    except Exception as e:
        log.error(f'Supervisor error: {e}')
        msgs = FALLBACK_RESPONSES.get(language, FALLBACK_RESPONSES['pt'])
        fallback = msgs[_fallback_idx % len(msgs)]
        _fallback_idx += 1
        return {
            'text': fallback,
            'input_tokens': total_input,
            'output_tokens': total_output,
            'model': model,
            'cost': estimate_cost(model, total_input, total_output),
            'tool_calls': tool_calls,
            'sentiment': sentiment,
        }
