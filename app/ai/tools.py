"""Tool definitions and implementations for the AI supervisor.

Each tool has a JSON schema (for Claude) and an execute function.
Tools are tenant-scoped: each tenant configures which tools are enabled.
"""

import logging
import requests

log = logging.getLogger('ai.tools')

# --- Tool Definitions (JSON Schema for Claude API) ---

TOOL_DEFINITIONS = {
    'web_search': {
        'name': 'web_search',
        'description': (
            'Busca informacoes na internet em tempo real. '
            'SEMPRE use esta ferramenta quando o usuario perguntar sobre: '
            'precos (bitcoin, acoes, dolar, cripto), clima/tempo de qualquer cidade, '
            'noticias atuais, eventos, resultados esportivos, informacoes de empresas, '
            'qualquer dado que mude com o tempo, ou QUALQUER pergunta que precise de '
            'informacao atualizada. Na duvida, busque. Voce eh um super agente.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {
                    'type': 'string',
                    'description': 'O que buscar na internet (em portugues ou ingles)',
                }
            },
            'required': ['query'],
        },
    },
    'analyze_website': {
        'name': 'analyze_website',
        'description': (
            'Analisa uma URL e extrai informacoes sobre o site. '
            'Use quando o usuario compartilhar um link ou mencionar um site.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'url': {
                    'type': 'string',
                    'description': 'A URL completa do site para analisar',
                }
            },
            'required': ['url'],
        },
    },
    'lookup_lead': {
        'name': 'lookup_lead',
        'description': (
            'Consulta dados do lead no banco de dados. '
            'Use para verificar informacoes de um contato especifico.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'phone': {
                    'type': 'string',
                    'description': 'Numero de telefone do lead',
                }
            },
            'required': ['phone'],
        },
    },
    'update_lead_stage': {
        'name': 'update_lead_stage',
        'description': (
            'Atualiza o estagio do lead no funil de vendas. '
            'Estagios: new, qualifying, nurturing, closing, support, closed.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'phone': {
                    'type': 'string',
                    'description': 'Numero de telefone do lead',
                },
                'stage': {
                    'type': 'string',
                    'enum': ['new', 'qualifying', 'nurturing', 'closing', 'support', 'closed'],
                    'description': 'Novo estagio do lead',
                },
            },
            'required': ['phone', 'stage'],
        },
    },
    'check_availability': {
        'name': 'check_availability',
        'description': (
            'Verifica se esta dentro do horario de atendimento. '
            'Use quando o cliente perguntar sobre disponibilidade.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {},
        },
    },
}


# --- Tool Implementations ---

def execute_tool(tool_name, tool_input, context=None):
    """Execute a tool and return the result string.

    context: dict with tenant_id, phone, conversation_id, etc.
    """
    ctx = context or {}
    executors = {
        'web_search': _exec_web_search,
        'analyze_website': _exec_analyze_website,
        'lookup_lead': _exec_lookup_lead,
        'update_lead_stage': _exec_update_lead_stage,
        'check_availability': _exec_check_availability,
    }
    executor = executors.get(tool_name)
    if not executor:
        return f'Ferramenta desconhecida: {tool_name}'
    try:
        return executor(tool_input, ctx)
    except Exception as e:
        log.error(f'Tool {tool_name} failed: {e}')
        return f'Erro ao executar {tool_name}: {e}'


def get_tool_definitions(enabled_tools=None):
    """Return tool definition list, filtered by enabled names."""
    if enabled_tools is None:
        enabled_tools = ['web_search']
    return [TOOL_DEFINITIONS[t] for t in enabled_tools if t in TOOL_DEFINITIONS]


# --- Individual Tool Executors ---

def _exec_web_search(inputs, ctx):
    query = inputs.get('query', '')
    log.info(f'Web search: "{query}"')
    try:
        from lxml import html
        r = requests.get(
            'https://html.duckduckgo.com/html/',
            params={'q': query},
            headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'},
            timeout=10,
        )
        tree = html.fromstring(r.text)
        results = []
        for item in tree.xpath('//div[contains(@class,"result")]')[:5]:
            title_els = item.xpath('.//a[contains(@class,"result__a")]')
            snippet_els = item.xpath('.//a[contains(@class,"result__snippet")]')
            title = title_els[0].text_content().strip() if title_els else ''
            snippet = snippet_els[0].text_content().strip() if snippet_els else ''
            if title and snippet:
                results.append(f'- {title}: {snippet}')
        return '\n'.join(results) if results else 'Nenhum resultado encontrado.'
    except Exception as e:
        return f'Erro na busca: {e}'


def _exec_analyze_website(inputs, ctx):
    url = inputs.get('url', '')
    if not url:
        return 'URL nao fornecida.'
    try:
        from lxml import html
        r = requests.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
        })
        tree = html.fromstring(r.text)
        title = tree.xpath('//title/text()')
        meta_desc = tree.xpath('//meta[@name="description"]/@content')
        h1s = tree.xpath('//h1/text()')
        paragraphs = tree.xpath('//p/text()')[:5]

        parts = []
        if title:
            parts.append(f'Titulo: {title[0].strip()}')
        if meta_desc:
            parts.append(f'Descricao: {meta_desc[0].strip()}')
        if h1s:
            parts.append(f'H1: {h1s[0].strip()}')
        if paragraphs:
            text = ' '.join(p.strip() for p in paragraphs if p.strip())[:500]
            parts.append(f'Conteudo: {text}')
        return '\n'.join(parts) if parts else 'Nao foi possivel extrair informacoes do site.'
    except Exception as e:
        return f'Erro ao analisar site: {e}'


def _exec_lookup_lead(inputs, ctx):
    phone = inputs.get('phone', '')
    tenant_id = ctx.get('tenant_id')
    if not phone or not tenant_id:
        return 'Telefone ou tenant nao disponivel.'
    try:
        from app.db import leads
        lead = leads.get_lead(tenant_id, phone)
        if not lead:
            return f'Lead nao encontrado para {phone}.'
        return (
            f'Lead: {lead.get("name", "N/A")}\n'
            f'Telefone: {lead["phone"]}\n'
            f'Empresa: {lead.get("company", "N/A")}\n'
            f'Estagio: {lead.get("stage", "new")}\n'
            f'Criado: {lead.get("created_at", "N/A")}'
        )
    except Exception as e:
        return f'Erro ao consultar lead: {e}'


def _exec_update_lead_stage(inputs, ctx):
    phone = inputs.get('phone', '')
    stage = inputs.get('stage', '')
    tenant_id = ctx.get('tenant_id')
    if not phone or not stage or not tenant_id:
        return 'Dados insuficientes para atualizar estagio.'
    try:
        from app.db import leads
        leads.update_lead_stage(tenant_id, phone, stage)
        return f'Lead {phone} atualizado para estagio: {stage}'
    except Exception as e:
        return f'Erro ao atualizar lead: {e}'


def _exec_check_availability(inputs, ctx):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    # TODO: read tenant business hours from config
    return f'Atendimento disponivel. Horario atual (UTC): {now.strftime("%H:%M")}'
