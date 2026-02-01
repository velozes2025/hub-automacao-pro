"""OpenAI API client with Anthropic-compatible interface.

Translates between the Anthropic message format (used throughout the codebase)
and the OpenAI Chat Completions API. All callers continue to use the same
call_api() signature and receive responses in Anthropic format.
"""

import json
import logging
import requests

from app.config import config

log = logging.getLogger('ai.client')

API_URL = 'https://api.openai.com/v1/chat/completions'


def _get_headers(api_key=None):
    key = api_key or config.OPENAI_API_KEY
    return {
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
    }


def estimate_cost(model, input_tokens, output_tokens):
    prices = config.PRICING.get(model, {'input': 0.0000025, 'output': 0.00001})
    return input_tokens * prices['input'] + output_tokens * prices['output']


def _convert_tools_to_openai(tools):
    """Convert Anthropic tool definitions to OpenAI function-calling format."""
    if not tools:
        return None
    oai_tools = []
    for tool in tools:
        oai_tools.append({
            'type': 'function',
            'function': {
                'name': tool.get('name'),
                'description': tool.get('description', ''),
                'parameters': tool.get('input_schema', {}),
            }
        })
    return oai_tools


def _convert_messages_to_openai(system_prompt, messages):
    """Convert Anthropic-format messages to OpenAI chat format.

    Handles:
    - Simple string content (text messages)
    - List content from assistant (tool_use blocks from agentic loop)
    - List content from user (tool_result blocks from agentic loop)
    """
    oai_messages = [{'role': 'system', 'content': system_prompt}]

    for msg in messages:
        role = msg.get('role', 'user')
        content = msg.get('content', '')

        if isinstance(content, str):
            oai_messages.append({'role': role, 'content': content})

        elif isinstance(content, list):
            if role == 'assistant':
                # Anthropic assistant blocks -> OpenAI assistant with tool_calls
                text_parts = []
                tool_calls = []
                for block in content:
                    if block.get('type') == 'text':
                        text_parts.append(block.get('text', ''))
                    elif block.get('type') == 'tool_use':
                        tool_calls.append({
                            'id': block.get('id'),
                            'type': 'function',
                            'function': {
                                'name': block.get('name'),
                                'arguments': json.dumps(block.get('input', {})),
                            }
                        })
                oai_msg = {'role': 'assistant', 'content': '\n'.join(text_parts) or None}
                if tool_calls:
                    oai_msg['tool_calls'] = tool_calls
                oai_messages.append(oai_msg)

            elif role == 'user':
                # Anthropic tool_result blocks -> OpenAI tool messages
                for block in content:
                    if block.get('type') == 'tool_result':
                        oai_messages.append({
                            'role': 'tool',
                            'tool_call_id': block.get('tool_use_id'),
                            'content': str(block.get('content', '')),
                        })

    return oai_messages


def _convert_response_to_anthropic(oai_response):
    """Convert OpenAI response to Anthropic format for supervisor compatibility."""
    choice = oai_response['choices'][0]
    message = choice['message']
    finish_reason = choice.get('finish_reason', 'stop')

    content = []
    if message.get('content'):
        content.append({'type': 'text', 'text': message['content']})

    if message.get('tool_calls'):
        for tc in message['tool_calls']:
            try:
                tool_input = json.loads(tc['function']['arguments'])
            except (json.JSONDecodeError, TypeError):
                tool_input = {}
            content.append({
                'type': 'tool_use',
                'id': tc['id'],
                'name': tc['function']['name'],
                'input': tool_input,
            })

    usage = oai_response.get('usage', {})

    return {
        'content': content,
        'stop_reason': 'tool_use' if finish_reason == 'tool_calls' else 'end_turn',
        'usage': {
            'input_tokens': usage.get('prompt_tokens', 0),
            'output_tokens': usage.get('completion_tokens', 0),
        }
    }


def _map_model(model):
    """Map Anthropic model names to OpenAI equivalents."""
    mapping = {
        'claude-sonnet-4-20250514': 'gpt-4o',
        'claude-3-5-sonnet-20241022': 'gpt-4o',
        'claude-opus-4-5-20251101': 'gpt-4o',
        'claude-3-haiku-20240307': 'gpt-4o-mini',
        'claude-3-5-haiku-20241022': 'gpt-4o-mini',
    }
    return mapping.get(model, 'gpt-4o')


def call_api(model, max_tokens, system_prompt, messages, tools=None, api_key=None):
    """API call compatible with existing codebase. Returns Anthropic-format response or None."""
    oai_model = _map_model(model)
    oai_messages = _convert_messages_to_openai(system_prompt, messages)

    body = {
        'model': oai_model,
        'max_tokens': max_tokens,
        'messages': oai_messages,
    }

    oai_tools = _convert_tools_to_openai(tools)
    if oai_tools:
        body['tools'] = oai_tools

    try:
        r = requests.post(
            API_URL,
            headers=_get_headers(api_key),
            json=body,
            timeout=60,
        )
        if r.status_code != 200:
            log.error(f'API error {r.status_code}: {r.text[:300]}')
            return None
        return _convert_response_to_anthropic(r.json())
    except Exception as e:
        log.error(f'API request failed: {e}')
        return None
