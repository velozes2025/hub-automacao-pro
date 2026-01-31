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
    'schedule_meeting': {
        'name': 'schedule_meeting',
        'description': (
            'Agenda uma reuniao com o lead. SEMPRE use esta ferramenta quando o cliente '
            'confirmar data e horario para uma reuniao. A ferramenta VALIDA se a data e o '
            'dia da semana batem (ex: 03/02/2026 deve ser terca-feira). '
            'Se houver conflito, retorna erro para voce perguntar ao cliente. '
            'NUNCA agende sem confirmacao explicita do cliente. '
            'A reuniao sera criada automaticamente no Google Calendar.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'phone': {
                    'type': 'string',
                    'description': 'Numero de telefone do lead',
                },
                'date': {
                    'type': 'string',
                    'description': 'Data da reuniao no formato DD/MM/AAAA (ex: 03/02/2026)',
                },
                'time': {
                    'type': 'string',
                    'description': 'Horario da reuniao no formato HH:MM (24h) (ex: 14:00)',
                },
                'day_of_week': {
                    'type': 'string',
                    'description': 'Dia da semana esperado (ex: terca-feira, segunda, quarta)',
                },
                'notes': {
                    'type': 'string',
                    'description': 'Observacoes sobre a reuniao (opcional)',
                },
            },
            'required': ['phone', 'date', 'time'],
        },
    },

    # --- Airtable CRM ---
    'airtable_read': {
        'name': 'airtable_read',
        'description': (
            'Le registros do CRM (Airtable). Tabelas disponiveis:\n'
            '- Leads: campos Nome, Telefone, Email, Empresa, Status, Origem, Interesse, Notas, '
            'Valor Estimado, Responsavel, Data Entrada, Ultima Interacao\n'
            '- Reunioes: campos Titulo, Telefone, Data e Hora, Hora, Tipo, Status, Observacoes, '
            'Resultado, Google Calendar ID\n'
            '- Interacoes: campos Telefone, Tipo, Canal, Mensagem, Status, Responsavel, Data e Hora'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'table': {
                    'type': 'string',
                    'description': 'Nome da tabela: Leads, Reunioes, ou Interacoes',
                },
                'filter': {
                    'type': 'string',
                    'description': 'Formula de filtro (opcional). Ex: {Status}=\'Novo\', {Telefone}=\'5511999\'',
                },
                'max_records': {
                    'type': 'integer',
                    'description': 'Maximo de registros (padrao: 20)',
                },
            },
            'required': ['table'],
        },
    },

    'airtable_create': {
        'name': 'airtable_create',
        'description': (
            'Cria registro no CRM (Airtable). USE OS NOMES EXATOS DOS CAMPOS:\n'
            'Tabela Leads: Nome, Telefone, Email, Empresa, Status (Novo/Qualificando/Nutricao/'
            'Fechando/Suporte/Fechado/Perdido/Em negociacao/Contato inicial), '
            'Origem (WhatsApp/Site/Indicacao/Outro), Interesse, Notas, Valor Estimado, '
            'Data Entrada (formato ISO: 2026-01-31T00:00:00.000Z), Ultima Interacao\n'
            'Tabela Reunioes: Titulo, Telefone, Data e Hora (ISO), Hora, '
            'Tipo (Consulta/Reuniao/Ligacao/Demo/Follow-up), '
            'Status (Agendada/Confirmada/Realizada/Cancelada/Reagendada), Observacoes\n'
            'Tabela Interacoes: Telefone, Tipo, Canal (WhatsApp/Email/Ligacao), '
            'Mensagem, Status (Pendente/Enviado/Respondido/Sem Resposta), Data e Hora'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'table': {
                    'type': 'string',
                    'description': 'Leads, Reunioes, ou Interacoes',
                },
                'fields': {
                    'type': 'object',
                    'description': 'Campos e valores. Use EXATAMENTE os nomes listados na descricao.',
                },
            },
            'required': ['table', 'fields'],
        },
    },

    'airtable_update': {
        'name': 'airtable_update',
        'description': (
            'Atualiza registro existente no CRM (Airtable). '
            'Precisa do ID do registro (recXXXXXX, obtido ao ler) e os campos a atualizar. '
            'Use os mesmos nomes de campos da ferramenta airtable_create.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'table': {
                    'type': 'string',
                    'description': 'Leads, Reunioes, ou Interacoes',
                },
                'record_id': {
                    'type': 'string',
                    'description': 'ID do registro (ex: recXXXXXXXX)',
                },
                'fields': {
                    'type': 'object',
                    'description': 'Campos a atualizar com os nomes exatos.',
                },
            },
            'required': ['table', 'record_id', 'fields'],
        },
    },

    # --- Google Calendar ---
    'google_calendar_list': {
        'name': 'google_calendar_list',
        'description': (
            'Lista os proximos eventos do Google Calendar. '
            'Use para verificar agenda, compromissos, reunioes marcadas.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'max_results': {
                    'type': 'integer',
                    'description': 'Numero maximo de eventos a retornar (padrao: 10)',
                },
            },
            'required': [],
        },
    },

    'google_calendar_check': {
        'name': 'google_calendar_check',
        'description': (
            'Verifica se um horario esta disponivel no Google Calendar. '
            'Use ANTES de agendar uma reuniao para confirmar disponibilidade.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'date': {
                    'type': 'string',
                    'description': 'Data no formato DD/MM/AAAA',
                },
                'time': {
                    'type': 'string',
                    'description': 'Horario no formato HH:MM (24h)',
                },
                'duration_minutes': {
                    'type': 'integer',
                    'description': 'Duracao em minutos (padrao: 60)',
                },
            },
            'required': ['date', 'time'],
        },
    },

    # --- Gmail ---
    'send_email': {
        'name': 'send_email',
        'description': (
            'Envia um email via Gmail. Use para enviar follow-ups, propostas, confirmacoes, '
            'ou qualquer comunicacao por email com leads e clientes. '
            'NUNCA envie email sem o consentimento explicito do cliente ou instrucao do admin.'
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
                    'description': 'Corpo do email (texto simples)',
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
        'schedule_meeting': _exec_schedule_meeting,
        'airtable_read': _exec_airtable_read,
        'airtable_create': _exec_airtable_create,
        'airtable_update': _exec_airtable_update,
        'google_calendar_list': _exec_calendar_list,
        'google_calendar_check': _exec_calendar_check,
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


_DIAS_SEMANA_MAP = {
    0: 'segunda-feira', 1: 'terca-feira', 2: 'quarta-feira',
    3: 'quinta-feira', 4: 'sexta-feira', 5: 'sabado', 6: 'domingo',
}

_DIAS_ALIASES = {
    'segunda': 0, 'segunda-feira': 0, 'seg': 0,
    'terca': 1, 'terca-feira': 1, 'ter': 1, 'terça': 1, 'terça-feira': 1,
    'quarta': 2, 'quarta-feira': 2, 'qua': 2,
    'quinta': 3, 'quinta-feira': 3, 'qui': 3,
    'sexta': 4, 'sexta-feira': 4, 'sex': 4,
    'sabado': 5, 'sab': 5, 'sábado': 5,
    'domingo': 6, 'dom': 6,
}


def _exec_schedule_meeting(inputs, ctx):
    """Schedule a meeting with date validation."""
    from datetime import datetime, timezone, timedelta
    import json as _json

    phone = inputs.get('phone', '')
    date_str = inputs.get('date', '')
    time_str = inputs.get('time', '')
    day_of_week = inputs.get('day_of_week', '')
    notes = inputs.get('notes', '')
    tenant_id = ctx.get('tenant_id')

    if not phone or not date_str or not time_str:
        return 'ERRO: Dados insuficientes. Preciso de telefone, data (DD/MM/AAAA) e horario (HH:MM).'

    # Parse date
    try:
        meeting_date = datetime.strptime(date_str, '%d/%m/%Y')
    except ValueError:
        return f'ERRO: Data "{date_str}" invalida. Use o formato DD/MM/AAAA (ex: 03/02/2026).'

    # Parse time
    try:
        parts = time_str.replace('h', ':').split(':')
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except (ValueError, IndexError):
        return f'ERRO: Horario "{time_str}" invalido. Use o formato HH:MM (ex: 14:00).'

    # Validate day of week
    actual_weekday = meeting_date.weekday()
    actual_day_name = _DIAS_SEMANA_MAP[actual_weekday]

    if day_of_week:
        expected_weekday = _DIAS_ALIASES.get(day_of_week.lower().strip())
        if expected_weekday is not None and expected_weekday != actual_weekday:
            expected_name = _DIAS_SEMANA_MAP[expected_weekday]
            return (
                f'CONFLITO DE DATA: O cliente disse "{day_of_week}" mas {date_str} '
                f'cai em {actual_day_name}, NAO em {expected_name}. '
                f'Pergunte ao cliente: "Voce prefere {date_str} ({actual_day_name}) '
                f'ou quer marcar para a proxima {expected_name}?"'
            )

    # Check if date is in the past
    now_br = datetime.now(timezone(timedelta(hours=-3)))
    if meeting_date.date() < now_br.date():
        return f'ERRO: A data {date_str} ja passou. Hoje e {now_br.strftime("%d/%m/%Y")}. Sugira uma data futura.'

    # Save meeting to lead metadata
    meeting_data = {
        'reuniao_data': date_str,
        'reuniao_hora': f'{hour:02d}:{minute:02d}',
        'reuniao_dia_semana': actual_day_name,
        'reuniao_notas': notes,
        'reuniao_agendada_em': now_br.strftime('%d/%m/%Y %H:%M'),
    }

    if tenant_id:
        try:
            from app.db import leads
            lead = leads.get_lead(tenant_id, phone)
            if lead:
                existing_meta = lead.get('metadata', {}) or {}
                if isinstance(existing_meta, str):
                    existing_meta = _json.loads(existing_meta) if existing_meta else {}
                existing_meta.update(meeting_data)
                from app.db import execute
                execute(
                    """UPDATE leads_v2
                       SET metadata = %s, stage = CASE WHEN stage = 'new' THEN 'qualifying' ELSE stage END,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE tenant_id = %s AND phone = %s""",
                    (_json.dumps(existing_meta), str(tenant_id), phone),
                )
        except Exception as e:
            log.error(f'Failed to save meeting to lead: {e}')

    # Create Google Calendar event
    calendar_link = ''
    try:
        from app.integrations import google_calendar
        start_dt = meeting_date.replace(hour=hour, minute=minute)
        push_name = ctx.get('push_name', '')
        summary = f'Reuniao - {push_name or phone}'
        description = f'Lead: {phone}\nNome: {push_name}\nNotas: {notes}'
        event = google_calendar.create_event(
            summary=summary,
            start_datetime=start_dt,
            description=description,
        )
        if event:
            calendar_link = f'\nGoogle Calendar: {event["link"]}'
            log.info(f'[CALENDAR] Meeting synced: {event["id"]}')
    except Exception as e:
        log.warning(f'[CALENDAR] Sync failed (meeting saved locally): {e}')

    return (
        f'REUNIAO AGENDADA COM SUCESSO!\n'
        f'Data: {date_str} ({actual_day_name})\n'
        f'Horario: {hour:02d}:{minute:02d}\n'
        f'Telefone: {phone}'
        f'{calendar_link}\n'
        f'Confirme ao cliente com esses dados exatos.'
    )


# --- Airtable CRM Executors ---

def _exec_airtable_read(inputs, ctx):
    """Read records from Airtable."""
    from app.integrations import airtable_client

    table = inputs.get('table', '')
    if not table:
        return 'ERRO: nome da tabela obrigatorio.'

    if not airtable_client.is_configured():
        return 'ERRO: Airtable nao configurado. Admin precisa definir AIRTABLE_API_KEY e AIRTABLE_BASE_ID.'

    filter_formula = inputs.get('filter', None)
    max_records = inputs.get('max_records', 20)

    records = airtable_client.list_records(table, max_records=max_records, filter_formula=filter_formula)
    if records is None:
        return f'ERRO: Nao foi possivel ler a tabela "{table}". Verifique se ela existe no Airtable.'
    if not records:
        return f'Nenhum registro encontrado em "{table}".'

    lines = []
    for rec in records[:30]:
        rec_id = rec.pop('id', '')
        parts = [f'{k}: {v}' for k, v in rec.items() if v]
        lines.append(f'[{rec_id}] {" | ".join(parts)}')
    result = '\n'.join(lines)
    if len(records) > 30:
        result += f'\n... (mais {len(records) - 30} registros)'
    return result


def _exec_airtable_create(inputs, ctx):
    """Create a record in Airtable."""
    from app.integrations import airtable_client

    table = inputs.get('table', '')
    fields = inputs.get('fields', {})

    if not table or not fields:
        return 'ERRO: table e fields sao obrigatorios.'

    if not airtable_client.is_configured():
        return 'ERRO: Airtable nao configurado. Admin precisa definir AIRTABLE_API_KEY e AIRTABLE_BASE_ID.'

    record = airtable_client.create_record(table, fields)
    if record:
        return f'OK: Registro criado em "{table}" (id: {record.get("id", "")})'
    return f'ERRO: Falha ao criar registro em "{table}".'


def _exec_airtable_update(inputs, ctx):
    """Update a record in Airtable."""
    from app.integrations import airtable_client

    table = inputs.get('table', '')
    record_id = inputs.get('record_id', '')
    fields = inputs.get('fields', {})

    if not table or not record_id or not fields:
        return 'ERRO: table, record_id e fields sao obrigatorios.'

    if not airtable_client.is_configured():
        return 'ERRO: Airtable nao configurado.'

    record = airtable_client.update_record(table, record_id, fields)
    if record:
        return f'OK: Registro {record_id} atualizado em "{table}".'
    return f'ERRO: Falha ao atualizar registro {record_id} em "{table}".'


# --- Google Calendar Executors ---

def _exec_calendar_list(inputs, ctx):
    """List upcoming calendar events."""
    from app.integrations import google_calendar

    max_results = inputs.get('max_results', 10)
    events = google_calendar.list_upcoming(max_results=max_results)

    if events is None:
        return 'ERRO: Nao foi possivel acessar o calendario.'
    if not events:
        return 'Nenhum evento futuro encontrado.'

    lines = []
    for ev in events:
        start = ev.get('start', '')
        lines.append(f'- {ev["summary"]} | {start}')
        if ev.get('attendees'):
            lines.append(f'  Participantes: {", ".join(ev["attendees"])}')
    return '\n'.join(lines)


def _exec_calendar_check(inputs, ctx):
    """Check calendar availability."""
    from app.integrations import google_calendar

    date_str = inputs.get('date', '')
    time_str = inputs.get('time', '')
    duration = inputs.get('duration_minutes', 60)

    if not date_str or not time_str:
        return 'ERRO: date e time sao obrigatorios (DD/MM/AAAA e HH:MM).'

    available = google_calendar.check_availability(date_str, time_str, duration)
    if available is None:
        return 'ERRO: Nao foi possivel verificar disponibilidade.'
    if available:
        return f'DISPONIVEL: O horario {date_str} as {time_str} esta livre.'
    return f'OCUPADO: Ja existe compromisso em {date_str} as {time_str}. Sugira outro horario.'


# --- Gmail Executor ---

def _exec_send_email(inputs, ctx):
    """Send email via Gmail SMTP."""
    from app.integrations import google_gmail

    to = inputs.get('to', '')
    subject = inputs.get('subject', '')
    body = inputs.get('body', '')

    if not to or not subject or not body:
        return 'ERRO: to, subject e body sao obrigatorios.'

    if not google_gmail.is_configured():
        return 'ERRO: Gmail SMTP nao configurado. Admin precisa definir GMAIL_ADDRESS e GMAIL_APP_PASSWORD.'

    result = google_gmail.send_email(to, subject, body)
    if result:
        return f'EMAIL ENVIADO com sucesso para {to}.'
    return 'ERRO: Falha ao enviar email. Verifique as configuracoes do Gmail.'
