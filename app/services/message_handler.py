"""Main message processing pipeline.

Webhook -> parse -> resolve tenant -> resolve LID -> get/create conversation
-> detect language -> AI supervisor -> send response.

RULE: No client goes without a response. No new lead is lost.
"""

import json
import time
import logging
import threading

from app.config import config
from app.db import tenants as tenants_db
from app.db import conversations as conv_db
from app.db import leads as leads_db
from app.db import queue as queue_db
from app.db import consumption as consumption_db
from app.ai import supervisor
from app.ai.oliver_core.engine import process_v60
from app.ai.prompts import detect_language, is_real_name
from app.channels import whatsapp, lid_resolver, sender, transcriber
from app.services import lead_service
from app.services import admin_control

log = logging.getLogger('services.handler')

PENDING_MAX_AGE_SECONDS = 600


# --- Payload parsing ---

def _get_phone(data):
    """Extract phone from Evolution API v2 payload."""
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


def _extract_content(data, instance_name):
    """Extract text from payload. If audio, transcribe it.

    Returns (text, source) where source is 'text', 'audio', 'audio_failed', or 'unsupported'.
    """
    msg = data.get('message', {})

    # Text message
    text = msg.get('conversation') or msg.get('extendedTextMessage', {}).get('text')
    if text:
        return text, 'text'

    # Audio message
    if msg.get('audioMessage'):
        transcription = transcriber.transcribe_audio(instance_name, data)
        if transcription:
            return transcription, 'audio'
        return None, 'audio_failed'

    return None, 'unsupported'


def _is_forwarded(data):
    """Detect if a message is forwarded from WhatsApp contextInfo.

    Evolution API v2 forwards contextInfo inside each message type.
    Returns True if isForwarded is set or forwardingScore >= 1.
    """
    msg = data.get('message', {})

    # Check all possible message types for contextInfo
    for key in ('extendedTextMessage', 'conversation', 'audioMessage',
                'imageMessage', 'videoMessage', 'documentMessage'):
        sub = msg.get(key)
        if isinstance(sub, dict):
            ctx = sub.get('contextInfo', {})
            if ctx.get('isForwarded') or (ctx.get('forwardingScore', 0) >= 1):
                return True

    # Top-level contextInfo (some Evolution API versions)
    ctx_top = msg.get('contextInfo', {})
    if ctx_top.get('isForwarded') or (ctx_top.get('forwardingScore', 0) >= 1):
        return True

    return False


def _is_within_business_hours(account_config):
    """Check if current time is within business hours."""
    from datetime import datetime, timezone
    start = account_config.get('business_hours_start')
    end = account_config.get('business_hours_end')
    if not start or not end:
        return True
    now = datetime.now(timezone.utc).time()
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end


# --- Main processing ---

def handle_webhook(payload):
    """Main entry point for webhook payloads. Runs in thread pool."""
    try:
        event = payload.get('event', '')

        # Route contacts events
        if event in ('contacts.upsert', 'contacts.update'):
            _handle_contacts_event(payload)
            return

        if event != 'messages.upsert':
            return

        instance_name = payload.get('instance', '')
        data = payload.get('data', {})

        # Skip outgoing messages (but learn LID mappings from them)
        if data.get('key', {}).get('fromMe', False):
            # Check for admin slash commands FIRST (retrocompatible)
            if admin_control.is_admin_command(data, instance_name):
                _handle_admin_command(instance_name, data)
                return
            # Check for natural language admin messages (no '/' prefix)
            if admin_control.is_admin_message(data, instance_name):
                _handle_admin_natural(instance_name, data)
                return
            _handle_sent_message(instance_name, data)
            return

        _process_incoming(instance_name, data)

    except Exception as e:
        log.error(f'Webhook handler error: {e}', exc_info=True)
        admin_control.log_admin_error(
            payload.get('instance', ''), f'{type(e).__name__}: {str(e)[:200]}'
        )


def _handle_contacts_event(payload):
    """Process contacts.upsert/update events to learn LID mappings."""
    instance_name = payload.get('instance', '')
    data = payload.get('data', {})

    # Resolve tenant for this instance
    account = tenants_db.get_whatsapp_account_by_instance(instance_name)
    if not account:
        return

    lid_jid, phone = lid_resolver.learn_from_contacts_event(
        account['id'], instance_name, data
    )
    if lid_jid and phone:
        _deliver_pending_lid_responses(account, instance_name, lid_jid, phone)


def _handle_sent_message(instance_name, data):
    """Learn LID mappings from outgoing messages."""
    account = tenants_db.get_whatsapp_account_by_instance(instance_name)
    if not account:
        return
    lid_resolver.learn_from_sent_message(account['id'], instance_name, data)


def _handle_admin_command(instance_name, data):
    """Process an admin command received via WhatsApp."""
    try:
        from app.db.redis_client import get_redis
        r = get_redis()
        if not r:
            log.warning('[ADMIN] Redis unavailable, cannot process admin command')
            return

        account = tenants_db.get_whatsapp_account_by_instance(instance_name)
        if not account:
            return

        msg = data.get('message', {})
        text = (msg.get('conversation')
                or msg.get('extendedTextMessage', {}).get('text', ''))
        if not text:
            return

        log.info(f'[ADMIN] Command: {text[:80]}')

        controller = admin_control.AdminController(instance_name, account, r)
        response = controller.handle_command(text)

        if response:
            # Reply to the chat where the admin typed the command
            remote_jid = data.get('key', {}).get('remoteJid', '')
            reply_phone = remote_jid.split('@')[0] if '@' in remote_jid else ''
            if reply_phone:
                whatsapp.send_message(instance_name, reply_phone, response)
    except Exception as e:
        log.error(f'[ADMIN] Error: {e}', exc_info=True)


def _handle_admin_natural(instance_name, data):
    """Process a natural-language admin message via NLP interpreter.

    Response always goes back to admin's own number (self-chat).
    """
    try:
        from app.db.redis_client import get_redis
        r = get_redis()
        if not r:
            log.warning('[ADMIN NLP] Redis unavailable')
            return

        account = tenants_db.get_whatsapp_account_by_instance(instance_name)
        if not account:
            return

        msg = data.get('message', {})
        text = (msg.get('conversation')
                or msg.get('extendedTextMessage', {}).get('text', ''))
        if not text:
            return

        log.info(f'[ADMIN NLP] Natural message: {text[:80]}')

        controller = admin_control.AdminController(instance_name, account, r)
        response = controller.handle_natural_message(text)

        if response:
            # Always reply to admin's own number (self-chat)
            admin_phone = config.ADMIN_NUMBER
            if admin_phone:
                whatsapp.send_message(instance_name, admin_phone, response)
    except Exception as e:
        log.error(f'[ADMIN NLP] Error: {e}', exc_info=True)


def _process_incoming(instance_name, data):
    """Process an incoming message through the full pipeline."""
    # --- DEDUPLICATION: check if message_id already processed ---
    message_id = data.get('key', {}).get('id', '')
    if message_id:
        from app.db.redis_client import get_redis
        r = get_redis()
        if r:
            dedup_key = f'dedup:{instance_name}:{message_id}'
            if not r.set(dedup_key, '1', nx=True, ex=config.DEDUP_TTL_SECONDS):
                log.debug(f'[DEDUP] Duplicate message ignored: {message_id}')
                return

            # --- CONTACT BLOCK: skip auto-reply if contact is blocked ---
            phone_check = _get_phone(data)
            if phone_check:
                block_key = f'block:{instance_name}:{phone_check}'
                if r.get(block_key):
                    log.info(f'[BLOCK] Contact {phone_check} is blocked, skipping auto-reply')
                    return
        # If Redis unavailable, proceed without dedup (graceful degradation)

    # --- ADMIN: Global pause check ---
    if admin_control.is_globally_paused(instance_name):
        log.info(f'[ADMIN] Bot paused globally, skipping: {instance_name}')
        return

    # Extract content (text or transcribed audio)
    text, source = _extract_content(data, instance_name)
    if not text:
        if source == 'audio_failed':
            log.warning(f'[{instance_name}] Audio transcription failed')
        return

    phone = _get_phone(data)
    if not phone:
        return

    # --- ADMIN: Per-chat pause/takeover check ---
    if admin_control.is_chat_paused(instance_name, phone):
        log.info(f'[ADMIN] Chat paused for {phone}')
        return
    if admin_control.is_chat_taken_over(instance_name, phone):
        log.info(f'[ADMIN] Chat in takeover for {phone}')
        from app.db.redis_client import get_redis as _get_redis_adm
        _r_adm = _get_redis_adm()
        if _r_adm:
            _r_adm.set(f'admin:last_chat:{instance_name}', phone, ex=3600)
        return

    push_name = data.get('pushName', '')
    detected_language = detect_language(text)

    # --- Resolve tenant ---
    account = tenants_db.get_whatsapp_account_by_instance(instance_name)
    if not account:
        log.warning(f'Unknown or inactive instance: {instance_name}')
        return

    tenant_id = str(account['tenant_id'])
    account_id = str(account['id'])

    # --- Billing check (Stripe) ---
    from app.services import stripe_service
    if not stripe_service.check_tenant_billing(tenant_id):
        log.warning(f'[BILLING] Tenant {tenant_id} blocked — billing issue')
        return

    account_config = account.get('config', {})
    if isinstance(account_config, str):
        account_config = json.loads(account_config) if account_config else {}

    # --- Resolve LID ---
    send_phone = phone
    is_lid = '@lid' in phone
    lid_unresolved = False

    if is_lid:
        resolved = lid_resolver.resolve(account_id, instance_name, phone)
        if resolved:
            send_phone = resolved
        else:
            lid_unresolved = True
            log.warning(f'[{instance_name}] LID unresolved: {phone}')

    db_phone = send_phone if not lid_unresolved else phone

    # --- Get or create conversation ---
    contact_name = push_name if is_real_name(push_name) else None
    conversation = conv_db.get_or_create_conversation(
        tenant_id=tenant_id,
        whatsapp_account_id=account_id,
        contact_phone=db_phone,
        contact_name=contact_name,
    )
    conversation_id = str(conversation['id'])

    # --- Persist language (lock on first message — never change after) ---
    stored_lang = conversation.get('language')
    if stored_lang:
        # Language already set: use it (never override, even if client sends
        # a message in another language — prevents accidental language flips)
        language = stored_lang
    else:
        # First message: detect and lock
        language = detected_language
        try:
            conv_db.update_conversation(conversation_id, tenant_id=tenant_id, language=detected_language)
        except Exception:
            pass

    # --- Detect forwarded messages ---
    forwarded = _is_forwarded(data)
    if forwarded:
        log.info(f'[{instance_name}] Forwarded message detected from {db_phone}')

    # --- Save user message ---
    msg_metadata = {'push_name': push_name, 'source': source, 'forwarded': forwarded}
    if source == 'audio':
        audio_meta = transcriber.get_audio_metadata(data)
        msg_metadata.update(audio_meta)
        # Log Whisper transcription cost ($0.006/min)
        duration_sec = audio_meta.get('duration_seconds', 0)
        if duration_sec <= 0:
            duration_sec = 5  # Minimum estimate for short voice notes
        duration_min = duration_sec / 60.0
        whisper_cost = round(duration_min * 0.006, 6)
        try:
            consumption_db.log_usage(
                tenant_id=tenant_id, model='whisper-1',
                input_tokens=0, output_tokens=0, cost=whisper_cost,
                conversation_id=conversation_id, operation='transcription',
                metadata={'duration_seconds': duration_sec},
            )
            log.info(f'[COST] Whisper: {duration_sec}s = ${whisper_cost}')
        except Exception as e:
            log.error(f'[COST] Failed to log Whisper cost: {e}')
    conv_db.save_message(conversation_id, 'user', text, msg_metadata)

    # --- Auto-save lead ---
    try:
        lead_service.upsert_lead(
            tenant_id=tenant_id,
            phone=db_phone,
            push_name=push_name,
            conversation_id=conversation_id,
            language=language,
        )
        log.info(f'[LEAD] Captured | TenantID:{tenant_id} | Phone:{db_phone} | '
                 f'Name:{push_name} | Source:{source} | Status:OK')
    except Exception as e:
        log.error(f'[LEAD] Failed | TenantID:{tenant_id} | Phone:{db_phone} | Error:{e}')

    # Reset reengagement count on new user message
    conv_db.reset_reengagement(conversation_id)

    # --- Business hours check ---
    if not _is_within_business_hours(account_config):
        outside_msg = account_config.get('outside_hours_message')
        if outside_msg:
            if lid_unresolved:
                queue_db.enqueue(tenant_id, account_id, phone, outside_msg,
                                queue_type='pending_lid',
                                metadata={'lid_jid': phone, 'push_name': push_name})
            else:
                whatsapp.send_message(instance_name, send_phone, outside_msg)
        return

    # --- Human-like read delay (people read the message before typing) ---
    import random
    read_delay = random.uniform(1.5, 3.5)
    time.sleep(read_delay)

    # --- Typing indicator ---
    can_send = not lid_unresolved
    if can_send:
        whatsapp.set_typing(instance_name, send_phone, True)

    # --- Get agent config FIRST (needed for history limit) ---
    agent_config = tenants_db.get_active_agent_config(tenant_id)
    if not agent_config:
        agent_config = {
            'system_prompt': '',
            'model': 'claude-sonnet-4-20250514',
            'max_tokens': 150,
            'max_history_messages': 10,
            'persona': {},
            'tools_enabled': '["web_search","schedule_meeting","airtable_read","airtable_create","airtable_update","google_calendar_list","google_calendar_check","send_email"]',
        }

    # --- ADMIN: Runtime prompt override ---
    from app.db.redis_client import get_redis as _get_redis_prompt
    _r_prompt = _get_redis_prompt()
    if _r_prompt:
        _prompt_override = _r_prompt.get(f'admin:prompt_override:{instance_name}')
        if _prompt_override:
            agent_config = dict(agent_config)
            agent_config['system_prompt'] = _prompt_override

    # --- Load conversation context for AI ---
    max_history = agent_config.get('max_history_messages', 10)
    history = conv_db.get_message_history(conversation_id, limit=max_history)
    lead = leads_db.get_lead(tenant_id, db_phone)

    conversation_ctx = dict(conversation)
    conversation_ctx['messages'] = history
    conversation_ctx['lead'] = lead
    conversation_ctx['tenant_name'] = account.get('tenant_name', '')

    # Detect if this is a brand new lead (first interaction)
    is_new_lead = (not lead or lead.get('stage') == 'new') and len(history) <= 2
    conversation_ctx['is_new_lead'] = is_new_lead

    # Pass forwarded flag so AI knows not to respond as if message was directed at it
    if forwarded:
        conversation_ctx['is_forwarded'] = True

    # Per-tenant API key
    api_key = account.get('tenant_anthropic_key')

    # --- Resolve tenant settings for v5.1 engine ---
    tenant_settings = account.get('tenant_settings', {})
    if isinstance(tenant_settings, str):
        tenant_settings = json.loads(tenant_settings) if tenant_settings else {}

    # --- Slow response acknowledgment (disabled — clean UX for clients) ---
    ack_sent = threading.Event()
    ack_timer = None

    # --- Call AI (v6.0 engine wraps v5.1 with state machine + memory + reflection) ---
    try:
        result = process_v60(
            conversation=conversation_ctx,
            agent_config=agent_config,
            language=language,
            api_key=api_key,
            source=source,
            tenant_settings=tenant_settings,
        )
    finally:
        if ack_timer:
            ack_timer.cancel()
        ack_sent.set()  # Prevent late ack

    response_text = result['text']

    # Save assistant response (skip fallback responses to avoid polluting history)
    if not result.get('is_fallback'):
        conv_db.save_message(conversation_id, 'assistant', response_text, {
            'model': result['model'],
            'input_tokens': result['input_tokens'],
            'output_tokens': result['output_tokens'],
            'cost': result['cost'],
            'tool_calls': result.get('tool_calls', []),
            'source': source,
        })
    else:
        log.warning(f'[FALLBACK] Not saving fallback response to history: "{response_text}"')

    # Log consumption (with v5.1 engine metadata)
    chat_operation = 'engine_v51_cache' if result.get('cache_hit') else 'chat'
    consumption_db.log_usage(
        tenant_id=tenant_id,
        model=result['model'],
        input_tokens=result['input_tokens'],
        output_tokens=result['output_tokens'],
        cost=result['cost'],
        conversation_id=conversation_id,
        operation=chat_operation,
        metadata={
            'tool_calls': len(result.get('tool_calls', [])),
            'cache_hit': result.get('cache_hit', False),
            'engine_version': result.get('engine_version', 'v5.0'),
            'intent': result.get('intent', ''),
        },
    )

    # --- Report usage to Stripe (no-op without Stripe key) ---
    try:
        stripe_service.report_usage(tenant_id, quantity=1)
    except Exception as e:
        log.error(f'Stripe usage report error: {e}')

    # --- Generate conversation summary (async, non-blocking) ---
    try:
        from app.services import summary_service
        all_messages = conv_db.get_message_history(conversation_id, limit=50)
        if summary_service.should_generate_summary(conversation_id, len(all_messages)):
            threading.Thread(
                target=summary_service.generate_summary,
                args=(conversation_id, tenant_id, all_messages, api_key),
                name=f'summary-{conversation_id[:8]}',
                daemon=True,
            ).start()
    except Exception as e:
        log.error(f'Summary trigger error: {e}')

    # --- Extract voice persona config (with sensible defaults) ---
    persona = agent_config.get('persona', {})
    if isinstance(persona, str):
        import json as _json
        persona = _json.loads(persona) if persona else {}
    voice_config = persona.get('voice')

    # If persona has gender but no voice config, create a default
    if not voice_config and persona.get('gender'):
        gender = persona.get('gender', 'male')
        voice_config = {
            'enabled': True,
            'tts_voice': 'echo' if gender == 'male' else 'nova',
            'speed': 1.0,
            'default_language': language,
        }
        log.info(f'[VOICE] Created default voice config: {voice_config["tts_voice"]} for {gender}')

    sentiment = result.get('sentiment', 'neutral')

    # --- Send response ---
    if lid_unresolved:
        queue_db.enqueue(
            tenant_id, account_id, phone, response_text,
            queue_type='pending_lid',
            metadata={'lid_jid': phone, 'push_name': push_name},
        )
        log.info(f'[{instance_name}] Response PENDING for LID {phone}')

        # Late resolution attempt
        time.sleep(2)
        resolved_late = lid_resolver.resolve(account_id, instance_name, phone)
        if resolved_late:
            log.info(f'[{instance_name}] Late LID resolution: {phone} -> {resolved_late}')
            _deliver_pending_lid_responses(account, instance_name, phone, resolved_late)
        return

    # Adjust TTS speed based on detected sentiment for more natural delivery
    if source == 'audio' and voice_config and voice_config.get('enabled'):
        _sentiment_speeds = {
            'frustrated': 0.88,   # Slower = empathetic, calm, acolhedor
            'happy': 1.08,        # Slightly faster = energetic but not rushed
            'confused': 0.92,     # Slower = patient, clear, didatic
            'urgent': 1.12,       # Faster = direct, efficient, confident
            'neutral': 1.0,       # Natural baseline
        }
        # Only override if no custom speed was set by tenant
        base_speed = voice_config.get('speed', 1.0)
        if base_speed == 1.0:
            voice_config['speed'] = _sentiment_speeds.get(sentiment, 1.0)

    # Send response — audio for: incoming audio OR new leads (first contact)
    # New leads get audio greeting to create personal connection
    reply_type = 'text'
    should_send_audio = (
        voice_config and voice_config.get('enabled') and
        (source == 'audio' or is_new_lead)
    )
    if should_send_audio:
        sent = sender.send_audio_response(
            instance_name, send_phone, response_text,
            voice_config=voice_config,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            whatsapp_account_id=account_id,
            metadata={'push_name': push_name},
            sentiment=sentiment,
            persona=persona,
        )
        reply_type = 'audio' if source == 'audio' else 'audio_new_lead'
        # Log TTS cost — provider-aware (ElevenLabs vs OpenAI)
        from app.channels.transcriber import (
            TTS_MODEL, TTS_COST_PER_1K_CHARS,
            ELEVENLABS_MODEL, ELEVENLABS_COST_PER_1K_CHARS,
        )
        tts_chars = len(response_text)
        tts_provider = sent.get('provider', 'openai') if isinstance(sent, dict) else 'openai'
        if tts_provider == 'elevenlabs':
            tts_model = ELEVENLABS_MODEL
            tts_cost = round((tts_chars / 1000.0) * ELEVENLABS_COST_PER_1K_CHARS, 6)
        else:
            tts_model = TTS_MODEL
            tts_cost = round((tts_chars / 1000.0) * TTS_COST_PER_1K_CHARS, 6)
        try:
            consumption_db.log_usage(
                tenant_id=tenant_id, model=tts_model,
                input_tokens=tts_chars, output_tokens=0, cost=tts_cost,
                conversation_id=conversation_id, operation='tts',
                metadata={'voice': voice_config.get('tts_voice', ''), 'chars': tts_chars,
                          'sentiment': sentiment, 'provider': tts_provider},
            )
            log.info(f'[COST] TTS ({tts_provider}/{tts_model}): {tts_chars} chars = ${tts_cost}')
        except Exception as e:
            log.error(f'[COST] Failed to log TTS cost: {e}')
    else:
        if source == 'audio' and not voice_config:
            log.info(f'[{instance_name}] Audio input but no voice persona configured — replying as text')
        elif is_new_lead and not voice_config:
            log.info(f'[{instance_name}] New lead but no voice persona configured — replying as text')
        sent = sender.send_split_messages(
            instance_name, send_phone, response_text,
            tenant_id=tenant_id,
            whatsapp_account_id=account_id,
            metadata={'push_name': push_name},
        )

    # --- Track for admin /reply and /correct ---
    from app.db.redis_client import get_redis as _get_redis_track
    _r_track = _get_redis_track()
    if _r_track:
        _r_track.set(f'admin:last_chat:{instance_name}', send_phone, ex=3600)
        _r_track.set(f'admin:last_bot_msg:{instance_name}:{send_phone}',
                     response_text[:2000], ex=3600)

    # --- Track send health ---
    from app.services import health_service
    if sent:
        health_service.reset_failures(instance_name)
        log.info(f'[{instance_name}] {send_phone}: "{text[:40]}" -> [{reply_type}] "{response_text[:40]}"')
    else:
        failures = health_service.record_failure(instance_name)
        if failures >= config.WEBHOOK_MAX_FAILURES:
            health_service.alert_admin(tenant_id, instance_name, 'send_failed')
        log.warning(f'[{instance_name}] Send failed, queued for retry: {send_phone}')


def _deliver_pending_lid_responses(account, instance_name, lid_jid, phone):
    """Deliver pending LID responses now that LID is resolved."""
    try:
        tenant_id = str(account['tenant_id'])
        pending = queue_db.get_pending(queue_type='pending_lid', tenant_id=tenant_id)
        matched = [p for p in pending if p.get('metadata', {}).get('lid_jid') == lid_jid]
        if not matched:
            return

        oldest_created = matched[0].get('created_at')
        push_name = matched[0].get('metadata', {}).get('push_name', '')
        nome = push_name.split()[0] if push_name and is_real_name(push_name) else ''

        # Check age
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        if oldest_created and hasattr(oldest_created, 'timestamp'):
            age_seconds = (now - oldest_created).total_seconds()
        else:
            age_seconds = 0

        if age_seconds > PENDING_MAX_AGE_SECONDS:
            # Old messages: send resumption message
            if nome:
                msg = f'Oi {nome}! Tive um atraso tecnico aqui, desculpa. Ja estou de volta, como posso te ajudar?'
            else:
                msg = 'Oi! Desculpa a demora, tive um problema tecnico. Ja to de volta, no que posso ajudar?'
            whatsapp.set_typing(instance_name, phone, True)
            time.sleep(2.5)
            whatsapp.send_message(instance_name, phone, msg)
        elif len(matched) == 1:
            whatsapp.set_typing(instance_name, phone, True)
            time.sleep(2.0)
            whatsapp.send_message(instance_name, phone, matched[0]['content'])
        else:
            # Multiple pending: send explanation + last response
            whatsapp.set_typing(instance_name, phone, True)
            time.sleep(2.0)
            explanation = f'{nome}, desculpa o atraso tecnico! Ja normalizou.' if nome else 'Desculpa o atraso tecnico! Ja normalizou.'
            whatsapp.send_message(instance_name, phone, explanation)
            time.sleep(1.5)
            whatsapp.set_typing(instance_name, phone, True)
            time.sleep(2.0)
            whatsapp.send_message(instance_name, phone, matched[-1]['content'])

        # Mark all as delivered (tenant-scoped)
        for m in matched:
            queue_db.mark_delivered(m['id'], tenant_id=tenant_id)
        log.info(f'Delivered {len(matched)} pending LID responses to {phone}')

    except Exception as e:
        log.error(f'Error delivering pending LID responses: {e}')
