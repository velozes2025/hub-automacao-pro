"""Anthropic API client with per-tenant key support."""

import logging
import requests

from app.config import config

log = logging.getLogger('ai.client')

API_URL = 'https://api.anthropic.com/v1/messages'


def _get_headers(api_key=None):
    key = api_key or config.ANTHROPIC_API_KEY
    return {
        'x-api-key': key,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
    }


def estimate_cost(model, input_tokens, output_tokens):
    prices = config.PRICING.get(model, {'input': 0.000003, 'output': 0.000015})
    return input_tokens * prices['input'] + output_tokens * prices['output']


def call_api(model, max_tokens, system_prompt, messages, tools=None, api_key=None):
    """Raw Anthropic API call. Returns parsed JSON or None on error."""
    body = {
        'model': model,
        'max_tokens': max_tokens,
        'system': system_prompt,
        'messages': messages,
    }
    if tools:
        body['tools'] = tools

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
        return r.json()
    except Exception as e:
        log.error(f'API request failed: {e}')
        return None
