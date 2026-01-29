"""
Hub Automacao Pro - Bot Multi-Cliente
Webhook unico que atende todas as instancias WhatsApp.
- Resolucao automatica de LID com 7 estrategias + fila de pendentes
- Auto-save de todo lead novo no banco
- Deteccao de idioma automatica
- Garantia de resposta: nenhum cliente fica sem resposta
"""
import json
import re
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

PENDING_MAX_AGE_SECONDS = 600  # 10 minutos
RETRY_MAX_ATTEMPTS = 5
RETRY_INTERVAL_SECONDS = 30
REENGAGE_CHECK_MINUTES = 25
REENGAGE_INTERVAL_SECONDS = 300  # 5 minutos entre checks
MSG_SPLIT_MAX_CHARS = 200


# ============================================================
# UTILS
# ============================================================

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


def is_real_name(name):
    """Detecta se o pushName parece um nome real de pessoa."""
    if not name or len(name.strip()) < 2:
        return False
    n = name.strip().lower()
    # Palavras que indicam que NAO e nome de pessoa
    fake_names = {
        'automation', 'bot', 'business', 'company', 'enterprise', 'admin',
        'test', 'teste', 'user', 'usuario', 'client', 'cliente', 'support',
        'suporte', 'info', 'contact', 'contato', 'shop', 'store', 'loja',
        'marketing', 'sales', 'vendas', 'service', 'servico', 'official',
        'oficial', 'news', 'tech', 'digital', 'group', 'grupo', 'team',
        'equipe', 'manager', 'gerente', 'assistant', 'assistente', 'help',
        'ajuda', 'welcome', 'delivery', 'app', 'web', 'dev', 'api',
    }
    # Se e exatamente uma palavra fake
    if n in fake_names:
        return False
    # Se contem apenas emojis/simbolos (sem letras)
    if not re.search(r'[a-zA-ZÀ-ÿ]', name):
        return False
    # Se e so 1 caractere
    if len(name.strip()) == 1:
        return False
    # Se parece nome de empresa (palavras comuns de empresa)
    biz_patterns = r'\b(llc|ltd|inc|corp|sa|ltda|eireli|mei|co\.)\b'
    if re.search(biz_patterns, n):
        return False
    return True


def detect_language(text):
    """Detecta idioma do texto por heuristica simples."""
    t = text.lower()
    # Ingles
    en_words = r'\b(hi|hello|hey|how|what|where|when|why|can|could|would|should|the|is|are|do|does|have|has|yes|no|please|thanks|thank|you|your|need|help|want|looking|business|company)\b'
    en_count = len(re.findall(en_words, t))
    # Espanhol
    es_words = r'\b(hola|como|estas|donde|cuando|porque|puedo|quiero|necesito|gracias|bueno|bien|empresa|negocio|ayuda|por favor|tengo|tiene|hacer|estoy)\b'
    es_count = len(re.findall(es_words, t))
    # Portugues
    pt_words = r'\b(oi|ola|tudo|bem|como|voce|onde|quando|porque|preciso|quero|obrigado|bom|empresa|ajuda|por favor|tenho|tem|fazer|estou|nao|sim)\b'
    pt_count = len(re.findall(pt_words, t))

    scores = {'en': en_count, 'es': es_count, 'pt': pt_count}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else 'pt'


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
# MESSAGE SPLITTING - Simula humano no WhatsApp
# ============================================================

def split_message(text, max_chars=MSG_SPLIT_MAX_CHARS):
    """Divide texto longo em chunks curtos, quebrando em limites de frase.

    Retorna lista de strings. Mensagens curtas voltam como lista de 1 item.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    # Quebrar em sentencas (ponto, exclamacao, interrogacao seguidos de espaco)
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current = ''

    for sentence in sentences:
        if not sentence:
            continue
        # Se a sentenca sozinha ja estoura, corta no espaco mais proximo
        if len(sentence) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ''
            words = sentence.split()
            buf = ''
            for w in words:
                if buf and len(buf) + 1 + len(w) > max_chars:
                    chunks.append(buf.strip())
                    buf = w
                else:
                    buf = f'{buf} {w}'.strip()
            if buf:
                current = buf
            continue

        if current and len(current) + 1 + len(sentence) > max_chars:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f'{current} {sentence}'.strip()

    if current:
        chunks.append(current.strip())

    return chunks if chunks else [text]


def send_with_retry(instance_name, phone, text, empresa_id='', push_name=''):
    """Envia mensagem via Evolution API. Se falhar, salva na fila de retry.

    Retorna True se enviou com sucesso, False se foi pra fila.
    """
    sent = evolution.send_message(instance_name, phone, text)
    if sent:
        return True

    # Falhou: salvar na fila de retry
    try:
        db.save_failed_response(instance_name, phone, text, empresa_id, push_name)
        log.warning(f'[RETRY-QUEUE] Resposta salva para retry: {instance_name} -> {phone}')
    except Exception as e:
        log.error(f'[RETRY-QUEUE] CRITICO - falha ao salvar na fila: {e}')
    return False


def send_split_messages(instance_name, phone, text, empresa_id='', push_name=''):
    """Envia mensagem dividida em chunks com typing entre cada um.

    Se algum chunk falhar, salva o restante na fila de retry.
    """
    chunks = split_message(text)

    if len(chunks) == 1:
        # Mensagem curta: envio normal com typing
        typing_secs = max(2.0, min(len(text) / 40.0, 8.0))
        evolution.set_typing(instance_name, phone, True)
        time.sleep(typing_secs)
        evolution.set_typing(instance_name, phone, False)
        return send_with_retry(instance_name, phone, text, empresa_id, push_name)

    # Multiplos chunks: enviar com typing entre cada
    all_sent = True
    for i, chunk in enumerate(chunks):
        typing_secs = max(1.5, min(len(chunk) / 40.0, 5.0))
        evolution.set_typing(instance_name, phone, True)
        time.sleep(typing_secs)
        evolution.set_typing(instance_name, phone, False)

        sent = send_with_retry(instance_name, phone, chunk, empresa_id, push_name)
        if not sent:
            # Falhou: salvar chunks restantes como uma mensagem na fila
            remaining = ' '.join(chunks[i + 1:])
            if remaining:
                try:
                    db.save_failed_response(instance_name, phone, remaining, empresa_id, push_name)
                except Exception:
                    pass
            all_sent = False
            break

        # Pausa entre chunks (simula humano pensando)
        if i < len(chunks) - 1:
            time.sleep(1.0)

    return all_sent


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

                _deliver_pending_responses(instance_name, lid, phone)

    except Exception as e:
        log.error(f'Erro processando contacts event: {e}', exc_info=True)


# ============================================================
# PENDING RESPONSE DELIVERY (max 2 msgs, consolidacao, janela)
# ============================================================

def _deliver_pending_responses(instance_name, lid_jid, phone):
    """Deliver pending responses with consolidation and time-window rules.

    - Pendentes > 10 min: 1 msg de retomada (descarta conteudo antigo).
    - Pendentes <= 10 min, 1 msg: envia normal.
    - Pendentes <= 10 min, 2+ msgs: max 2 msgs (atraso + continuacao).
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
            # Mensagens antigas (>10 min): msg unica de retomada
            if nome:
                msg = f'Oi {nome}! Tive um atraso tecnico aqui, desculpa. Ja estou de volta, como posso te ajudar?'
            else:
                msg = 'Oi! Desculpa a demora, tive um problema tecnico. Ja to de volta, no que posso ajudar?'

            evolution.set_typing(instance_name, phone, True)
            time.sleep(2.5)
            evolution.send_message(instance_name, phone, msg)
            evolution.set_typing(instance_name, phone, False)

            log.info(f'[PENDING] Retomada enviada para {phone} ({len(pending)} msgs antigas descartadas)')
            db.mark_responses_delivered(all_ids)
            return

        # Mensagens recentes (<= 10 min)
        if len(pending) == 1:
            evolution.set_typing(instance_name, phone, True)
            time.sleep(2.0)
            evolution.send_message(instance_name, phone, pending[0]['response_text'])
            evolution.set_typing(instance_name, phone, False)
            log.info(f'[PENDING] Entregue 1 resposta para {phone}')
        else:
            # 2+ pendentes: max 2 msgs (explicacao + ultima resposta)
            evolution.set_typing(instance_name, phone, True)
            time.sleep(2.0)
            if nome:
                evolution.send_message(instance_name, phone,
                    f'{nome}, desculpa o atraso tecnico! Ja normalizou.')
            else:
                evolution.send_message(instance_name, phone,
                    'Desculpa o atraso tecnico! Ja normalizou.')
            evolution.set_typing(instance_name, phone, False)

            time.sleep(1.5)
            evolution.set_typing(instance_name, phone, True)
            time.sleep(2.0)
            evolution.send_message(instance_name, phone, pending[-1]['response_text'])
            evolution.set_typing(instance_name, phone, False)
            log.info(f'[PENDING] Consolidou {len(pending)} respostas em 2 msgs para {phone}')

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
    """Processa mensagem em background thread.

    REGRA: Nenhum cliente fica sem resposta. Nenhum lead novo deixa de ser salvo.
    """
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

        push_name = data.get('pushName', '')
        lang = detect_language(text)

        # --- Resolver LID ---
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
                    push_name,
                    json.dumps(data.get('key', {}))
                )

        # --- Buscar empresa ---
        empresa = db.get_empresa_by_instance(instance_name)
        if not empresa:
            log.warning(f'Instancia desconhecida ou inativa: {instance_name}')
            return

        empresa_id = str(empresa['id'])
        db_phone = send_phone if not lid_unresolved else phone

        # ==========================================================
        # LEAD AUTO-SAVE: todo contato novo vai pro banco SEMPRE
        # ==========================================================
        try:
            db.upsert_lead(
                empresa_id=empresa_id,
                phone=db_phone,
                push_name=push_name,
                lid=phone if is_lid else '',
                origin='whatsapp',
                first_message=text[:500],
                detected_language=lang,
                instance_name=instance_name
            )
        except Exception as e:
            # Erro no banco NAO impede resposta
            log.error(f'Erro ao salvar lead: {e}')

        # --- Horario de atendimento ---
        if not is_within_business_hours(empresa):
            msg_fora = empresa.get('outside_hours_message')
            if msg_fora:
                if lid_unresolved:
                    db.save_pending_response(phone, instance_name, msg_fora, push_name)
                else:
                    evolution.send_message(instance_name, send_phone, msg_fora)
            return

        # --- Digitando (indica que esta processando) ---
        can_send = not lid_unresolved
        if can_send:
            evolution.set_typing(instance_name, send_phone, True)

        # --- Historico ---
        max_history = empresa.get('max_history_messages', 10)
        history = db.get_conversation_history(empresa_id, db_phone, max_history)

        # Salvar mensagem do usuario
        db.save_message(empresa_id, db_phone, 'user', text, push_name)
        history.append({'role': 'user', 'content': text})

        # Atualizar status do lead e tracking de interacao
        try:
            db.update_lead_status(empresa_id, db_phone, 'em_andamento')
            db.update_last_client_msg(empresa_id, db_phone)
            db.reset_reengagement(empresa_id, db_phone)
        except Exception:
            pass

        # --- System prompt + contexto ---
        base_prompt = empresa.get('system_prompt', '')
        contact_info = db.get_contact_info(empresa_id, db_phone)

        raw_name = (contact_info.get('push_name') if contact_info else None) or push_name or ''
        nome = raw_name if is_real_name(raw_name) else ''
        nome_instrucao = ''
        if not nome:
            nome_instrucao = (
                'IMPORTANTE: Voce NAO sabe o nome dessa pessoa. '
                'Pergunte o nome dela de forma natural antes de continuar. '
                'NAO invente nenhum nome, NAO use apelidos do perfil como nome. '
            )

        if contact_info and contact_info['total_msgs'] > 1:
            total = contact_info['total_msgs']
            ctx = (
                f'\n\nCONTEXTO: Ja trocaram {total} msgs. '
                f'Idioma detectado: {lang}. '
                f'{f"Nome do cliente: {nome}. Chame pelo nome. " if nome else nome_instrucao}'
                f'NAO se apresente de novo. Continue a conversa naturalmente. '
                f'Seja proativo, sugira, pergunte.'
            )
        else:
            ctx = (
                f'\n\nCONTEXTO: Primeiro contato. '
                f'Idioma detectado: {lang}. RESPONDA NESSE IDIOMA. '
                f'{f"Nome do cliente: {nome}. " if nome else nome_instrucao}'
                f'Se apresente: Oliver, quantrexnow.io. '
                f'Pergunte o ramo do negocio e como pode ajudar. So nesta primeira vez.'
            )

        # --- Chamar Claude ---
        result = claude_client.call_claude(
            system_prompt=base_prompt + ctx,
            messages=history,
            model=empresa.get('model', 'claude-opus-4-5-20251101'),
            max_tokens=empresa.get('max_tokens', 120)
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

        # --- ENVIO (com garantia de entrega) ---
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

        # Enviar com split de mensagens + retry automatico
        sent = send_split_messages(instance_name, send_phone, response_text, empresa_id, push_name)

        if sent:
            log.info(f'[{instance_name}] {send_phone}: "{text[:40]}" -> "{response_text[:40]}"')
            try:
                db.update_last_bot_msg(empresa_id, db_phone)
            except Exception:
                pass
        else:
            log.warning(f'[{instance_name}] Envio falhou, salvo na fila de retry: {send_phone}')

    except Exception as e:
        log.error(f'Erro ao processar mensagem: {e}', exc_info=True)
        # GARANTIA: se temos dados suficientes, salvar resposta na fila
        _locals = locals()
        try:
            _resp = _locals.get('response_text', '')
            _phone = _locals.get('send_phone', '')
            _inst = _locals.get('instance_name', '')
            if _resp and _phone and _inst:
                db.save_failed_response(
                    _inst, _phone, _resp,
                    _locals.get('empresa_id', ''),
                    _locals.get('push_name', '')
                )
                log.info(f'[GARANTIA] Resposta salva na fila apos excecao')
        except Exception:
            log.error(f'[GARANTIA] CRITICO - nao conseguiu salvar na fila de retry')


# ============================================================
# BACKGROUND: RETRY PROCESSOR (respostas falhadas)
# ============================================================

def _background_retry_processor():
    """Thread que reenvia respostas falhadas a cada 30s.

    Max 5 tentativas por resposta. Apos isso, loga como perdida.
    """
    while True:
        try:
            time.sleep(RETRY_INTERVAL_SECONDS)
            pending = db.get_pending_retries(max_attempts=RETRY_MAX_ATTEMPTS)
            if not pending:
                continue

            log.info(f'[RETRY] Processando {len(pending)} respostas falhadas')

            for entry in pending:
                fid = entry['id']
                inst = entry['instance_name']
                phone = entry['phone']
                text = entry['response_text']

                sent = evolution.send_message(inst, phone, text)
                if sent:
                    db.mark_failed_delivered(fid)
                    log.info(f'[RETRY] Entregue com sucesso: {inst} -> {phone} (tentativa {entry["attempts"] + 1})')
                    # Atualizar last_bot_msg
                    try:
                        if entry.get('empresa_id'):
                            db.update_last_bot_msg(entry['empresa_id'], phone)
                    except Exception:
                        pass
                else:
                    db.increment_retry(fid)
                    attempts = entry['attempts'] + 1
                    if attempts >= RETRY_MAX_ATTEMPTS:
                        log.error(f'[RETRY] DESISTIU apos {RETRY_MAX_ATTEMPTS} tentativas: {inst} -> {phone}')
                    else:
                        log.warning(f'[RETRY] Falhou novamente ({attempts}/{RETRY_MAX_ATTEMPTS}): {inst} -> {phone}')

        except Exception as e:
            log.error(f'[RETRY] Erro no processador: {e}', exc_info=True)


# ============================================================
# BACKGROUND: REENGAGEMENT (clientes sem resposta / inativos)
# ============================================================

REENGAGE_MESSAGES_PT = [
    'Oi{nome}! Fiquei pensando sobre o que conversamos. Se tiver alguma duvida, to por aqui.',
    'E ai{nome}, tudo certo? Fico a disposicao se precisar de algo.',
    '{nome_ou_oi}, se quiser continuar de onde paramos, e so me chamar.',
]

REENGAGE_MESSAGES_EN = [
    'Hey{nome}! Just checking in. Let me know if you have any questions.',
    'Hi{nome}, still here if you need anything!',
    '{nome_ou_oi}, feel free to reach out whenever you are ready.',
]

REENGAGE_MESSAGES_ES = [
    'Hola{nome}! Quedo a tu disposicion si tienes alguna duda.',
    '{nome_ou_oi}, si necesitas algo, aqui estoy.',
    'Hola{nome}, seguimos cuando quieras!',
]

_reengage_idx = 0


def _get_reengage_msg(push_name='', lang='pt'):
    """Retorna mensagem de reengajamento variada."""
    global _reengage_idx

    nome = ''
    nome_ou_oi = 'Oi'
    if push_name and is_real_name(push_name):
        first = push_name.strip().split()[0]
        nome = f' {first}'
        nome_ou_oi = first

    if lang == 'en':
        msgs = REENGAGE_MESSAGES_EN
        if not nome:
            nome_ou_oi = 'Hey'
    elif lang == 'es':
        msgs = REENGAGE_MESSAGES_ES
        if not nome:
            nome_ou_oi = 'Hola'
    else:
        msgs = REENGAGE_MESSAGES_PT

    msg = msgs[_reengage_idx % len(msgs)]
    _reengage_idx += 1

    return msg.format(nome=nome, nome_ou_oi=nome_ou_oi)


def _background_reengagement():
    """Thread que detecta clientes inativos e envia msg de reengajamento.

    Roda a cada 5 minutos. Max 2 reengajamentos por lead.
    """
    while True:
        try:
            time.sleep(REENGAGE_INTERVAL_SECONDS)
            stale = db.get_stale_conversations(minutes=REENGAGE_CHECK_MINUTES)
            if not stale:
                continue

            log.info(f'[REENGAGE] Encontrou {len(stale)} conversas inativas')

            for lead in stale:
                empresa_id = lead['empresa_id']
                phone = lead['phone']
                inst = lead['instance_name']
                push_name = lead.get('push_name', '')
                lang = 'pt'

                # Detectar idioma da ultima conversa
                try:
                    history = db.get_conversation_history(empresa_id, phone, 3)
                    if history:
                        last_user = [h for h in history if h['role'] == 'user']
                        if last_user:
                            lang = detect_language(last_user[-1]['content'])
                except Exception:
                    pass

                msg = _get_reengage_msg(push_name, lang)

                # Typing + envio
                evolution.set_typing(inst, phone, True)
                time.sleep(2.5)
                evolution.set_typing(inst, phone, False)
                sent = evolution.send_message(inst, phone, msg)

                if sent:
                    db.increment_reengagement(empresa_id, phone)
                    # Salvar no historico
                    try:
                        db.save_message(empresa_id, phone, 'assistant', msg)
                        db.update_last_bot_msg(empresa_id, phone)
                    except Exception:
                        pass
                    log.info(f'[REENGAGE] Enviado para {phone} ({inst}): "{msg[:50]}"')
                else:
                    log.warning(f'[REENGAGE] Falha envio para {phone} ({inst})')

                # Pausa entre envios para nao sobrecarregar
                time.sleep(3)

        except Exception as e:
            log.error(f'[REENGAGE] Erro: {e}', exc_info=True)


# ============================================================
# ROUTES
# ============================================================

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


@app.route('/api/leads', methods=['GET'])
def list_leads():
    """Lista todos os leads salvos."""
    rows = db._query(
        """SELECT id, empresa_id, phone, push_name, origin, first_message,
                  detected_language, status, instance_name, created_at, updated_at
           FROM leads ORDER BY created_at DESC LIMIT 100"""
    )
    return jsonify([dict(r) for r in rows] if rows else []), 200


# ============================================================
# STARTUP
# ============================================================

if __name__ == '__main__':
    log.info('Hub Bot multi-cliente iniciando...')
    db.init_pool()
    db.ensure_tables()
    log.info('Pool PostgreSQL conectado + tabelas verificadas')

    # Iniciar background resolver
    resolver_thread = threading.Thread(target=_background_lid_resolver, daemon=True)
    resolver_thread.start()
    log.info('Background LID resolver iniciado')

    # Iniciar retry processor (respostas falhadas)
    retry_thread = threading.Thread(target=_background_retry_processor, daemon=True)
    retry_thread.start()
    log.info('Background retry processor iniciado')

    # Iniciar reengagement (clientes inativos)
    reengage_thread = threading.Thread(target=_background_reengagement, daemon=True)
    reengage_thread.start()
    log.info('Background reengagement iniciado')

    app.run(host='0.0.0.0', port=3000)
