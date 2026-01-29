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
    """Extrai telefone do payload da Evolution API v2.
    Tenta remoteJid primeiro; se for LID, usa participant ou pushName lookup.
    """
    remote_jid = data.get('key', {}).get('remoteJid', '')

    # Formato normal: 5511999999999@s.whatsapp.net
    if '@s.whatsapp.net' in remote_jid:
        return remote_jid.split('@')[0]

    # Formato LID: precisa do remoteJid completo para envio
    if '@lid' in remote_jid:
        # Tenta participant como alternativa (tem numero real em grupos)
        participant = data.get('key', {}).get('participant', '')
        if participant and '@s.whatsapp.net' in participant:
            return participant.split('@')[0]
        # Retorna o remoteJid completo para usar no envio
        return remote_jid

    # Fallback: participant
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

        # Resolver LID para numero real (WhatsApp usa LID internamente)
        send_phone = phone
        if '@lid' in phone:
            resolved = evolution.resolve_lid_to_phone(instance_name, phone)
            if resolved:
                send_phone = resolved
            else:
                log.warning(f'[{instance_name}] LID nao resolvido: {phone}')

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
                evolution.send_message(instance_name, send_phone, msg_fora)
            return

        # Indicador de digitacao
        evolution.set_typing(instance_name, send_phone, True)
        time.sleep(empresa.get('typing_delay_ms', 800) / 1000)

        # Usar send_phone para DB tambem (consistencia de historico)
        db_phone = send_phone

        # Carregar historico
        max_history = empresa.get('max_history_messages', 10)
        history = db.get_conversation_history(empresa_id, db_phone, max_history)

        # Mensagem de boas-vindas na primeira interacao
        greeting = empresa.get('greeting_message')
        if greeting and len(history) == 0:
            evolution.send_message(instance_name, send_phone, greeting)
            db.save_message(empresa_id, db_phone, 'assistant', greeting)
            time.sleep(0.5)

        # Salvar mensagem do usuario
        db.save_message(empresa_id, db_phone, 'user', text, push_name)
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
        db.save_message(empresa_id, db_phone, 'assistant', response_text)

        # Registrar consumo
        db.log_token_usage(
            empresa_id,
            result['model'],
            result['input_tokens'],
            result['output_tokens'],
            result['cost']
        )

        # Parar digitacao e enviar
        evolution.set_typing(instance_name, send_phone, False)
        sent = evolution.send_message(instance_name, send_phone, response_text)

        if sent:
            log.info(f'[{instance_name}] {send_phone}: "{text[:40]}" -> "{response_text[:40]}"')
        else:
            log.error(f'[{instance_name}] FALHA ENVIO para {send_phone}. Resposta: "{response_text[:40]}"')

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
