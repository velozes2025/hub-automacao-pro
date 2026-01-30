"""Message sending with retry, splitting, and typing simulation.

Handles:
- Long message splitting at sentence boundaries
- Typing indicator simulation between chunks
- Automatic retry queue on failure
"""

import re
import time
import random
import logging

from app.config import config
from app.channels import whatsapp
from app.channels import transcriber
from app.db import queue as queue_db

log = logging.getLogger('channels.sender')


def split_message(text, max_chars=None):
    """Split long text into chunks at sentence boundaries.

    Returns list of strings. Short messages return a single-item list.
    """
    if max_chars is None:
        max_chars = config.MSG_SPLIT_MAX_CHARS
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current = ''

    for sentence in sentences:
        if not sentence:
            continue
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


def _typing_delay(text_length):
    """Calculate typing delay with human-like variation.

    Humans don't type at constant speed — adds ±20% random variation
    to make the typing indicator feel natural.
    """
    base = text_length * config.TYPING_DELAY_PER_CHAR_MS / 1000.0
    # Add random variation (±20%)
    jitter = base * random.uniform(-0.2, 0.2)
    delay = base + jitter
    return max(config.TYPING_MIN_MS / 1000.0, min(delay, config.TYPING_MAX_MS / 1000.0))


def send_with_retry(instance_name, phone, text, tenant_id=None,
                    whatsapp_account_id=None, metadata=None):
    """Send message via WhatsApp. On failure, enqueue for retry.

    Returns True if sent immediately, False if queued.
    """
    sent = whatsapp.send_message(instance_name, phone, text)
    if sent:
        return True

    # Failed: save to retry queue
    if tenant_id and whatsapp_account_id:
        try:
            queue_db.enqueue(
                tenant_id=tenant_id,
                whatsapp_account_id=whatsapp_account_id,
                phone=phone,
                content=text,
                queue_type='failed',
                metadata=metadata or {},
            )
            log.warning(f'[RETRY-QUEUE] Response queued: {instance_name} -> {phone}')
        except Exception as e:
            log.error(f'[RETRY-QUEUE] CRITICAL - failed to queue: {e}')
    return False


def send_split_messages(instance_name, phone, text,
                        tenant_id=None, whatsapp_account_id=None, metadata=None):
    """Send message split into chunks with typing indicators.

    If any chunk fails, remaining chunks are queued for retry.
    Returns True if all chunks sent successfully.
    """
    chunks = split_message(text)

    if len(chunks) == 1:
        delay = _typing_delay(len(text))
        whatsapp.set_typing(instance_name, phone, True)
        time.sleep(delay)
        whatsapp.set_typing(instance_name, phone, False)
        return send_with_retry(instance_name, phone, text, tenant_id,
                              whatsapp_account_id, metadata)

    all_sent = True
    for i, chunk in enumerate(chunks):
        delay = _typing_delay(len(chunk))
        whatsapp.set_typing(instance_name, phone, True)
        time.sleep(delay)
        whatsapp.set_typing(instance_name, phone, False)

        sent = send_with_retry(instance_name, phone, chunk, tenant_id,
                              whatsapp_account_id, metadata)
        if not sent:
            remaining = ' '.join(chunks[i + 1:])
            if remaining and tenant_id and whatsapp_account_id:
                try:
                    queue_db.enqueue(
                        tenant_id=tenant_id,
                        whatsapp_account_id=whatsapp_account_id,
                        phone=phone,
                        content=remaining,
                        queue_type='failed',
                        metadata=metadata or {},
                    )
                except Exception:
                    pass
            all_sent = False
            break

        # Human-like pause between chunks (1.5-3.5s — like reading before typing again)
        if i < len(chunks) - 1:
            time.sleep(random.uniform(1.5, 3.5))

    return all_sent


def send_audio_response(instance_name, phone, text, voice_config=None,
                        conversation_id=None, tenant_id=None,
                        whatsapp_account_id=None, metadata=None,
                        sentiment='neutral', persona=None):
    """Convert text to audio using agent voice persona and send as voice note.

    Uses gpt-4o-mini-tts with voice instructions for natural-sounding speech.
    Falls back to text if TTS is disabled, voice config missing, or send fails.

    Args:
        voice_config: Agent voice persona dict from agent_configs.persona.voice
        conversation_id: For audit logging.
        sentiment: Detected user sentiment for tone adjustment.
        persona: Agent persona dict for voice instruction building.
    """
    # Generate audio via TTS with persona voice + sentiment-aware instructions
    tts_result = transcriber.text_to_speech(
        text, voice_config=voice_config, sentiment=sentiment, persona=persona,
    )
    if not tts_result:
        log.info(f'[AUDIO] Fallback to text (TTS unavailable): {phone}')
        return send_split_messages(instance_name, phone, text,
                                   tenant_id, whatsapp_account_id, metadata)

    log.info(
        f'[AUDIO-AUDIT] conv={conversation_id} phone={phone} '
        f'voice={tts_result["voice"]} lang={tts_result["language"]}'
    )

    # Show recording indicator then send audio
    whatsapp.set_typing(instance_name, phone, True)
    time.sleep(1.5)
    whatsapp.set_typing(instance_name, phone, False)

    sent = whatsapp.send_audio(instance_name, phone, tts_result['audio_b64'])
    if sent:
        return True

    # Audio send failed — fallback to text
    log.warning(f'[AUDIO] Send failed, falling back to text: {phone}')
    return send_split_messages(instance_name, phone, text,
                               tenant_id, whatsapp_account_id, metadata)
