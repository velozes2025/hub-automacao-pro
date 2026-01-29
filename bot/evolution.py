import requests
from config import EVOLUTION_URL, EVOLUTION_API_KEY

_HEADERS = {
    'apikey': EVOLUTION_API_KEY or '',
    'Content-Type': 'application/json'
}


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
        if r.status_code == 200:
            return True
        # fallback: formato alternativo
        r = requests.post(
            f'{EVOLUTION_URL}/message/sendText/{instance_name}',
            headers=_HEADERS,
            json={'number': phone, 'textMessage': {'text': text}},
            timeout=10
        )
        return r.status_code == 200
    except Exception:
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
