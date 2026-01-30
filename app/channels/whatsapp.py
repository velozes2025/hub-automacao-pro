"""Evolution API v2 client for WhatsApp operations.

All WhatsApp communication goes through this module.
No other module should call Evolution API directly.
"""

import logging
import requests

from app.config import config

log = logging.getLogger('channels.whatsapp')


def _headers():
    return {
        'apikey': config.EVOLUTION_API_KEY or '',
        'Content-Type': 'application/json',
    }


# --- Messaging ---

def send_message(instance_name, phone, text):
    """Send a text message. Returns True on success, False on failure."""
    try:
        r = requests.post(
            f'{config.EVOLUTION_URL}/message/sendText/{instance_name}',
            headers=_headers(),
            json={'number': phone, 'text': text},
            timeout=10,
        )
        if r.status_code in (200, 201):
            return True
        log.warning(f'Send failed ({r.status_code}): {r.text[:200]}')
        # Fallback: textMessage wrapper format
        r = requests.post(
            f'{config.EVOLUTION_URL}/message/sendText/{instance_name}',
            headers=_headers(),
            json={'number': phone, 'textMessage': {'text': text}},
            timeout=10,
        )
        if r.status_code in (200, 201):
            return True
        log.error(f'Send fallback failed ({r.status_code}): {r.text[:200]}')
        return False
    except Exception as e:
        log.error(f'Send error: {e}')
        return False


def set_typing(instance_name, phone, typing=True):
    """Set composing/paused presence indicator."""
    try:
        requests.post(
            f'{config.EVOLUTION_URL}/chat/updatePresence/{instance_name}',
            headers=_headers(),
            json={'number': phone, 'presence': 'composing' if typing else 'paused'},
            timeout=3,
        )
    except Exception:
        pass


# --- Contacts ---

def fetch_all_contacts(instance_name):
    """Fetch all contacts for an instance."""
    try:
        r = requests.post(
            f'{config.EVOLUTION_URL}/chat/findContacts/{instance_name}',
            headers=_headers(),
            json={},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else []
        return []
    except Exception:
        return []


# --- Media ---

def get_base64_media(instance_name, message_key):
    """Download media as base64 from Evolution API."""
    try:
        r = requests.post(
            f'{config.EVOLUTION_URL}/chat/getBase64FromMediaMessage/{instance_name}',
            headers=_headers(),
            json={'message': {'key': message_key}},
            timeout=30,
        )
        if r.status_code in (200, 201):
            return r.json().get('base64', '')
        log.warning(f'Media download failed ({r.status_code})')
        return ''
    except Exception as e:
        log.error(f'Media download error: {e}')
        return ''


def send_audio(instance_name, phone, base64_audio):
    """Send an audio message (voice note) via Evolution API.

    Args:
        instance_name: Evolution API instance name.
        phone: Recipient phone number.
        base64_audio: Base64-encoded audio (OGG/Opus).

    Returns True on success, False on failure.
    """
    try:
        r = requests.post(
            f'{config.EVOLUTION_URL}/message/sendWhatsAppAudio/{instance_name}',
            headers=_headers(),
            json={'number': phone, 'audio': base64_audio},
            timeout=15,
        )
        if r.status_code in (200, 201):
            return True
        log.warning(f'Audio send failed ({r.status_code}): {r.text[:200]}')
        return False
    except Exception as e:
        log.error(f'Audio send error: {e}')
        return False


# --- Instance Management ---

def create_instance(instance_name):
    r = requests.post(
        f'{config.EVOLUTION_URL}/instance/create',
        headers=_headers(),
        json={
            'instanceName': instance_name,
            'qrcode': True,
            'integration': 'WHATSAPP-BAILEYS',
        },
        timeout=15,
    )
    return r.json() if r.status_code in (200, 201) else {'error': r.text}


def get_connection_state(instance_name):
    try:
        r = requests.get(
            f'{config.EVOLUTION_URL}/instance/connectionState/{instance_name}',
            headers=_headers(),
            timeout=5,
        )
        return r.json().get('instance', {}).get('state', 'unknown')
    except Exception:
        return 'error'


def get_qr_code(instance_name):
    try:
        r = requests.get(
            f'{config.EVOLUTION_URL}/instance/connect/{instance_name}',
            headers=_headers(),
            timeout=10,
        )
        return r.json() if r.status_code == 200 else {'error': r.text}
    except Exception as e:
        return {'error': str(e)}


def fetch_all_instances():
    try:
        r = requests.get(
            f'{config.EVOLUTION_URL}/instance/fetchInstances',
            headers=_headers(),
            timeout=10,
        )
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


def delete_instance(instance_name):
    try:
        r = requests.delete(
            f'{config.EVOLUTION_URL}/instance/delete/{instance_name}',
            headers=_headers(),
            timeout=10,
        )
        return r.json()
    except Exception as e:
        return {'error': str(e)}


def logout_instance(instance_name):
    try:
        r = requests.delete(
            f'{config.EVOLUTION_URL}/instance/logout/{instance_name}',
            headers=_headers(),
            timeout=10,
        )
        return r.json()
    except Exception as e:
        return {'error': str(e)}


def set_webhook(instance_name, webhook_url):
    try:
        r = requests.post(
            f'{config.EVOLUTION_URL}/webhook/set/{instance_name}',
            headers=_headers(),
            json={
                'webhook': {
                    'enabled': True,
                    'url': webhook_url,
                    'webhookByEvents': True,
                    'events': ['MESSAGES_UPSERT', 'CONTACTS_UPSERT', 'CONTACTS_UPDATE'],
                }
            },
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False
