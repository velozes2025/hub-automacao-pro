"""WhatsApp-based admin control for bot management.

Allows the admin to send /commands from their iPhone via WhatsApp
to control the bot without opening a terminal.

All mutable state lives in Redis. The module is stateless by design.
"""

import logging
import json
from datetime import datetime, timezone

from app.config import config

log = logging.getLogger('services.admin_control')


# ---------------------------------------------------------------------------
# Helper functions (module-level, used by message_handler.py)
# ---------------------------------------------------------------------------

def is_admin_command(data, instance_name):
    """Check if this webhook payload is an admin slash command.

    Criteria:
    1. fromMe is True (sent from the bot's own number)
    2. Message text starts with '/'
    3. ADMIN_NUMBER is configured (acts as on/off switch)
    4. NOT from a group (remoteJid must not contain @g.us)
    """
    if not config.ADMIN_NUMBER:
        return False

    if not data.get('key', {}).get('fromMe', False):
        return False

    remote_jid = data.get('key', {}).get('remoteJid', '')
    if '@g.us' in remote_jid:
        return False

    msg = data.get('message', {})
    text = (msg.get('conversation')
            or msg.get('extendedTextMessage', {}).get('text', ''))
    if not text or not text.strip().startswith('/'):
        return False

    return True


def is_admin_message(data, instance_name):
    """Check if this webhook payload is a natural-language admin message.

    Only activates when admin messages their OWN number (self-chat / saved messages).
    This prevents intercepting normal messages the admin sends to clients.

    Criteria:
    1. fromMe is True
    2. ADMIN_NUMBER is configured
    3. NOT from a group
    4. remoteJid matches ADMIN_NUMBER (self-chat only)
    5. Has text content (non-empty, no '/' prefix)
    """
    if not config.ADMIN_NUMBER:
        return False

    if not data.get('key', {}).get('fromMe', False):
        return False

    remote_jid = data.get('key', {}).get('remoteJid', '')
    if '@g.us' in remote_jid:
        return False

    # Only activate NLP in self-chat (admin messaging their own number)
    remote_phone = remote_jid.split('@')[0] if '@' in remote_jid else ''
    if remote_phone != config.ADMIN_NUMBER:
        return False

    msg = data.get('message', {})
    text = (msg.get('conversation')
            or msg.get('extendedTextMessage', {}).get('text', ''))
    if not text or not text.strip():
        return False

    # Slash commands are handled by is_admin_command — skip here
    if text.strip().startswith('/'):
        return False

    return True


def is_globally_paused(instance_name):
    """Check if bot is globally paused for this instance."""
    r = _get_redis()
    if not r:
        return False
    try:
        return bool(r.get(f'admin:paused:{instance_name}'))
    except Exception:
        return False


def is_chat_paused(instance_name, phone):
    """Check if a specific chat is paused."""
    r = _get_redis()
    if not r:
        return False
    try:
        return bool(r.get(f'admin:pausedchat:{instance_name}:{phone}'))
    except Exception:
        return False


def is_chat_taken_over(instance_name, phone):
    """Check if admin has taken over a specific chat."""
    r = _get_redis()
    if not r:
        return False
    try:
        return bool(r.get(f'admin:takeover:{instance_name}:{phone}'))
    except Exception:
        return False


def log_admin_error(instance_name, error_msg):
    """Push an error to the admin errors list in Redis."""
    if not instance_name:
        return
    r = _get_redis()
    if not r:
        return
    try:
        key = f'admin:errors:{instance_name}'
        ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
        r.lpush(key, f'[{ts}] {error_msg}')
        r.ltrim(key, 0, config.ADMIN_ERROR_LOG_MAX - 1)
    except Exception:
        pass


def _get_redis():
    """Get Redis client. Returns None if unavailable."""
    try:
        from app.db.redis_client import get_redis
        return get_redis()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# AdminController class
# ---------------------------------------------------------------------------

class AdminController:
    """Processes admin commands received via WhatsApp."""

    def __init__(self, instance_name, account, redis_client):
        self.instance_name = instance_name
        self.account = account
        self.tenant_id = str(account['tenant_id'])
        self.account_id = str(account['id'])
        self.r = redis_client

    def handle_command(self, text):
        """Parse a /command and return the response text."""
        parts = text.strip().split(None, 1)
        cmd = parts[0].lower().lstrip('/')
        args = parts[1] if len(parts) > 1 else ''

        commands = {
            'help': self._cmd_help,
            'status': self._cmd_status,
            'pause': self._cmd_pause,
            'resume': self._cmd_resume,
            'restart': self._cmd_restart,
            'chats': self._cmd_chats,
            'chat': self._cmd_chat,
            'takeover': self._cmd_takeover,
            'release': self._cmd_release,
            'pausechat': self._cmd_pausechat,
            'resumechat': self._cmd_resumechat,
            'send': self._cmd_send,
            'reply': self._cmd_reply,
            'correct': self._cmd_correct,
            'setprompt': self._cmd_setprompt,
            'getprompt': self._cmd_getprompt,
            'saveprompt': self._cmd_saveprompt,
            'settemp': self._cmd_settemp,
            'addblock': self._cmd_addblock,
            'removeblock': self._cmd_removeblock,
            'tenants': self._cmd_tenants,
            'tenant': self._cmd_tenant_info,
            'logs': self._cmd_logs,
            'errors': self._cmd_errors,
            'clearerrors': self._cmd_clearerrors,
        }

        handler = commands.get(cmd)
        if not handler:
            return (f'Comando nao reconhecido: /{cmd}\n\n'
                    f'Digite /help para ver comandos disponiveis.')

        try:
            return handler(args)
        except Exception as e:
            log.error(f'[ADMIN] Command /{cmd} error: {e}', exc_info=True)
            log_admin_error(self.instance_name, f'/{cmd}: {e}')
            return f'Erro ao executar /{cmd}: {str(e)[:200]}'

    # -------------------------------------------------------------------
    # NATURAL LANGUAGE CONTROL (v6.0 — conversational agent)
    # -------------------------------------------------------------------

    def handle_natural_message(self, text):
        """Full conversational admin: understand intent, gather context, act, respond naturally."""
        # 1) Gather live system context for the AI
        context = self._gather_system_context()

        # 2) Call AI with full context + admin message
        result = self._converse_with_admin(text, context)
        if not result:
            return 'Nao consegui processar. Tenta de novo ou manda /help.'

        # 3) Execute any actions the AI decided on
        action_results = self._execute_actions(result.get('actions', []))

        # 4) Build final response
        response = result.get('response', '')
        if action_results:
            response += '\n\n' + '\n'.join(action_results)

        return response or 'Feito.'

    def _gather_system_context(self):
        """Collect live system state to give the AI full awareness."""
        from app.db import conversations as conv_db
        from app.db import tenants as tenants_db
        from app.channels import whatsapp

        parts = []

        # Bot status
        is_paused = bool(self.r.get(f'admin:paused:{self.instance_name}'))
        conn_state = 'desconhecido'
        try:
            conn_state = whatsapp.get_connection_state(self.instance_name)
        except Exception:
            pass
        parts.append(f'BOT: {"PAUSADO" if is_paused else "ATIVO"} | Conexao: {conn_state}')

        # Active chats
        try:
            convs = conv_db.list_conversations(self.tenant_id, limit=20)
            if convs:
                chat_lines = []
                for c in convs:
                    phone = c.get('contact_phone', '?')
                    name = c.get('contact_name') or '?'
                    flags = []
                    if self.r.get(f'admin:pausedchat:{self.instance_name}:{phone}'):
                        flags.append('PAUSADO')
                    if self.r.get(f'admin:takeover:{self.instance_name}:{phone}'):
                        flags.append('TAKEOVER')
                    if self.r.get(f'block:{self.instance_name}:{phone}'):
                        flags.append('BLOQUEADO')
                    flag_str = f' [{",".join(flags)}]' if flags else ''
                    chat_lines.append(f'  {name} ({phone}){flag_str}')
                parts.append(f'CHATS ATIVOS ({len(convs)}):\n' + '\n'.join(chat_lines))
            else:
                parts.append('CHATS ATIVOS: nenhum')
        except Exception:
            parts.append('CHATS: erro ao buscar')

        # Tenants
        try:
            tenants = tenants_db.list_tenants(status=None)
            if tenants:
                t_lines = []
                for t in tenants:
                    st = 'ON' if t.get('status') == 'active' else 'OFF'
                    t_lines.append(f'  [{st}] {t.get("name","?")} (slug:{t.get("slug","?")}, id:{t.get("id","?")})')
                parts.append(f'TENANTS ({len(tenants)}):\n' + '\n'.join(t_lines))
        except Exception:
            pass

        # Recent errors
        try:
            errors = self.r.lrange(f'admin:errors:{self.instance_name}', 0, 4)
            if errors:
                parts.append(f'ERROS RECENTES ({len(errors)}):\n  ' + '\n  '.join(errors))
        except Exception:
            pass

        # Last chat (for /reply context)
        last_chat = self.r.get(f'admin:last_chat:{self.instance_name}')
        if last_chat:
            parts.append(f'ULTIMO CHAT ATIVO: {last_chat}')

        parts.append(f'INSTANCIA: {self.instance_name}')

        return '\n'.join(parts)

    def _converse_with_admin(self, text, context):
        """Call AI as a conversational admin assistant with memory.

        Returns:
            {
              "actions": [{"type": "...", ...}, ...],
              "response": "Resposta natural aqui"
            }
        """
        from app.ai.client import call_api
        from datetime import datetime, timezone, timedelta

        # Build conversation history from Redis (last 10 messages)
        history_key = f'admin:nlp_history:{self.instance_name}'
        messages = []
        try:
            raw_history = self.r.lrange(history_key, 0, 9)
            if raw_history:
                for entry in reversed(raw_history):  # oldest first
                    parsed = json.loads(entry)
                    messages.append(parsed)
        except Exception:
            pass

        # Add current message
        messages.append({'role': 'user', 'content': text})

        # Current datetime in Brazil
        br_tz = timezone(timedelta(hours=-3))
        now = datetime.now(br_tz)
        date_str = now.strftime('%d/%m/%Y %H:%M (BRT)')

        system_prompt = (
            'Voce e o assistente pessoal do Thiago, dono do Hub Automacao Pro.\n'
            'Thiago esta te mandando mensagem pelo WhatsApp para controlar o bot.\n'
            'Responda de forma natural, curta e direta, como um assistente pessoal.\n\n'
            f'AGORA: {date_str}\n\n'
            'ESTADO ATUAL DO SISTEMA:\n'
            f'{context}\n\n'
            'ACOES QUE VOCE PODE EXECUTAR:\n'
            'Retorne um JSON com "actions" (lista de acoes) e "response" (sua resposta natural).\n\n'
            'TIPOS DE ACAO:\n'
            '{"type":"status"} - mostrar status\n'
            '{"type":"pause_bot"} - pausar bot globalmente\n'
            '{"type":"resume_bot"} - retomar bot\n'
            '{"type":"restart"} - reiniciar agente\n'
            '{"type":"view_chat","phone":"NUM"} - ver historico de um chat\n'
            '{"type":"takeover","phone":"NUM"} - assumir chat\n'
            '{"type":"release","phone":"NUM"} - devolver chat ao bot\n'
            '{"type":"pause_chat","phone":"NUM"} - pausar chat especifico\n'
            '{"type":"resume_chat","phone":"NUM"} - retomar chat especifico\n'
            '{"type":"send_message","phone":"NUM","text":"MSG"} - enviar msg como bot\n'
            '{"type":"reply","text":"MSG"} - responder ultimo chat ativo\n'
            '{"type":"set_prompt","text":"PROMPT"} - override temporario do prompt\n'
            '{"type":"save_prompt","text":"PROMPT"} - salvar prompt no banco\n'
            '{"type":"save_prompt","tenant_slug":"SLUG","text":"PROMPT"} - prompt outro tenant\n'
            '{"type":"get_prompt"} - ver prompt atual\n'
            '{"type":"set_temp","value":0.7} - alterar temperatura\n'
            '{"type":"block","phone":"NUM"} - bloquear contato\n'
            '{"type":"unblock","phone":"NUM"} - desbloquear\n'
            '{"type":"list_tenants"} - listar tenants\n'
            '{"type":"view_tenant","slug":"SLUG"} - ver detalhes tenant\n'
            '{"type":"get_errors"} - ver erros\n'
            '{"type":"clear_errors"} - limpar erros\n'
            '{"type":"shell","command":"CMD"} - executar comando shell\n'
            '{"type":"db_query","sql":"SQL"} - executar SQL no PostgreSQL\n'
            '{"type":"edit_file","path":"PATH","old":"OLD","new":"NEW"} - editar arquivo\n'
            '{"type":"read_file","path":"PATH"} - ler arquivo\n\n'
            'GOOGLE CALENDAR — GERAR LINKS REAIS:\n'
            'Quando o admin pedir link de reuniao/evento, gere um link REAL usando o formato:\n'
            'https://calendar.google.com/calendar/render?action=TEMPLATE&text=TITULO&dates=INICIO/FIM&details=DETALHES\n'
            'Formato das datas: YYYYMMDDTHHmmSSZ (UTC, entao horario BRT + 3h)\n'
            'Exemplo: reuniao amanha 4/fev as 14h BRT = 20260204T170000Z/20260204T180000Z\n'
            'NUNCA use placeholder como [link] ou [inserir aqui]. Gere o link COMPLETO.\n\n'
            'REGRAS:\n'
            '1. SEMPRE retorne JSON puro: {"actions":[...],"response":"..."}\n'
            '2. Se nao precisa executar acao, retorne "actions":[] com so a resposta.\n'
            '3. Se o admin menciona um NOME de contato, busque o numero no contexto.\n'
            '   Se nao encontrar, pergunte na resposta.\n'
            '4. Responda em portugues, curto e direto.\n'
            '5. Pode executar MULTIPLAS acoes de uma vez.\n'
            '6. NUNCA coloque markdown (```), so o JSON puro.\n'
            '7. Para "manda mensagem pro X sobre Y", gere o texto da mensagem voce mesmo.\n'
            '8. Voce tem HISTORICO da conversa. Use o contexto anterior para entender referências\n'
            '   como "ele", "manda pra ela", "o mesmo", etc.\n'
            '9. Para alterar codigo use edit_file. Apos editar, shell docker restart hub-bot.\n'
            '10. Projeto: /root/hub-automacao-pro/\n'
        )

        reply_text = ''
        try:
            response = call_api(
                model='claude-3-5-haiku-20241022',
                max_tokens=600,
                system_prompt=system_prompt,
                messages=messages,
            )
            if not response:
                log.warning('[ADMIN NLP] AI returned None')
                return None

            content = response.get('content', [])
            for block in content:
                if block.get('type') == 'text':
                    reply_text = block.get('text', '')
                    break
            if not reply_text:
                log.warning('[ADMIN NLP] AI returned empty text')
                return None

            log.info(f'[ADMIN NLP] AI raw: {reply_text[:300]}')

            reply_text = reply_text.strip()
            if reply_text.startswith('```'):
                reply_text = reply_text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()

            parsed = json.loads(reply_text)
            log.info(f'[ADMIN NLP] Actions: {len(parsed.get("actions", []))} | Response: {str(parsed.get("response",""))[:80]}')

            # Save conversation to Redis history (last 10 exchanges)
            try:
                ai_response_text = parsed.get('response', '')
                self.r.lpush(history_key, json.dumps({'role': 'user', 'content': text}))
                self.r.lpush(history_key, json.dumps({'role': 'assistant', 'content': ai_response_text}))
                self.r.ltrim(history_key, 0, 19)  # keep 20 entries (10 exchanges)
                self.r.expire(history_key, 3600)  # expire after 1h of inactivity
            except Exception:
                pass

            return parsed

        except (json.JSONDecodeError, TypeError) as e:
            log.warning(f'[ADMIN NLP] JSON parse failed: {e} | raw: {reply_text[:300]}')
            # If AI returned plain text, use it as response
            if reply_text and not reply_text.startswith('{'):
                return {'actions': [], 'response': reply_text}
            return None
        except Exception as e:
            log.error(f'[ADMIN NLP] AI call failed: {e}', exc_info=True)
            return None

    def _execute_actions(self, actions):
        """Execute a list of actions returned by the AI. Returns list of result strings."""
        results = []
        for action in actions:
            try:
                result = self._execute_single_action(action)
                if result:
                    results.append(result)
            except Exception as e:
                log.error(f'[ADMIN NLP] Action failed: {action} — {e}')
                results.append(f'Erro em {action.get("type","?")}: {str(e)[:100]}')
        return results

    def _execute_single_action(self, action):
        """Execute one action and return a result string (or None if silent)."""
        from app.db import tenants as tenants_db
        from app.channels import whatsapp

        atype = action.get('type', '')

        if atype == 'pause_bot':
            self.r.set(f'admin:paused:{self.instance_name}', '1')
            return None  # AI response already covers it

        if atype == 'resume_bot':
            self.r.delete(f'admin:paused:{self.instance_name}')
            return None

        if atype == 'restart':
            self.r.delete(f'admin:paused:{self.instance_name}')
            self.r.delete(f'admin:prompt_override:{self.instance_name}')
            self.r.delete(f'admin:temp_override:{self.instance_name}')
            for key in self.r.keys(f'admin:takeover:{self.instance_name}:*'):
                self.r.delete(key)
            for key in self.r.keys(f'admin:pausedchat:{self.instance_name}:*'):
                self.r.delete(key)
            return None

        if atype == 'view_chat':
            return self._cmd_chat(action.get('phone', ''))

        if atype == 'takeover':
            phone = self._clean_phone(action.get('phone', ''))
            if phone:
                self.r.set(f'admin:takeover:{self.instance_name}:{phone}',
                           '1', ex=config.ADMIN_TAKEOVER_TTL)
                self.r.set(f'admin:last_chat:{self.instance_name}', phone, ex=3600)
            return None

        if atype == 'release':
            phone = self._clean_phone(action.get('phone', ''))
            if phone:
                self.r.delete(f'admin:takeover:{self.instance_name}:{phone}')
            return None

        if atype == 'pause_chat':
            phone = self._clean_phone(action.get('phone', ''))
            if phone:
                self.r.set(f'admin:pausedchat:{self.instance_name}:{phone}', '1')
            return None

        if atype == 'resume_chat':
            phone = self._clean_phone(action.get('phone', ''))
            if phone:
                self.r.delete(f'admin:pausedchat:{self.instance_name}:{phone}')
            return None

        if atype == 'send_message':
            phone = self._clean_phone(action.get('phone', ''))
            text = action.get('text', '')
            if phone and text:
                sent = whatsapp.send_message(self.instance_name, phone, text)
                if sent:
                    self._save_admin_message(phone, text)
                    self.r.set(f'admin:last_chat:{self.instance_name}', phone, ex=3600)
                    return f'Msg enviada para {phone}'
                return f'Falha ao enviar para {phone}'
            return None

        if atype == 'reply':
            last_chat = self.r.get(f'admin:last_chat:{self.instance_name}')
            text = action.get('text', '')
            if last_chat and text:
                sent = whatsapp.send_message(self.instance_name, last_chat, text)
                if sent:
                    self._save_admin_message(last_chat, text)
                    return f'Respondido para {last_chat}'
            return None

        if atype == 'set_prompt':
            text = action.get('text', '')
            if text:
                self.r.set(f'admin:prompt_override:{self.instance_name}', text)
            return None

        if atype == 'save_prompt':
            text = action.get('text', '')
            slug = action.get('tenant_slug', '')
            if text:
                if slug:
                    tenant = tenants_db.get_tenant_by_slug(slug)
                    if tenant:
                        tenants_db.upsert_agent_config(str(tenant['id']), system_prompt=text)
                    else:
                        return f'Tenant nao encontrado: {slug}'
                else:
                    tenants_db.upsert_agent_config(self.tenant_id, system_prompt=text)
            return None

        if atype == 'get_prompt':
            slug = action.get('tenant_slug', '')
            if slug:
                tenant = tenants_db.get_tenant_by_slug(slug)
                if tenant:
                    agent = tenants_db.get_active_agent_config(str(tenant['id']))
                    prompt = (agent or {}).get('system_prompt', '(nenhum)')
                    if len(prompt) > 800:
                        prompt = prompt[:800] + '...'
                    return f'Prompt [{slug}]:\n{prompt}'
                return f'Tenant nao encontrado: {slug}'
            return self._cmd_getprompt('')

        if atype == 'set_temp':
            val = action.get('value')
            if val is not None:
                self.r.set(f'admin:temp_override:{self.instance_name}', str(val))
            return None

        if atype == 'block':
            phone = self._clean_phone(action.get('phone', ''))
            if phone:
                self.r.set(f'block:{self.instance_name}:{phone}', '1')
            return None

        if atype == 'unblock':
            phone = self._clean_phone(action.get('phone', ''))
            if phone:
                self.r.delete(f'block:{self.instance_name}:{phone}')
            return None

        if atype == 'list_tenants':
            return self._cmd_tenants('')

        if atype == 'view_tenant':
            return self._cmd_tenant_info(action.get('slug', ''))

        if atype == 'get_errors':
            return self._cmd_errors('')

        if atype == 'clear_errors':
            self.r.delete(f'admin:errors:{self.instance_name}')
            return None

        if atype == 'status':
            return self._cmd_status('')

        # --- INFRASTRUCTURE ACTIONS (full power) ---

        if atype == 'shell':
            return self._exec_shell(action.get('command', ''))

        if atype == 'db_query':
            return self._exec_sql(action.get('sql', ''))

        if atype == 'read_file':
            return self._exec_read_file(action.get('path', ''))

        if atype == 'edit_file':
            return self._exec_edit_file(
                action.get('path', ''),
                action.get('old', ''),
                action.get('new', ''),
            )

        return None

    # -----------------------------------------------------------------------
    # BASIC CONTROL
    # -----------------------------------------------------------------------

    def _cmd_help(self, args):
        return (
            'COMANDOS DO BOT\n'
            '========================\n\n'
            'LINGUAGEM NATURAL\n'
            'Voce pode digitar normalmente!\n'
            'Ex: "como ta o bot", "pausa tudo",\n'
            '"manda pro 55219... oi", "mostra os chats"\n\n'
            'CONTROLE\n'
            '/help - Lista comandos\n'
            '/status - Status do bot\n'
            '/pause - Pausar bot (global)\n'
            '/resume - Retomar bot\n'
            '/restart - Reiniciar agente\n\n'
            'CHATS\n'
            '/chats - Listar chats ativos\n'
            '/chat NUMERO - Ver conversa\n'
            '/takeover NUMERO - Assumir chat\n'
            '/release NUMERO - Devolver ao bot\n'
            '/pausechat NUMERO - Pausar chat\n'
            '/resumechat NUMERO - Retomar chat\n\n'
            'INTERVENCAO\n'
            '/send NUMERO MSG - Enviar como bot\n'
            '/reply MSG - Responder ultimo chat\n'
            '/correct MSG - Corrigir ultima resposta\n\n'
            'CONFIG\n'
            '/setprompt TEXTO - Override prompt (Redis)\n'
            '/saveprompt [SLUG] TEXTO - Salvar no banco\n'
            '/getprompt [SLUG] - Ver prompt (atual ou tenant)\n'
            '/settemp 0.7 - Alterar temperatura\n'
            '/addblock NUMERO - Bloquear numero\n'
            '/removeblock NUMERO - Desbloquear\n\n'
            'TENANTS\n'
            '/tenants - Listar todos os tenants\n'
            '/tenant SLUG - Info detalhada do tenant\n\n'
            'DEBUG\n'
            '/logs - Ver ultimos logs\n'
            '/errors - Ver erros\n'
            '/clearerrors - Limpar erros'
        )

    def _cmd_status(self, args):
        from app.channels import whatsapp
        from app.db import conversations as conv_db

        # Connection state
        conn_state = whatsapp.get_connection_state(self.instance_name)

        # Pause state
        is_paused = bool(self.r.get(f'admin:paused:{self.instance_name}'))
        status_label = 'PAUSADO' if is_paused else 'ATIVO'

        # Counts
        takeover_keys = self.r.keys(f'admin:takeover:{self.instance_name}:*')
        paused_keys = self.r.keys(f'admin:pausedchat:{self.instance_name}:*')
        block_keys = self.r.keys(f'block:{self.instance_name}:*')

        # Active chats from DB
        try:
            convs = conv_db.list_conversations(self.tenant_id, limit=100)
            active_count = len(convs) if convs else 0
        except Exception:
            active_count = '?'

        # Error count
        error_count = self.r.llen(f'admin:errors:{self.instance_name}') or 0

        return (
            f'STATUS DO BOT\n'
            f'========================\n\n'
            f'Status: {status_label}\n'
            f'Conexao: {conn_state}\n'
            f'Chats ativos: {active_count}\n'
            f'Chats em takeover: {len(takeover_keys)}\n'
            f'Chats pausados: {len(paused_keys)}\n'
            f'Contatos bloqueados: {len(block_keys)}\n'
            f'Erros recentes: {error_count}\n\n'
            f'Instancia: {self.instance_name}\n'
            f'Atualizado: {datetime.now(timezone.utc).strftime("%H:%M:%S UTC")}'
        )

    def _cmd_pause(self, args):
        self.r.set(f'admin:paused:{self.instance_name}', '1')
        return ('BOT PAUSADO\n\n'
                'O bot nao respondera mais mensagens automaticamente.\n'
                'Digite /resume para retomar.')

    def _cmd_resume(self, args):
        self.r.delete(f'admin:paused:{self.instance_name}')
        return ('BOT RETOMADO\n\n'
                'O bot voltou a responder mensagens automaticamente.')

    def _cmd_restart(self, args):
        # Clear ephemeral state
        self.r.delete(f'admin:paused:{self.instance_name}')
        self.r.delete(f'admin:prompt_override:{self.instance_name}')
        self.r.delete(f'admin:temp_override:{self.instance_name}')
        # Clear takeovers
        for key in self.r.keys(f'admin:takeover:{self.instance_name}:*'):
            self.r.delete(key)
        for key in self.r.keys(f'admin:pausedchat:{self.instance_name}:*'):
            self.r.delete(key)
        return ('AGENTE REINICIADO\n\n'
                'Estado limpo: pause, takeovers, prompts e chats pausados resetados.')

    # -----------------------------------------------------------------------
    # CHAT MANAGEMENT
    # -----------------------------------------------------------------------

    def _cmd_chats(self, args):
        from app.db import conversations as conv_db

        try:
            convs = conv_db.list_conversations(self.tenant_id, limit=15)
        except Exception as e:
            return f'Erro ao listar chats: {e}'

        if not convs:
            return 'Nenhum chat ativo no momento.'

        lines = [f'CHATS ATIVOS ({len(convs)})', '========================', '']
        for i, c in enumerate(convs, 1):
            phone = c.get('contact_phone', '?')
            name = c.get('contact_name') or 'Desconhecido'
            last_msg = c.get('last_message_at', '')
            if hasattr(last_msg, 'strftime'):
                last_msg = last_msg.strftime('%d/%m %H:%M')

            flags = ''
            if self.r.get(f'admin:pausedchat:{self.instance_name}:{phone}'):
                flags += ' [PAUSADO]'
            if self.r.get(f'admin:takeover:{self.instance_name}:{phone}'):
                flags += ' [TAKEOVER]'
            if self.r.get(f'block:{self.instance_name}:{phone}'):
                flags += ' [BLOQUEADO]'

            lines.append(f'{i}. {name}{flags}')
            lines.append(f'   {phone}')
            lines.append(f'   Ultima msg: {last_msg}')
            lines.append('')

        return '\n'.join(lines)

    def _cmd_chat(self, args):
        phone = self._clean_phone(args)
        if not phone:
            return 'Formato: /chat 5511999999999'

        from app.db import conversations as conv_db

        try:
            convs = conv_db.list_conversations(self.tenant_id, limit=100)
            conv = None
            for c in (convs or []):
                if c.get('contact_phone', '').endswith(phone) or phone in c.get('contact_phone', ''):
                    conv = c
                    break
            if not conv:
                return f'Chat nao encontrado: {phone}'

            history = conv_db.get_message_history(str(conv['id']), limit=10)
        except Exception as e:
            return f'Erro ao buscar chat: {e}'

        name = conv.get('contact_name') or 'Desconhecido'
        lines = [f'CHAT: {name} ({conv.get("contact_phone", "")})',
                 '========================', '']

        for msg in history:
            role = 'VOCE' if msg.get('role') == 'assistant' else 'CLIENTE'
            content = msg.get('content', '')[:200]
            ts = msg.get('created_at', '')
            if hasattr(ts, 'strftime'):
                ts = ts.strftime('%H:%M')
            lines.append(f'[{ts}] {role}: {content}')

        if not history:
            lines.append('(sem mensagens)')

        return '\n'.join(lines)

    def _cmd_takeover(self, args):
        phone = self._clean_phone(args)
        if not phone:
            return 'Formato: /takeover 5511999999999'

        self.r.set(f'admin:takeover:{self.instance_name}:{phone}',
                   '1', ex=config.ADMIN_TAKEOVER_TTL)
        self.r.set(f'admin:last_chat:{self.instance_name}', phone, ex=3600)

        hours = config.ADMIN_TAKEOVER_TTL // 3600
        return (f'TAKEOVER ATIVADO\n\n'
                f'Chat: {phone}\n'
                f'O bot nao respondera mais neste chat.\n'
                f'Auto-expira em {hours}h.\n\n'
                f'Use /release {phone} para devolver ao bot.')

    def _cmd_release(self, args):
        phone = self._clean_phone(args)
        if not phone:
            return 'Formato: /release 5511999999999'

        self.r.delete(f'admin:takeover:{self.instance_name}:{phone}')
        return (f'CHAT LIBERADO\n\n'
                f'Chat {phone} devolvido ao bot.\n'
                f'O bot voltara a responder automaticamente.')

    def _cmd_pausechat(self, args):
        phone = self._clean_phone(args)
        if not phone:
            return 'Formato: /pausechat 5511999999999'

        self.r.set(f'admin:pausedchat:{self.instance_name}:{phone}', '1')
        return f'Chat {phone} pausado.\nUse /resumechat {phone} para retomar.'

    def _cmd_resumechat(self, args):
        phone = self._clean_phone(args)
        if not phone:
            return 'Formato: /resumechat 5511999999999'

        self.r.delete(f'admin:pausedchat:{self.instance_name}:{phone}')
        return f'Chat {phone} retomado. Bot voltara a responder.'

    # -----------------------------------------------------------------------
    # MANUAL INTERVENTION
    # -----------------------------------------------------------------------

    def _cmd_send(self, args):
        import re
        match = re.match(r'^(\d+)\s+(.+)$', args, re.DOTALL)
        if not match:
            return 'Formato: /send 5511999999999 Sua mensagem aqui'

        phone = match.group(1)
        message = match.group(2)

        from app.channels import whatsapp
        sent = whatsapp.send_message(self.instance_name, phone, message)

        if sent:
            # Save to conversation history for AI context coherence
            self._save_admin_message(phone, message)
            self.r.set(f'admin:last_chat:{self.instance_name}', phone, ex=3600)
            return f'Mensagem enviada para {phone}:\n"{message[:200]}"'
        return f'Falha ao enviar para {phone}. Verifique o numero.'

    def _cmd_reply(self, args):
        if not args:
            return 'Formato: /reply Sua resposta aqui'

        last_chat = self.r.get(f'admin:last_chat:{self.instance_name}')
        if not last_chat:
            return 'Nenhum chat ativo para responder. Use /send NUMERO MSG.'

        from app.channels import whatsapp
        sent = whatsapp.send_message(self.instance_name, last_chat, args)

        if sent:
            self._save_admin_message(last_chat, args)
            return f'Respondido para {last_chat}:\n"{args[:200]}"'
        return f'Falha ao responder para {last_chat}.'

    def _cmd_correct(self, args):
        if not args:
            return 'Formato: /correct Nova resposta correta'

        last_chat = self.r.get(f'admin:last_chat:{self.instance_name}')
        if not last_chat:
            return 'Nenhum chat para corrigir.'

        correction = f'Correcao: {args}'

        from app.channels import whatsapp
        sent = whatsapp.send_message(self.instance_name, last_chat, correction)

        if sent:
            self._save_admin_message(last_chat, correction)
            return f'Correcao enviada para {last_chat}.'
        return f'Falha ao enviar correcao para {last_chat}.'

    # -----------------------------------------------------------------------
    # CONFIGURATION
    # -----------------------------------------------------------------------

    def _cmd_setprompt(self, args):
        if not args:
            return 'Formato: /setprompt Seu novo prompt aqui'

        self.r.set(f'admin:prompt_override:{self.instance_name}', args)
        preview = args[:150] + ('...' if len(args) > 150 else '')
        return f'Prompt atualizado (Redis override)!\n\nNovo prompt:\n"{preview}"'

    def _cmd_getprompt(self, args):
        from app.db import tenants as tenants_db

        # If args provided, try to find tenant by slug
        target_tenant_id = self.tenant_id
        target_label = 'ATUAL'
        if args and args.strip():
            slug = args.strip().split()[0]
            tenant = tenants_db.get_tenant_by_slug(slug)
            if tenant:
                target_tenant_id = str(tenant['id'])
                target_label = slug
            else:
                return f'Tenant nao encontrado: {slug}\nUse /tenants para listar.'

        # Check for runtime override first
        override = self.r.get(f'admin:prompt_override:{self.instance_name}')
        if override and target_tenant_id == self.tenant_id:
            source = 'OVERRIDE (Redis)'
            prompt = override
        else:
            agent_config = tenants_db.get_active_agent_config(target_tenant_id)
            prompt = (agent_config or {}).get('system_prompt', '(nenhum prompt configurado)')
            source = 'BANCO DE DADOS'

        # Truncate for WhatsApp
        if len(prompt) > 1400:
            prompt = prompt[:1400] + '\n\n... (truncado)'

        return f'PROMPT [{target_label}] [{source}]\n========================\n\n{prompt}'

    def _cmd_saveprompt(self, args):
        """Persist prompt directly to database (not just Redis override)."""
        from app.db import tenants as tenants_db

        if not args:
            return 'Formato: /saveprompt [SLUG] Seu prompt aqui\nSem slug = tenant atual.'

        parts = args.strip().split(None, 1)
        first_word = parts[0]
        rest = parts[1] if len(parts) > 1 else ''

        # Check if first word is a tenant slug
        tenant = tenants_db.get_tenant_by_slug(first_word)
        if tenant and rest:
            target_id = str(tenant['id'])
            target_label = first_word
            prompt_text = rest
        else:
            # No slug — apply to current tenant
            target_id = self.tenant_id
            target_label = 'atual'
            prompt_text = args

        try:
            tenants_db.upsert_agent_config(target_id, system_prompt=prompt_text)
            preview = prompt_text[:150] + ('...' if len(prompt_text) > 150 else '')
            return (f'PROMPT SALVO NO BANCO [{target_label}]\n'
                    f'========================\n\n"{preview}"')
        except Exception as e:
            return f'Erro ao salvar prompt: {str(e)[:200]}'

    def _cmd_settemp(self, args):
        try:
            temp = float(args.strip())
        except (ValueError, AttributeError):
            return 'Formato: /settemp 0.7 (valor entre 0 e 2)'

        if temp < 0 or temp > 2:
            return 'Temperatura deve ser entre 0 e 2.'

        self.r.set(f'admin:temp_override:{self.instance_name}', str(temp))
        return f'Temperatura alterada para: {temp}'

    def _cmd_addblock(self, args):
        phone = self._clean_phone(args)
        if not phone:
            return 'Formato: /addblock 5511999999999'

        # Reuses the EXISTING block key pattern from message_handler.py
        self.r.set(f'block:{self.instance_name}:{phone}', '1')
        return f'Numero {phone} bloqueado.\nO bot nao respondera mais este contato.'

    def _cmd_removeblock(self, args):
        phone = self._clean_phone(args)
        if not phone:
            return 'Formato: /removeblock 5511999999999'

        self.r.delete(f'block:{self.instance_name}:{phone}')
        return f'Numero {phone} desbloqueado.'

    # -----------------------------------------------------------------------
    # TENANT MANAGEMENT
    # -----------------------------------------------------------------------

    def _cmd_tenants(self, args):
        """List all tenants."""
        from app.db import tenants as tenants_db

        try:
            tenants = tenants_db.list_tenants(status=None)
        except Exception as e:
            return f'Erro ao listar tenants: {e}'

        if not tenants:
            return 'Nenhum tenant cadastrado.'

        lines = [f'TENANTS ({len(tenants)})', '========================', '']
        for t in tenants:
            status_icon = 'ON' if t.get('status') == 'active' else 'OFF'
            slug = t.get('slug', '?')
            name = t.get('name', '?')
            tid = t.get('id', '?')

            # Check accounts for this tenant
            try:
                accounts = tenants_db.list_whatsapp_accounts(str(tid))
                instances = [a.get('instance_name', '') for a in (accounts or [])]
            except Exception:
                instances = []

            lines.append(f'[{status_icon}] {name}')
            lines.append(f'   slug: {slug} | id: {tid}')
            if instances:
                lines.append(f'   instancias: {", ".join(instances)}')
            lines.append('')

        return '\n'.join(lines)

    def _cmd_tenant_info(self, args):
        """Show detailed info for a tenant."""
        from app.db import tenants as tenants_db

        if not args or not args.strip():
            return 'Formato: /tenant SLUG\nUse /tenants para listar.'

        slug = args.strip().split()[0]
        tenant = tenants_db.get_tenant_by_slug(slug)
        if not tenant:
            return f'Tenant nao encontrado: {slug}\nUse /tenants para listar.'

        tid = str(tenant['id'])
        lines = [
            f'TENANT: {tenant.get("name", "?")}',
            '========================',
            f'Slug: {slug}',
            f'ID: {tid}',
            f'Status: {tenant.get("status", "?")}',
        ]

        # Agent config
        try:
            agent = tenants_db.get_active_agent_config(tid)
            if agent:
                prompt = (agent.get('system_prompt', '') or '')[:200]
                lines.append(f'\nPrompt ({len(agent.get("system_prompt", "") or "")} chars):')
                lines.append(f'"{prompt}..."' if len(agent.get('system_prompt', '') or '') > 200 else f'"{prompt}"')
                lines.append(f'Modelo: {agent.get("model", "default")}')
                lines.append(f'Temperatura: {agent.get("temperature", "default")}')
            else:
                lines.append('\n(sem agent config)')
        except Exception:
            lines.append('\n(erro ao buscar config)')

        # WhatsApp accounts
        try:
            accounts = tenants_db.list_whatsapp_accounts(tid)
            if accounts:
                lines.append(f'\nInstancias WhatsApp ({len(accounts)}):')
                for a in accounts:
                    lines.append(f'  - {a.get("instance_name", "?")} [{a.get("status", "?")}]')
        except Exception:
            pass

        return '\n'.join(lines)

    # -----------------------------------------------------------------------
    # LOGS & DEBUG
    # -----------------------------------------------------------------------

    def _cmd_logs(self, args):
        return self._cmd_errors(args)

    def _cmd_errors(self, args):
        key = f'admin:errors:{self.instance_name}'
        errors = self.r.lrange(key, 0, 19)  # Last 20

        if not errors:
            return 'Nenhum erro registrado.'

        lines = [f'ERROS RECENTES ({len(errors)})', '========================', '']
        for err in errors:
            lines.append(err)

        return '\n'.join(lines)

    def _cmd_clearerrors(self, args):
        self.r.delete(f'admin:errors:{self.instance_name}')
        return 'Erros limpos.'

    # -----------------------------------------------------------------------
    # INFRASTRUCTURE (shell, SQL, files)
    # -----------------------------------------------------------------------

    def _exec_shell(self, command):
        """Execute a shell command on the server. Returns output truncated for WhatsApp."""
        import subprocess
        if not command:
            return 'Nenhum comando fornecido.'

        log.info(f'[ADMIN SHELL] {command}')
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=30, cwd='/root/hub-automacao-pro',
            )
            output = result.stdout or ''
            if result.stderr:
                output += '\n' + result.stderr
            output = output.strip()
            if not output:
                output = f'(exit code: {result.returncode})'
            # Truncate for WhatsApp
            if len(output) > 2000:
                output = output[:2000] + '\n... (truncado)'
            return output
        except subprocess.TimeoutExpired:
            return 'Comando excedeu timeout de 30s.'
        except Exception as e:
            return f'Erro: {str(e)[:200]}'

    def _exec_sql(self, sql):
        """Execute a SQL query via the app's DB connection."""
        if not sql:
            return 'Nenhuma query fornecida.'

        log.info(f'[ADMIN SQL] {sql[:100]}')
        try:
            from app.db import query as db_query, execute as db_execute

            sql_stripped = sql.strip().rstrip(';')
            upper = sql_stripped.upper().lstrip()

            if upper.startswith('SELECT') or upper.startswith('WITH'):
                rows = db_query(sql_stripped)
                if not rows:
                    return '(nenhum resultado)'
                # Format as text table
                lines = []
                for i, row in enumerate(rows[:20]):
                    if i == 0:
                        lines.append(' | '.join(str(k) for k in row.keys()))
                        lines.append('-' * 40)
                    lines.append(' | '.join(str(v)[:50] for v in row.values()))
                if len(rows) > 20:
                    lines.append(f'... (+{len(rows)-20} linhas)')
                output = '\n'.join(lines)
                if len(output) > 2000:
                    output = output[:2000] + '\n... (truncado)'
                return output
            else:
                db_execute(sql_stripped)
                return f'Query executada: {sql_stripped[:100]}'
        except Exception as e:
            return f'Erro SQL: {str(e)[:300]}'

    def _exec_read_file(self, path):
        """Read a file and return its content."""
        if not path:
            return 'Nenhum caminho fornecido.'

        log.info(f'[ADMIN FILE] Read: {path}')
        try:
            with open(path, 'r') as f:
                content = f.read()
            if len(content) > 2000:
                content = content[:2000] + '\n... (truncado)'
            return content or '(arquivo vazio)'
        except FileNotFoundError:
            return f'Arquivo nao encontrado: {path}'
        except Exception as e:
            return f'Erro ao ler: {str(e)[:200]}'

    def _exec_edit_file(self, path, old, new):
        """Replace text in a file (exact string match)."""
        if not path or not old:
            return 'Parametros incompletos para editar arquivo.'

        log.info(f'[ADMIN FILE] Edit: {path} — replacing {len(old)} chars')
        try:
            with open(path, 'r') as f:
                content = f.read()

            if old not in content:
                return f'Texto nao encontrado no arquivo {path}'

            new_content = content.replace(old, new, 1)

            with open(path, 'w') as f:
                f.write(new_content)

            return f'Arquivo editado: {path}'
        except FileNotFoundError:
            return f'Arquivo nao encontrado: {path}'
        except Exception as e:
            return f'Erro ao editar: {str(e)[:200]}'

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _clean_phone(self, text):
        """Extract phone number from text, keeping only digits."""
        import re
        digits = re.sub(r'[^\d]', '', text.strip())
        return digits if len(digits) >= 8 else ''

    def _save_admin_message(self, phone, message):
        """Save an admin-sent message to conversation history for AI context."""
        try:
            from app.db import conversations as conv_db
            convs = conv_db.list_conversations(self.tenant_id, limit=100)
            conv = None
            for c in (convs or []):
                if c.get('contact_phone', '').endswith(phone) or phone in c.get('contact_phone', ''):
                    conv = c
                    break
            if conv:
                conv_db.save_message(
                    str(conv['id']), 'assistant', message,
                    {'source': 'admin_manual'}
                )
        except Exception as e:
            log.error(f'[ADMIN] Failed to save manual message: {e}')
