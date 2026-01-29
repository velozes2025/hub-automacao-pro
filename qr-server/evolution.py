import os
import requests

EVOLUTION_URL = os.getenv('EVOLUTION_URL', 'http://evolution:8080')
EVOLUTION_API_KEY = os.getenv('EVOLUTION_API_KEY', '')

_HEADERS = {
    'apikey': EVOLUTION_API_KEY,
    'Content-Type': 'application/json'
}


def get_connection_state(instance_name):
    try:
        r = requests.get(
            f'{EVOLUTION_URL}/instance/connectionState/{instance_name}',
            headers=_HEADERS, timeout=5
        )
        return r.json().get('instance', {}).get('state', 'unknown')
    except Exception:
        return 'error'


def get_qr_code(instance_name):
    try:
        r = requests.get(
            f'{EVOLUTION_URL}/instance/connect/{instance_name}',
            headers=_HEADERS, timeout=10
        )
        return r.json() if r.status_code == 200 else {'error': r.text}
    except Exception as e:
        return {'error': str(e)}


def create_instance(instance_name):
    try:
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


def delete_instance(instance_name):
    try:
        r = requests.delete(
            f'{EVOLUTION_URL}/instance/delete/{instance_name}',
            headers=_HEADERS, timeout=10
        )
        return r.json()
    except Exception as e:
        return {'error': str(e)}


def logout_instance(instance_name):
    try:
        r = requests.delete(
            f'{EVOLUTION_URL}/instance/logout/{instance_name}',
            headers=_HEADERS, timeout=10
        )
        return r.json()
    except Exception as e:
        return {'error': str(e)}


def fetch_all_instances():
    try:
        r = requests.get(
            f'{EVOLUTION_URL}/instance/fetchInstances',
            headers=_HEADERS, timeout=10
        )
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []
