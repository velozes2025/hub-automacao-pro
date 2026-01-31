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
    """Check if this webhook payload is an admin command.

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
            'settemp': self._cmd_settemp,
            'addblock': self._cmd_addblock,
            'removeblock': self._cmd_removeblock,
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

    # -----------------------------------------------------------------------
    # BASIC CONTROL
    # -----------------------------------------------------------------------

    def _cmd_help(self, args):
        return (
            'COMANDOS DO BOT\n'
            '========================\n\n'
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
            '/setprompt TEXTO - Alterar prompt\n'
            '/getprompt - Ver prompt atual\n'
            '/settemp 0.7 - Alterar temperatura\n'
            '/addblock NUMERO - Bloquear numero\n'
            '/removeblock NUMERO - Desbloquear\n\n'
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
        return f'Prompt atualizado!\n\nNovo prompt:\n"{preview}"'

    def _cmd_getprompt(self, args):
        # Check for runtime override first
        override = self.r.get(f'admin:prompt_override:{self.instance_name}')
        if override:
            source = 'OVERRIDE (Redis)'
            prompt = override
        else:
            # Fall back to DB agent config
            from app.db import tenants as tenants_db
            agent_config = tenants_db.get_active_agent_config(self.tenant_id)
            prompt = (agent_config or {}).get('system_prompt', '(nenhum prompt configurado)')
            source = 'BANCO DE DADOS'

        # Truncate for WhatsApp
        if len(prompt) > 1400:
            prompt = prompt[:1400] + '\n\n... (truncado)'

        return f'PROMPT ATUAL [{source}]\n========================\n\n{prompt}'

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
