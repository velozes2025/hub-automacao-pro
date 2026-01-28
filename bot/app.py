"""
Quantrex Bot - Atendimento Humanizado
"""
from flask import Flask, request, jsonify
import requests
import os
import sys
import time
from collections import defaultdict

app = Flask(__name__)
sys.stdout.reconfigure(line_buffering=True)

# Config
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
EVOLUTION_API_KEY = os.getenv('EVOLUTION_API_KEY')
EVOLUTION_URL = os.getenv('EVOLUTION_URL', 'http://evolution:8080')
INSTANCE_NAME = os.getenv('INSTANCE_NAME', 'eva_bot')

# Memoria
conversations = defaultdict(list)


def set_typing(phone, typing=True):
    """Mostra 'digitando...' no WhatsApp"""
    try:
        requests.post(
            f'{EVOLUTION_URL}/chat/updatePresence/{INSTANCE_NAME}',
            headers={'apikey': EVOLUTION_API_KEY, 'Content-Type': 'application/json'},
            json={
                'number': phone,
                'presence': 'composing' if typing else 'paused'
            },
            timeout=3
        )
    except:
        pass


def send_message(phone, text):
    """Envia mensagem"""
    try:
        r = requests.post(
            f'{EVOLUTION_URL}/message/sendText/{INSTANCE_NAME}',
            headers={'apikey': EVOLUTION_API_KEY, 'Content-Type': 'application/json'},
            json={'number': phone, 'textMessage': {'text': text}},
            timeout=10
        )
        return r.status_code in [200, 201]
    except:
        return False


def call_claude(phone):
    """Gera resposta humanizada"""
    try:
        r = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json'
            },
            json={
                'model': 'claude-3-haiku-20240307',
                'max_tokens': 30,
                'system': '''Voce e humano da Quantrex. NUNCA diga que e assistente/bot/IA.

REGRAS:
- MAX 5-8 palavras por resposta
- Casual: "opa", "show", "massa"
- Se perguntarem nome: "pode me chamar de Thiago"
- NUNCA mencione "assistente", "virtual", "ajudar"

Bom: "opa, qual seu nome?"
Bom: "massa, conta mais"
Bom: "show, bora resolver"
Ruim: "Ola! Como posso ajudar voce hoje?"''',
                'messages': conversations[phone]
            },
            timeout=30
        )
        if r.status_code == 200:
            return r.json()['content'][0]['text']
        return "opa, um segundo"
    except:
        return "ja volto"


def get_phone_from_message(data):
    """Extrai telefone de QUALQUER formato"""
    # Tentar remoteJid primeiro
    remote_jid = data.get('data', {}).get('key', {}).get('remoteJid', '')

    if '@s.whatsapp.net' in remote_jid:
        return remote_jid.replace('@s.whatsapp.net', '')

    # Se for @lid, buscar nos chats pelo timestamp
    if '@lid' in remote_jid:
        msg_ts = data.get('data', {}).get('messageTimestamp', 0)
        try:
            r = requests.get(
                f'{EVOLUTION_URL}/chat/findChats/{INSTANCE_NAME}',
                headers={'apikey': EVOLUTION_API_KEY},
                timeout=5
            )
            if r.status_code == 200:
                chats = r.json()
                # Pegar chat com timestamp mais proximo
                best = None
                min_diff = 999999
                for chat in chats:
                    cid = chat.get('id', '')
                    if '@s.whatsapp.net' in cid and cid != '0@s.whatsapp.net':
                        cts = chat.get('lastMsgTimestamp', 0)
                        diff = abs(msg_ts - cts)
                        if diff < min_diff:
                            min_diff = diff
                            best = cid.replace('@s.whatsapp.net', '')
                if best:
                    return best
        except:
            pass

    # Tentar participant (grupos)
    participant = data.get('data', {}).get('key', {}).get('participant', '')
    if '@s.whatsapp.net' in participant:
        return participant.replace('@s.whatsapp.net', '')

    return None


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json

        # Log tudo que chega
        event = data.get('event', '')
        print(f"[EVENT] {event}")

        # So mensagens
        if event != 'messages.upsert':
            return jsonify({'ok': True}), 200

        # Ignorar proprias
        if data.get('data', {}).get('key', {}).get('fromMe'):
            return jsonify({'ok': True}), 200

        # Extrair texto
        message = data.get('data', {}).get('message', {})
        text = message.get('conversation') or message.get('extendedTextMessage', {}).get('text', '')

        if not text:
            return jsonify({'ok': True}), 200

        # PEGAR TELEFONE - ACEITA QUALQUER FORMATO
        phone = get_phone_from_message(data)

        if not phone:
            print("[ERRO] Nao consegui extrair telefone")
            print(f"[DEBUG] data: {data}")
            return jsonify({'ok': True}), 200

        name = data.get('data', {}).get('pushName', 'Cliente')
        print(f"[MSG] {name} ({phone}): {text}")

        # 1. DIGITANDO IMEDIATO
        set_typing(phone, True)

        # 2. DELAY 800ms
        time.sleep(0.8)

        # 3. HISTORICO
        conversations[phone].append({'role': 'user', 'content': text})
        if len(conversations[phone]) > 10:
            conversations[phone] = conversations[phone][-10:]

        # 4. RESPOSTA IA
        reply = call_claude(phone)
        conversations[phone].append({'role': 'assistant', 'content': reply})

        # 5. PARAR DIGITANDO E ENVIAR
        set_typing(phone, False)

        if send_message(phone, reply):
            print(f"[OK] {phone}: {reply}")
        else:
            print(f"[ERRO] Falha ao enviar para {phone}")

        return jsonify({'ok': True}), 200

    except Exception as e:
        print(f"[ERRO] {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/health')
def health():
    return {'status': 'ok'}


if __name__ == '__main__':
    print("Quantrex Bot iniciado - Aceita TODOS os numeros")
    app.run(host='0.0.0.0', port=3000)
