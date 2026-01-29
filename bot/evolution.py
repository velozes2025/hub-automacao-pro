import logging
import requests
from config import EVOLUTION_URL, EVOLUTION_API_KEY

log = logging.getLogger('evolution')

_HEADERS = {
    'apikey': EVOLUTION_API_KEY or '',
    'Content-Type': 'application/json'
}

# In-memory cache: LID JID -> resolved phone number
_lid_cache = {}


def resolve_lid_to_phone(instance_name, lid_jid):
    """Resolve a LID JID to a real phone number.

    Order: 1) memory cache, 2) DB mapping, 3) contacts profilePicUrl, 4) contacts pushName.
    Auto-saves resolved mappings to DB for future use.
    """
    import db as _db

    if lid_jid in _lid_cache:
        return _lid_cache[lid_jid]

    # Strategy 1: Check DB mapping table
    try:
        db_phone = _db.get_lid_phone(lid_jid, instance_name)
        if db_phone:
            _lid_cache[lid_jid] = db_phone
            log.info(f'LID resolvido via DB: {lid_jid} -> {db_phone}')
            return db_phone
    except Exception:
        pass

    # Strategy 2+3: Contacts API
    try:
        r = requests.post(
            f'{EVOLUTION_URL}/chat/findContacts/{instance_name}',
            headers=_HEADERS,
            json={},
            timeout=10
        )
        if r.status_code != 200:
            log.warning(f'findContacts falhou ({r.status_code})')
            return None

        contacts = r.json()
        if not isinstance(contacts, list):
            return None

        lid_contact = None
        for c in contacts:
            if c.get('remoteJid') == lid_jid:
                lid_contact = c
                break

        if not lid_contact:
            return None

        pic_url = lid_contact.get('profilePicUrl')
        push_name = lid_contact.get('pushName', '')

        # Strategy 2: Match by profilePicUrl
        if pic_url:
            for c in contacts:
                rjid = c.get('remoteJid', '')
                if rjid.endswith('@s.whatsapp.net') and c.get('profilePicUrl') == pic_url:
                    phone = rjid.split('@')[0]
                    _lid_cache[lid_jid] = phone
                    _db.save_lid_phone(lid_jid, phone, instance_name, push_name)
                    log.info(f'LID resolvido via profilePic: {lid_jid} -> {phone}')
                    return phone

        # Strategy 3: Match by pushName (unique match only)
        if push_name:
            candidates = [
                c for c in contacts
                if c.get('remoteJid', '').endswith('@s.whatsapp.net')
                and c.get('pushName') == push_name
            ]
            if len(candidates) == 1:
                phone = candidates[0]['remoteJid'].split('@')[0]
                _lid_cache[lid_jid] = phone
                _db.save_lid_phone(lid_jid, phone, instance_name, push_name)
                log.info(f'LID resolvido via pushName: {lid_jid} -> {phone}')
                return phone

        log.warning(f'LID nao resolvido: {lid_jid} (push={push_name})')
        return None
    except Exception as e:
        log.error(f'Erro ao resolver LID: {e}')
        return None


def fetch_all_contacts(instance_name):
    """Busca todos os contatos de uma instancia."""
    try:
        r = requests.post(
            f'{EVOLUTION_URL}/chat/findContacts/{instance_name}',
            headers=_HEADERS,
            json={},
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else []
        return []
    except Exception:
        return []


def set_typing(instance_name, phone, typing=True):
    try:
        requests.post(
            f'{EVOLUTION_URL}/chat/updatePresence/{instance_name}',
            headers=_HEADERS,
            json={'number': phone, 'presence': 'composing' if typing else 'paused'},
            timeout=3
        )
    except Exception:
        pass


def send_message(instance_name, phone, text):
    try:
        r = requests.post(
            f'{EVOLUTION_URL}/message/sendText/{instance_name}',
            headers=_HEADERS,
            json={'number': phone, 'text': text},
            timeout=10
        )
        if r.status_code in (200, 201):
            return True
        log.warning(f'Envio falhou ({r.status_code}): {r.text[:200]}')
        # fallback: formato alternativo (textMessage wrapper)
        r = requests.post(
            f'{EVOLUTION_URL}/message/sendText/{instance_name}',
            headers=_HEADERS,
            json={'number': phone, 'textMessage': {'text': text}},
            timeout=10
        )
        if r.status_code in (200, 201):
            return True
        log.error(f'Envio fallback falhou ({r.status_code}): {r.text[:200]}')
        return False
    except Exception as e:
        log.error(f'Erro envio: {e}')
        return False


def create_instance(instance_name):
    r = requests.post(
        f'{EVOLUTION_URL}/instance/create',
        headers=_HEADERS,
        json={
            'instanceName': instance_name,
            'qrcode': True,
            'integration': 'WHATSAPP-BAILEYS'
        },
        timeout=15
    )
    return r.json() if r.status_code in (200, 201) else {'error': r.text}


def get_connection_state(instance_name):
    try:
        r = requests.get(
            f'{EVOLUTION_URL}/instance/connectionState/{instance_name}',
            headers=_HEADERS,
            timeout=5
        )
        return r.json().get('instance', {}).get('state', 'unknown')
    except Exception:
        return 'error'


def get_qr_code(instance_name):
    try:
        r = requests.get(
            f'{EVOLUTION_URL}/instance/connect/{instance_name}',
            headers=_HEADERS,
            timeout=10
        )
        return r.json() if r.status_code == 200 else {'error': r.text}
    except Exception as e:
        return {'error': str(e)}


def fetch_all_instances():
    try:
        r = requests.get(
            f'{EVOLUTION_URL}/instance/fetchInstances',
            headers=_HEADERS,
            timeout=10
        )
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


def delete_instance(instance_name):
    try:
        r = requests.delete(
            f'{EVOLUTION_URL}/instance/delete/{instance_name}',
            headers=_HEADERS,
            timeout=10
        )
        return r.json()
    except Exception as e:
        return {'error': str(e)}


def logout_instance(instance_name):
    try:
        r = requests.delete(
            f'{EVOLUTION_URL}/instance/logout/{instance_name}',
            headers=_HEADERS,
            timeout=10
        )
        return r.json()
    except Exception as e:
        return {'error': str(e)}


def set_webhook(instance_name, webhook_url):
    try:
        r = requests.post(
            f'{EVOLUTION_URL}/webhook/set/{instance_name}',
            headers=_HEADERS,
            json={
                'webhook': {
                    'enabled': True,
                    'url': webhook_url,
                    'webhookByEvents': True,
                    'events': ['MESSAGES_UPSERT']
                }
            },
            timeout=10
        )
        return r.status_code == 200
    except Exception:
        return False
