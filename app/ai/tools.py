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
    'airtable_save_lead': {
        'name': 'airtable_save_lead',
        'description': (
            'Salva ou atualiza um lead no Airtable. '
            'Use AUTOMATICAMENTE quando voce identificar dados importantes do cliente '
            '(nome, empresa, telefone, email, interesse, observacoes). '
            'Nao precisa pedir permissao — salve sempre que tiver dados novos.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'name': {
                    'type': 'string',
                    'description': 'Nome completo do lead',
                },
                'phone': {
                    'type': 'string',
                    'description': 'Telefone do lead (com DDD)',
                },
                'email': {
                    'type': 'string',
                    'description': 'Email do lead (se fornecido)',
                },
                'company': {
                    'type': 'string',
                    'description': 'Nome da empresa do lead',
                },
                'interest': {
                    'type': 'string',
                    'description': 'O que o lead demonstrou interesse (resumo curto)',
                },
                'stage': {
                    'type': 'string',
                    'enum': ['new', 'qualifying', 'nurturing', 'closing', 'closed'],
                    'description': 'Estagio atual do lead no funil',
                },
                'notes': {
                    'type': 'string',
                    'description': 'Observacoes relevantes sobre a conversa',
                },
            },
            'required': ['name', 'phone'],
        },
    },
    'airtable_search': {
        'name': 'airtable_search',
        'description': (
            'Busca leads no Airtable por telefone ou nome. '
            'Use para verificar se um contato ja existe na base.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'search_term': {
                    'type': 'string',
                    'description': 'Telefone ou nome para buscar',
                },
            },
            'required': ['search_term'],
        },
    },
    'send_email': {
        'name': 'send_email',
        'description': (
            'Envia um email via Gmail. '
            'Use quando o cliente pedir para receber algo por email, '
            'ou quando precisar enviar proposta, resumo, ou informacao por email. '
            'Pergunte o email do destinatario se nao souber.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'to': {
                    'type': 'string',
                    'description': 'Email do destinatario',
                },
                'subject': {
                    'type': 'string',
                    'description': 'Assunto do email',
                },
                'body': {
                    'type': 'string',
                    'description': 'Corpo do email em texto simples',
                },
            },
            'required': ['to', 'subject', 'body'],
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
        'airtable_save_lead': _exec_airtable_save_lead,
        'airtable_search': _exec_airtable_search,
        'send_email': _exec_send_email,
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


# --- Airtable Tools ---

def _exec_airtable_save_lead(inputs, ctx):
    from app.config import config
    if not config.AIRTABLE_API_KEY or not config.AIRTABLE_BASE_ID:
        return 'Airtable nao configurado. Defina AIRTABLE_API_KEY e AIRTABLE_BASE_ID no .env'

    name = inputs.get('name', '')
    phone = inputs.get('phone', '') or ctx.get('phone', '')
    email = inputs.get('email', '')
    company = inputs.get('company', '')
    interest = inputs.get('interest', '')
    stage = inputs.get('stage', 'new')
    notes = inputs.get('notes', '')

    if not name or not phone:
        return 'Nome e telefone sao obrigatorios.'

    table = config.AIRTABLE_TABLE_NAME
    base_id = config.AIRTABLE_BASE_ID

    # Build fields (only include non-empty values)
    fields = {'Nome': name, 'Telefone': phone, 'Estagio': stage}
    if email:
        fields['Email'] = email
    if company:
        fields['Empresa'] = company
    if interest:
        fields['Interesse'] = interest
    if notes:
        fields['Observacoes'] = notes

    # Search for existing record by phone
    try:
        search_url = f'https://api.airtable.com/v0/{base_id}/{table}'
        headers = {
            'Authorization': f'Bearer {config.AIRTABLE_API_KEY}',
            'Content-Type': 'application/json',
        }

        # Search by phone
        search_resp = requests.get(
            search_url,
            headers=headers,
            params={'filterByFormula': f'{{Telefone}}="{phone}"', 'maxRecords': 1},
            timeout=10,
        )

        if search_resp.status_code == 200:
            records = search_resp.json().get('records', [])
            if records:
                # Update existing record
                record_id = records[0]['id']
                update_resp = requests.patch(
                    f'{search_url}/{record_id}',
                    headers=headers,
                    json={'fields': fields},
                    timeout=10,
                )
                if update_resp.status_code == 200:
                    log.info(f'[AIRTABLE] Updated lead: {phone}')
                    return f'Lead {name} ({phone}) atualizado no Airtable com sucesso.'
                return f'Erro ao atualizar no Airtable: {update_resp.status_code}'

        # Create new record
        create_resp = requests.post(
            search_url,
            headers=headers,
            json={'fields': fields},
            timeout=10,
        )
        if create_resp.status_code == 200:
            log.info(f'[AIRTABLE] Created lead: {phone}')
            return f'Lead {name} ({phone}) salvo no Airtable com sucesso.'
        return f'Erro ao criar no Airtable: {create_resp.status_code} - {create_resp.text[:200]}'

    except Exception as e:
        log.error(f'[AIRTABLE] Error: {e}')
        return f'Erro ao acessar Airtable: {e}'


def _exec_airtable_search(inputs, ctx):
    from app.config import config
    if not config.AIRTABLE_API_KEY or not config.AIRTABLE_BASE_ID:
        return 'Airtable nao configurado. Defina AIRTABLE_API_KEY e AIRTABLE_BASE_ID no .env'

    search_term = inputs.get('search_term', '')
    if not search_term:
        return 'Termo de busca nao fornecido.'

    table = config.AIRTABLE_TABLE_NAME
    base_id = config.AIRTABLE_BASE_ID
    headers = {
        'Authorization': f'Bearer {config.AIRTABLE_API_KEY}',
        'Content-Type': 'application/json',
    }

    try:
        # Search by phone OR name
        formula = f'OR(FIND("{search_term}", {{Telefone}}), FIND("{search_term}", {{Nome}}))'
        resp = requests.get(
            f'https://api.airtable.com/v0/{base_id}/{table}',
            headers=headers,
            params={'filterByFormula': formula, 'maxRecords': 5},
            timeout=10,
        )

        if resp.status_code != 200:
            return f'Erro ao buscar no Airtable: {resp.status_code}'

        records = resp.json().get('records', [])
        if not records:
            return f'Nenhum lead encontrado para "{search_term}".'

        results = []
        for rec in records:
            f = rec.get('fields', {})
            results.append(
                f'- {f.get("Nome", "N/A")} | {f.get("Telefone", "N/A")} | '
                f'{f.get("Empresa", "")} | Estagio: {f.get("Estagio", "new")}'
            )
        return f'Encontrados {len(records)} leads:\n' + '\n'.join(results)

    except Exception as e:
        log.error(f'[AIRTABLE] Search error: {e}')
        return f'Erro ao buscar no Airtable: {e}'


# --- Gmail Tool ---

def _exec_send_email(inputs, ctx):
    from app.config import config
    if not config.GMAIL_ADDRESS or not config.GMAIL_APP_PASSWORD:
        return 'Gmail nao configurado. Defina GMAIL_ADDRESS e GMAIL_APP_PASSWORD no .env'

    to_email = inputs.get('to', '')
    subject = inputs.get('subject', '')
    body = inputs.get('body', '')

    if not to_email or not subject or not body:
        return 'Destinatario, assunto e corpo do email sao obrigatorios.'

    # Basic email validation
    if '@' not in to_email or '.' not in to_email:
        return f'Email invalido: {to_email}'

    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg = MIMEMultipart()
        msg['From'] = config.GMAIL_ADDRESS
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=15) as server:
            server.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
            server.send_message(msg)

        log.info(f'[GMAIL] Email sent to {to_email}: "{subject}"')
        return f'Email enviado com sucesso para {to_email}.'

    except smtplib.SMTPAuthenticationError:
        return ('Erro de autenticacao Gmail. Verifique se GMAIL_APP_PASSWORD '
                'e uma Senha de App (nao a senha normal da conta).')
    except Exception as e:
        log.error(f'[GMAIL] Send error: {e}')
        return f'Erro ao enviar email: {e}'
