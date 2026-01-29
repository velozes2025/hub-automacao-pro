"""
Hub Automacao Pro - Bot Multi-Cliente
Webhook unico que atende todas as instancias WhatsApp.
"""
import time
import threading
import logging
from datetime import datetime, timezone
from flask import Flask, request, jsonify

import db
import evolution
import claude_client

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('hub-bot')


def get_phone_from_message(data):
    """Extrai telefone do payload da Evolution API v2."""
    remote_jid = data.get('key', {}).get('remoteJid', '')
    if '@s.whatsapp.net' in remote_jid:
        return remote_jid.split('@')[0]
    if '@lid' in remote_jid:
        return remote_jid
    participant = data.get('key', {}).get('participant', '')
    if participant:
        return participant.split('@')[0]
    return None


def get_text_from_message(data):
    """Extrai texto do payload da Evolution API v2."""
    msg = data.get('message', {})
    return (
        msg.get('conversation')
        or msg.get('extendedTextMessage', {}).get('text')
    )


def is_within_business_hours(empresa):
    """Verifica se esta dentro do horario de atendimento."""
    start = empresa.get('business_hours_start')
    end = empresa.get('business_hours_end')
    if not start or not end:
        return True
    now = datetime.now(timezone.utc).time()
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end


def process_message(payload):
    """Processa mensagem em background thread."""
    try:
        event = payload.get('event', '')
        if event != 'messages.upsert':
            return

        instance_name = payload.get('instance', '')
        data = payload.get('data', {})

        if data.get('key', {}).get('fromMe', False):
            return

        text = get_text_from_message(data)
        if not text:
            return

        phone = get_phone_from_message(data)
        if not phone:
            return

        push_name = data.get('pushName', '')

        # Buscar config da empresa
        empresa = db.get_empresa_by_instance(instance_name)
        if not empresa:
            log.warning(f'Instancia desconhecida ou inativa: {instance_name}')
            return

        empresa_id = str(empresa['id'])

        # Verificar horario de atendimento
        if not is_within_business_hours(empresa):
            msg_fora = empresa.get('outside_hours_message')
            if msg_fora:
                evolution.send_message(instance_name, phone, msg_fora)
            return

        # Indicador de digitacao
        evolution.set_typing(instance_name, phone, True)
        time.sleep(empresa.get('typing_delay_ms', 800) / 1000)

        # Carregar historico
        max_history = empresa.get('max_history_messages', 10)
        history = db.get_conversation_history(empresa_id, phone, max_history)

        # Mensagem de boas-vindas na primeira interacao
        greeting = empresa.get('greeting_message')
        if greeting and len(history) == 0:
            evolution.send_message(instance_name, phone, greeting)
            db.save_message(empresa_id, phone, 'assistant', greeting)
            time.sleep(0.5)

        # Salvar mensagem do usuario
        db.save_message(empresa_id, phone, 'user', text, push_name)
        history.append({'role': 'user', 'content': text})

        # Chamar Claude
        result = claude_client.call_claude(
            system_prompt=empresa.get('system_prompt', ''),
            messages=history,
            model=empresa.get('model', 'claude-3-haiku-20240307'),
            max_tokens=empresa.get('max_tokens', 150)
        )

        response_text = result['text']

        # Salvar resposta
        db.save_message(empresa_id, phone, 'assistant', response_text)

        # Registrar consumo
        db.log_token_usage(
            empresa_id,
            result['model'],
            result['input_tokens'],
            result['output_tokens'],
            result['cost']
        )

        # Parar digitacao e enviar
        evolution.set_typing(instance_name, phone, False)
        evolution.send_message(instance_name, phone, response_text)

        log.info(f'[{instance_name}] {phone}: "{text[:40]}" -> "{response_text[:40]}"')

    except Exception as e:
        log.error(f'Erro ao processar mensagem: {e}', exc_info=True)


@app.route('/webhook', methods=['POST'])
def webhook():
    payload = request.json
    if not payload:
        return jsonify({'ok': False}), 400
    threading.Thread(target=process_message, args=(payload,), daemon=True).start()
    return jsonify({'ok': True}), 200


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': 'hub-bot'}), 200


if __name__ == '__main__':
    log.info('Hub Bot multi-cliente iniciando...')
    db.init_pool()
    log.info('Pool PostgreSQL conectado')
    app.run(host='0.0.0.0', port=3000)
