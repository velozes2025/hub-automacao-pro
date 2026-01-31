"""Automation rules: reengagement, business hours, etc."""

import time
import logging

from app.db import conversations as conv_db
from app.channels import whatsapp, sender
from app.ai.prompts import is_real_name, detect_language
from app.config import config

log = logging.getLogger('services.automation')

# --- Reengagement messages ---

_REENGAGE_PT = [
    'Oi{nome}! Fiquei pensando sobre o que conversamos. Se tiver alguma duvida, to por aqui.',
    'E ai{nome}, tudo certo? Fico a disposicao se precisar de algo.',
    '{nome_ou_oi}, se quiser continuar de onde paramos, e so me chamar.',
]
_REENGAGE_EN = [
    'Hey{nome}! Just checking in. Let me know if you have any questions.',
    'Hi{nome}, still here if you need anything!',
    '{nome_ou_oi}, feel free to reach out whenever you are ready.',
]
_REENGAGE_ES = [
    'Hola{nome}! Quedo a tu disposicion si tienes alguna duda.',
    '{nome_ou_oi}, si necesitas algo, aqui estoy.',
    'Hola{nome}, seguimos cuando quieras!',
]

_reengage_idx = 0


def get_reengage_message(push_name='', language='pt'):
    """Get a varied reengagement message."""
    global _reengage_idx

    nome = ''
    nome_ou_oi = 'Oi'
    if push_name and is_real_name(push_name):
        first = push_name.strip().split()[0]
        nome = f' {first}'
        nome_ou_oi = first

    if language == 'en':
        msgs = _REENGAGE_EN
        if not nome:
            nome_ou_oi = 'Hey'
    elif language == 'es':
        msgs = _REENGAGE_ES
        if not nome:
            nome_ou_oi = 'Hola'
    else:
        msgs = _REENGAGE_PT

    msg = msgs[_reengage_idx % len(msgs)]
    _reengage_idx += 1
    return msg.format(nome=nome, nome_ou_oi=nome_ou_oi)


def run_reengagement(tenant_id):
    """Check for stale conversations and send reengagement messages.

    Called periodically by the reengagement worker.
    """
    stale = conv_db.get_stale_conversations(
        tenant_id,
        stale_minutes=config.REENGAGE_CHECK_MINUTES,
        max_reengagement=2,
    )
    if not stale:
        return 0

    log.info(f'[REENGAGE] Found {len(stale)} stale conversations for tenant {tenant_id}')
    sent_count = 0

    for conv in stale:
        instance_name = conv.get('instance_name', '')
        phone = conv.get('contact_phone', '')
        contact_name = conv.get('contact_name', '')
        conversation_id = str(conv['id'])

        # Detect language from last messages
        language = conv.get('language', 'pt')
        try:
            history = conv_db.get_message_history(conversation_id, limit=3)
            user_msgs = [m for m in history if m['role'] == 'user']
            if user_msgs:
                language = detect_language(user_msgs[-1]['content'])
        except Exception:
            pass

        msg = get_reengage_message(contact_name, language)

        whatsapp.set_typing(instance_name, phone, True)
        time.sleep(2.5)
        whatsapp.set_typing(instance_name, phone, False)
        sent = whatsapp.send_message(instance_name, phone, msg)

        if sent:
            conv_db.increment_reengagement(conversation_id)
            conv_db.save_message(conversation_id, 'assistant', msg, {'source': 'reengagement'})
            sent_count += 1
            log.info(f'[REENGAGE] Sent to {phone} ({instance_name})')
        else:
            log.warning(f'[REENGAGE] Failed to send to {phone} ({instance_name})')

        time.sleep(3)

    return sent_count
