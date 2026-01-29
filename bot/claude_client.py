import requests
from config import ANTHROPIC_API_KEY

PRICING = {
    'claude-3-haiku-20240307': {'input': 0.00000025, 'output': 0.00000125},
    'claude-3-5-haiku-20241022': {'input': 0.0000008, 'output': 0.000004},
    'claude-3-5-sonnet-20241022': {'input': 0.000003, 'output': 0.000015},
    'claude-sonnet-4-20250514': {'input': 0.000003, 'output': 0.000015},
}

FALLBACK_RESPONSES = [
    'um momento por favor',
    'ja volto',
    'opa, um segundo',
]
_fallback_idx = 0


def estimate_cost(model, input_tokens, output_tokens):
    prices = PRICING.get(model, {'input': 0.000003, 'output': 0.000015})
    return input_tokens * prices['input'] + output_tokens * prices['output']


def call_claude(system_prompt, messages, model='claude-3-haiku-20240307', max_tokens=150):
    global _fallback_idx
    try:
        r = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json'
            },
            json={
                'model': model,
                'max_tokens': max_tokens,
                'system': system_prompt,
                'messages': messages
            },
            timeout=30
        )
        if r.status_code == 200:
            data = r.json()
            usage = data.get('usage', {})
            input_tokens = usage.get('input_tokens', 0)
            output_tokens = usage.get('output_tokens', 0)
            return {
                'text': data['content'][0]['text'],
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'model': model,
                'cost': estimate_cost(model, input_tokens, output_tokens)
            }
    except Exception:
        pass

    fallback = FALLBACK_RESPONSES[_fallback_idx % len(FALLBACK_RESPONSES)]
    _fallback_idx += 1
    return {
        'text': fallback,
        'input_tokens': 0,
        'output_tokens': 0,
        'model': model,
        'cost': 0.0
    }
