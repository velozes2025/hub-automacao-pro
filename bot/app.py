"""
Hub Automacao Pro - Bot Multi-Cliente
Webhook unico que atende todas as instancias WhatsApp.
Resolucao automatica de LID com 7 estrategias + fila de pendentes.
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


# ============================================================
# CONTACTS EVENT HANDLER - Auto-learn LID-to-phone mappings
# ============================================================

def process_contacts_event(payload):
    """Handle contacts.upsert/update events to learn LID-phone mappings."""
    try:
        instance_name = payload.get('instance', '')
        data = payload.get('data', {})

        contacts = data if isinstance(data, list) else [data]

        for contact in contacts:
            if not isinstance(contact, dict):
                continue

            contact_id = contact.get('id', '') or contact.get('remoteJid', '')
            lid = contact.get('lid', '')
            push_name = (
                contact.get('name')
                or contact.get('notify', '')
                or contact.get('pushName', '')
            )

            # Direct mapping if both phone JID and LID are present
            if (contact_id and '@s.whatsapp.net' in contact_id
                    and lid and '@lid' in lid):
                phone = contact_id.split('@')[0]
                db.save_lid_phone(lid, phone, instance_name, push_name)
                evolution._lid_cache[lid] = phone
                db.mark_lid_resolved(lid, instance_name)
                log.info(f'[CONTACTS EVENT] Mapeamento direto: {lid} -> {phone}')

                # Deliver pending responses
                _deliver_pending_responses(instance_name, lid, phone)

    except Exception as e:
        log.error(f'Erro processando contacts event: {e}', exc_info=True)


# ============================================================
# PENDING RESPONSE DELIVERY
# ============================================================

PENDING_MAX_AGE_SECONDS = 600  # 10 minutos


def _deliver_pending_responses(instance_name, lid_jid, phone):
    """Deliver pending responses with consolidation and time-window rules.

    - Se pendentes > 10 min: manda msg unica de retomada.
    - Se pendentes <= 10 min e multiplas: condensa em 1-2 msgs.
    - Se pendente unica <= 10 min: manda normal.
    """
    try:
        pending = db.get_pending_responses(lid_jid, instance_name)
        if not pending:
            return

        all_ids = [p['id'] for p in pending]
        oldest_age = max(float(p.get('age_seconds', 0)) for p in pending)
        push_name = pending[0].get('push_name', '') or ''
        nome = push_name.split()[0] if push_name else ''

        if oldest_age > PENDING_MAX_AGE_SECONDS:
            # Mensagens antigas: manda retomada em vez do conteudo original
            if nome:
                msg = f'Oi {nome}! Tive um atraso tecnico aqui, desculpa. Ja estou de volta, como posso te ajudar?'
            else:
                msg = 'Oi! Desculpa a demora, tive um problema tecnico. Ja to de volta, no que posso ajudar?'

            evolution.set_typing(instance_name, phone, True)
            time.sleep(2.5)
            sent = evolution.send_message(instance_name, phone, msg)
            evolution.set_typing(instance_name, phone, False)

            if sent:
                log.info(f'[PENDING] Retomada enviada para {phone} ({len(pending)} msgs antigas descartadas)')
            db.mark_responses_delivered(all_ids)
            return

        # Mensagens recentes (< 10 min)
        if len(pending) == 1:
            # Uma unica pendente: envia normal
            evolution.set_typing(instance_name, phone, True)
            time.sleep(2.0)
            evolution.send_message(instance_name, phone, pending[0]['response_text'])
            evolution.set_typing(instance_name, phone, False)
            log.info(f'[PENDING] Entregue 1 resposta pendente para {phone}')
            db.mark_responses_delivered(all_ids)
            return

        # Multiplas pendentes recentes: condensar em 1-2 mensagens
        texts = [p['response_text'] for p in pending]
        if len(texts) <= 2:
            # 2 pendentes: manda as duas com intervalo
            for t in texts:
                evolution.set_typing(instance_name, phone, True)
                time.sleep(2.0)
                evolution.send_message(instance_name, phone, t)
                evolution.set_typing(instance_name, phone, False)
        else:
            # 3+ pendentes: condensar tudo em uma unica mensagem resumo
            combined = '\n'.join(texts)
            # Se o resumo ficar muito grande, pega so a ultima resposta
            if len(combined) > 500:
                final_msg = texts[-1]
            else:
                final_msg = combined

            evolution.set_typing(instance_name, phone, True)
            time.sleep(3.0)
            evolution.send_message(instance_name, phone, final_msg)
            evolution.set_typing(instance_name, phone, False)

        log.info(f'[PENDING] Consolidou {len(pending)} respostas para {phone}')
        db.mark_responses_delivered(all_ids)

    except Exception as e:
        log.error(f'Erro entregando respostas pendentes: {e}')


# ============================================================
# BACKGROUND LID RESOLVER
# ============================================================

def _background_lid_resolver():
    """Background thread that periodically retries resolving unresolved LIDs."""
    while True:
        try:
            time.sleep(30)
            unresolved = db.get_unresolved_lids()
            for entry in unresolved:
                lid = entry['lid']
                inst = entry['instance_name']
                phone = evolution.resolve_lid_to_phone(inst, lid)
                if phone:
                    log.info(f'[BG-RESOLVER] Resolveu {lid} -> {phone}')
                    _deliver_pending_responses(inst, lid, phone)
        except Exception as e:
            log.error(f'[BG-RESOLVER] Erro: {e}')


# ============================================================
# MESSAGE PROCESSING
# ============================================================

def _learn_from_sent(instance_name, data):
    """Aprende mapeamento LID->phone quando uma mensagem e enviada."""
    try:
        remote_jid = data.get('key', {}).get('remoteJid', '')
        if '@s.whatsapp.net' not in remote_jid:
            return
        phone = remote_jid.split('@')[0]
        push_name = data.get('pushName', '')

        contacts = evolution.fetch_all_contacts(instance_name)
        if not contacts:
            return

        sent_contact = None
        for c in contacts:
            if c.get('remoteJid') == remote_jid:
                sent_contact = c
                break

        if not sent_contact:
            return

        pic = sent_contact.get('profilePicUrl')
        pn = sent_contact.get('pushName', '') or push_name

        # Match by profilePicUrl (base path comparison)
        if pic:
            for c in contacts:
                rjid = c.get('remoteJid', '')
                if '@lid' in rjid and evolution._same_profile_pic(c.get('profilePicUrl'), pic):
                    db.save_lid_phone(rjid, phone, instance_name, pn or c.get('pushName', ''))
                    evolution._lid_cache[rjid] = phone
                    db.mark_lid_resolved(rjid, instance_name)
                    log.info(f'Aprendeu mapeamento via envio: {rjid} -> {phone}')
                    _deliver_pending_responses(instance_name, rjid, phone)
                    break

        # Match by pushName
        if pn:
            lid_candidates = [
                c for c in contacts
                if '@lid' in c.get('remoteJid', '')
                and c.get('pushName') == pn
            ]
            if len(lid_candidates) == 1:
                rjid = lid_candidates[0]['remoteJid']
                if rjid not in evolution._lid_cache:
                    db.save_lid_phone(rjid, phone, instance_name, pn)
                    evolution._lid_cache[rjid] = phone
                    db.mark_lid_resolved(rjid, instance_name)
                    log.info(f'Aprendeu mapeamento via pushName envio: {rjid} -> {phone}')
                    _deliver_pending_responses(instance_name, rjid, phone)

    except Exception:
        pass


def process_message(payload):
    """Processa mensagem em background thread."""
    try:
        event = payload.get('event', '')

        # Route contacts events
        if event in ('contacts.upsert', 'contacts.update'):
            process_contacts_event(payload)
            return

        if event != 'messages.upsert':
            return

        instance_name = payload.get('instance', '')
        data = payload.get('data', {})

        if data.get('key', {}).get('fromMe', False):
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
        lid_unresolved = False

        if is_lid:
            resolved = evolution.resolve_lid_to_phone(instance_name, phone)
            if resolved:
                send_phone = resolved
            else:
                lid_unresolved = True
                log.warning(f'[{instance_name}] LID nao resolvido: {phone} - processando como pendente')
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
            if msg_fora and not lid_unresolved:
                evolution.send_message(instance_name, send_phone, msg_fora)
            return

        # Ativar "digitando..." imediatamente (se temos o telefone real)
        can_send = not lid_unresolved
        if can_send:
            evolution.set_typing(instance_name, send_phone, True)

        db_phone = send_phone if not lid_unresolved else phone

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

        # Chamar Claude
        result = claude_client.call_claude(
            system_prompt=base_prompt + ctx,
            messages=history,
            model=empresa.get('model', 'claude-opus-4-5-20251101'),
            max_tokens=empresa.get('max_tokens', 200)
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

        if lid_unresolved:
            # LID nao resolvido: salvar resposta como pendente
            db.save_pending_response(phone, instance_name, response_text, push_name)
            log.info(f'[{instance_name}] Resposta PENDENTE para LID {phone}: "{response_text[:40]}"')

            # Tentar resolver uma ultima vez (contacts podem ter atualizado)
            time.sleep(2)
            resolved_late = evolution.resolve_lid_to_phone(instance_name, phone)
            if resolved_late:
                log.info(f'[{instance_name}] LID resolvido tardiamente: {phone} -> {resolved_late}')
                _deliver_pending_responses(instance_name, phone, resolved_late)
            return

        # Delay proporcional ao tamanho da resposta (simula digitacao real)
        typing_secs = max(2.0, min(len(response_text) / 40.0, 8.0))
        evolution.set_typing(instance_name, send_phone, True)
        time.sleep(typing_secs)

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


@app.route('/api/unresolved-lids', methods=['GET'])
def unresolved_lids():
    """Lista LIDs nao resolvidos para mapeamento manual."""
    lids = db.get_unresolved_lids()
    return jsonify(lids), 200


if __name__ == '__main__':
    log.info('Hub Bot multi-cliente iniciando...')
    db.init_pool()
    db.ensure_pending_table()
    log.info('Pool PostgreSQL conectado')

    # Iniciar background resolver
    resolver_thread = threading.Thread(target=_background_lid_resolver, daemon=True)
    resolver_thread.start()
    log.info('Background LID resolver iniciado')

    app.run(host='0.0.0.0', port=3000)
