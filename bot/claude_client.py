import logging
import requests
from config import ANTHROPIC_API_KEY

log = logging.getLogger('claude-agent')

PRICING = {
    'claude-3-haiku-20240307': {'input': 0.00000025, 'output': 0.00000125},
    'claude-3-5-haiku-20241022': {'input': 0.0000008, 'output': 0.000004},
    'claude-3-5-sonnet-20241022': {'input': 0.000003, 'output': 0.000015},
    'claude-sonnet-4-20250514': {'input': 0.000003, 'output': 0.000015},
    'claude-opus-4-5-20251101': {'input': 0.000015, 'output': 0.000075},
}

TOOLS = [
    {
        'name': 'web_search',
        'description': (
            'Busca informacoes na internet em tempo real. '
            'Use quando o usuario perguntar sobre algo que voce nao sabe, '
            'precos, noticias, informacoes atualizadas, ou qualquer coisa '
            'que precise de dados em tempo real.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {
                    'type': 'string',
                    'description': 'O que buscar na internet (em portugues ou ingles)'
                }
            },
            'required': ['query']
        }
    }
]

FALLBACK_RESPONSES = [
    'perai, to verificando aqui',
    'um seg, ja volto',
    'opa, da um momento',
]
_fallback_idx = 0

API_URL = 'https://api.anthropic.com/v1/messages'
API_HEADERS = {
    'x-api-key': ANTHROPIC_API_KEY,
    'anthropic-version': '2023-06-01',
    'content-type': 'application/json'
}


def estimate_cost(model, input_tokens, output_tokens):
    prices = PRICING.get(model, {'input': 0.000003, 'output': 0.000015})
    return input_tokens * prices['input'] + output_tokens * prices['output']


def _do_web_search(query):
    """Executa busca web via DuckDuckGo HTML."""
    try:
        from lxml import html
        r = requests.get(
            'https://html.duckduckgo.com/html/',
            params={'q': query},
            headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'},
            timeout=10
        )
        tree = html.fromstring(r.text)
        results = []
        for item in tree.xpath('//div[contains(@class,"result")]')[:5]:
            title_els = item.xpath('.//a[contains(@class,"result__a")]')
            snippet_els = item.xpath('.//a[contains(@class,"result__snippet")]')
            title = title_els[0].text_content().strip() if title_els else ''
            snippet = snippet_els[0].text_content().strip() if snippet_els else ''
            if title and snippet:
                results.append(f"- {title}: {snippet}")
        if not results:
            return 'Nenhum resultado encontrado.'
        return '\n'.join(results)
    except Exception as e:
        log.error(f'Erro busca web: {e}')
        return f'Erro na busca: {e}'


def _call_api(model, max_tokens, system_prompt, messages, tools=None):
    """Faz uma chamada a API do Claude."""
    body = {
        'model': model,
        'max_tokens': max_tokens,
        'system': system_prompt,
        'messages': messages,
    }
    if tools:
        body['tools'] = tools
    r = requests.post(API_URL, headers=API_HEADERS, json=body, timeout=60)
    if r.status_code != 200:
        log.error(f'API erro {r.status_code}: {r.text[:300]}')
        return None
    return r.json()


def call_claude(system_prompt, messages, model='claude-opus-4-5-20251101', max_tokens=150):
    """Chama Claude como agente com capacidade de busca web.

    Fluxo agentico: Claude decide se precisa buscar na web.
    Se sim, executa a busca e retorna a resposta final.
    Maximo 2 iteracoes de tool use para evitar loops.
    """
    global _fallback_idx
    total_input = 0
    total_output = 0

    try:
        # Primeira chamada - Claude decide se usa ferramentas
        data = _call_api(model, max_tokens, system_prompt, messages, tools=TOOLS)
        if not data:
            raise Exception('API retornou None')

        usage = data.get('usage', {})
        total_input += usage.get('input_tokens', 0)
        total_output += usage.get('output_tokens', 0)

        # Loop agentico (max 2 tool calls)
        iterations = 0
        while data.get('stop_reason') == 'tool_use' and iterations < 2:
            iterations += 1

            # Extrair tool calls do response
            tool_results = []
            assistant_content = data.get('content', [])

            for block in assistant_content:
                if block.get('type') == 'tool_use':
                    tool_name = block.get('name')
                    tool_input = block.get('input', {})
                    tool_id = block.get('id')

                    if tool_name == 'web_search':
                        query = tool_input.get('query', '')
                        log.info(f'Agente buscando: "{query}"')
                        result_text = _do_web_search(query)
                    else:
                        result_text = f'Ferramenta desconhecida: {tool_name}'

                    tool_results.append({
                        'type': 'tool_result',
                        'tool_use_id': tool_id,
                        'content': result_text
                    })

            # Adicionar assistant response + tool results ao historico
            extended_messages = messages + [
                {'role': 'assistant', 'content': assistant_content},
                {'role': 'user', 'content': tool_results}
            ]

            # Segunda chamada com resultados das ferramentas
            data = _call_api(model, max_tokens, system_prompt, extended_messages, tools=TOOLS)
            if not data:
                raise Exception('API retornou None no tool loop')

            usage = data.get('usage', {})
            total_input += usage.get('input_tokens', 0)
            total_output += usage.get('output_tokens', 0)

        # Extrair texto final da resposta
        final_text = ''
        for block in data.get('content', []):
            if block.get('type') == 'text':
                final_text += block.get('text', '')

        if not final_text:
            raise Exception('Resposta vazia do Claude')

        return {
            'text': final_text.strip(),
            'input_tokens': total_input,
            'output_tokens': total_output,
            'model': model,
            'cost': estimate_cost(model, total_input, total_output)
        }

    except Exception as e:
        log.error(f'Erro agente: {e}')
        fallback = FALLBACK_RESPONSES[_fallback_idx % len(FALLBACK_RESPONSES)]
        _fallback_idx += 1
        return {
            'text': fallback,
            'input_tokens': total_input,
            'output_tokens': total_output,
            'model': model,
            'cost': estimate_cost(model, total_input, total_output)
        }
