"""
Hub Automacao Pro - Bot Multi-Cliente
Webhook unico que atende todas as instancias WhatsApp.
"""
import json
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

# Fila de mensagens pendentes por LID nao resolvido
_pending_lid = {}


def get_phone_from_message(data):
    """Extrai telefone do payload da Evolution API v2."""
    remote_jid = data.get('key', {}).get('remoteJid', '')

    if '@s.whatsapp.net' in remote_jid:
        return remote_jid.split('@')[0]

    if '@lid' in remote_jid:
        participant = data.get('key', {}).get('participant', '')
        if participant and '@s.whatsapp.net' in participant:
            return participant.split('@')[0]
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


def try_resolve_lid_from_sent(instance_name, lid_jid):
    """Tenta resolver LID checando mensagens enviadas (fromMe) que contém o JID real."""
    try:
        # Quando o bot envia uma mensagem manual para um numero real,
        # a Evolution API cria um contato @s.whatsapp.net.
        # Na proxima vez que o LID mandar mensagem, a resolucao via contacts funciona.
        # Aqui tentamos forcar a atualizacao dos contatos.
        r = evolution.fetch_all_contacts(instance_name)
        if not r:
            return None

        # Procura por contato com mesmo profilePicUrl ou pushName
        lid_contact = None
        for c in r:
            if c.get('remoteJid') == lid_jid:
                lid_contact = c
                break

        if not lid_contact:
            return None

        pic = lid_contact.get('profilePicUrl')
        pn = lid_contact.get('pushName', '')

        if pic:
            for c in r:
                rjid = c.get('remoteJid', '')
                if rjid.endswith('@s.whatsapp.net') and c.get('profilePicUrl') == pic:
                    return rjid.split('@')[0]

        if pn:
            matches = [c for c in r if c.get('remoteJid', '').endswith('@s.whatsapp.net') and c.get('pushName') == pn]
            if len(matches) == 1:
                return matches[0]['remoteJid'].split('@')[0]

        return None
    except Exception:
        return None


def process_message(payload):
    """Processa mensagem em background thread."""
    try:
        event = payload.get('event', '')
        if event != 'messages.upsert':
            return

        instance_name = payload.get('instance', '')
        data = payload.get('data', {})

        if data.get('key', {}).get('fromMe', False):
            # Quando o bot envia uma mensagem (manual ou automatica),
            # captura o mapeamento LID <-> phone se possivel
            _learn_from_sent(instance_name, data)
            return

        text = get_text_from_message(data)
        if not text:
            return

        phone = get_phone_from_message(data)
        if not phone:
            return

        # Resolver LID para numero real
        send_phone = phone
        is_lid = '@lid' in phone
        if is_lid:
            resolved = evolution.resolve_lid_to_phone(instance_name, phone)
            if resolved:
                send_phone = resolved
            else:
                log.warning(f'[{instance_name}] LID nao resolvido: {phone} - salvando payload')
                # Salvar LID pendente para resolucao futura
                db.save_unresolved_lid(
                    phone, instance_name,
                    data.get('pushName', ''),
                    json.dumps(data.get('key', {}))
                )

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
            if msg_fora and not is_lid:
                evolution.send_message(instance_name, send_phone, msg_fora)
            return

        # Ativar "digitando..." imediatamente
        can_send = send_phone != phone or not is_lid
        if can_send:
            evolution.set_typing(instance_name, send_phone, True)

        db_phone = send_phone

        # Carregar historico
        max_history = empresa.get('max_history_messages', 10)
        history = db.get_conversation_history(empresa_id, db_phone, max_history)

        # Salvar mensagem do usuario
        db.save_message(empresa_id, db_phone, 'user', text, push_name)
        history.append({'role': 'user', 'content': text})

        # Montar system prompt com contexto do contato
        base_prompt = empresa.get('system_prompt', '')
        contact_info = db.get_contact_info(empresa_id, db_phone)

        if contact_info and contact_info['total_msgs'] > 1:
            nome = contact_info.get('push_name') or push_name or ''
            total = contact_info['total_msgs']
            ctx = (
                f'\n\nCONTEXTO: Falando com {nome}. Ja trocaram {total} msgs. '
                f'NAO se apresente de novo. Continue a conversa naturalmente. '
                f'Chame pelo nome. Seja proativo, sugira, pergunte.'
            )
        else:
            nome = push_name or ''
            ctx = (
                f'\n\nCONTEXTO: Primeiro contato{" com " + nome if nome else ""}. '
                f'Se apresente: Oliver, quantrexnow.io. '
                f'Pergunte o ramo do negocio e como pode ajudar. So nesta primeira vez.'
            )

        # Chamar Claude (digitando continua aparecendo enquanto processa)
        result = claude_client.call_claude(
            system_prompt=base_prompt + ctx,
            messages=history,
            model=empresa.get('model', 'claude-opus-4-5-20251101'),
            max_tokens=empresa.get('max_tokens', 200)
        )

        response_text = result['text']

        # Delay proporcional ao tamanho da resposta (simula digitacao real)
        # Pessoa real digita ~40 chars/seg no WhatsApp
        if can_send:
            typing_secs = max(2.0, min(len(response_text) / 40.0, 8.0))
            # Reenviar "digitando" pra manter o indicador ativo
            evolution.set_typing(instance_name, send_phone, True)
            time.sleep(typing_secs)

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


def _learn_from_sent(instance_name, data):
    """Aprende mapeamento LID->phone quando uma mensagem e enviada."""
    try:
        remote_jid = data.get('key', {}).get('remoteJid', '')
        if '@s.whatsapp.net' not in remote_jid:
            return
        phone = remote_jid.split('@')[0]
        push_name = data.get('pushName', '')

        # Tenta encontrar LID correspondente nos contatos
        contacts = evolution.fetch_all_contacts(instance_name)
        if not contacts:
            return

        # Encontra o contato @s.whatsapp.net
        sent_contact = None
        for c in contacts:
            if c.get('remoteJid') == remote_jid:
                sent_contact = c
                break

        if not sent_contact:
            return

        pic = sent_contact.get('profilePicUrl')
        if not pic:
            return

        # Encontra LID com mesma foto
        for c in contacts:
            rjid = c.get('remoteJid', '')
            if '@lid' in rjid and c.get('profilePicUrl') == pic:
                db.save_lid_phone(rjid, phone, instance_name, push_name or c.get('pushName', ''))
                evolution._lid_cache[rjid] = phone
                log.info(f'Aprendeu mapeamento: {rjid} -> {phone}')
                break
    except Exception:
        pass


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


@app.route('/api/unresolved-lids', methods=['GET'])
def unresolved_lids():
    """Lista LIDs nao resolvidos para mapeamento manual."""
    lids = db.get_unresolved_lids()
    return jsonify(lids), 200


if __name__ == '__main__':
    log.info('Hub Bot multi-cliente iniciando...')
    db.init_pool()
    log.info('Pool PostgreSQL conectado')
    app.run(host='0.0.0.0', port=3000)
