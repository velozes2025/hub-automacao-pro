"""Audio transcription via OpenAI Whisper API.

Downloads audio from Evolution API and transcribes to text.
Supports WhatsApp voice messages (.ogg/opus format).
"""

import os
import base64
import tempfile
import logging
import requests

from app.config import config
from app.channels import whatsapp

log = logging.getLogger('channels.transcriber')


def transcribe_audio(instance_name, message_data):
    """Download audio from WhatsApp and transcribe via Whisper API.

    Args:
        instance_name: Evolution API instance name
        message_data: Full message payload from webhook

    Returns:
        Transcribed text string, or None on failure.
    """
    if not config.OPENAI_API_KEY:
        log.warning('OPENAI_API_KEY not set — audio transcription disabled')
        return None

    message_key = message_data.get('key', {})

    # Download audio via Evolution API
    base64_audio = whatsapp.get_base64_media(instance_name, message_key)
    if not base64_audio:
        log.warning(f'Failed to download audio from {instance_name}')
        return None

    # Decode and write to temp file
    try:
        audio_bytes = base64.b64decode(base64_audio)
    except Exception as e:
        log.error(f'Base64 decode failed: {e}')
        return None

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        # Send to Whisper API
        with open(tmp_path, 'rb') as audio_file:
            r = requests.post(
                'https://api.openai.com/v1/audio/transcriptions',
                headers={'Authorization': f'Bearer {config.OPENAI_API_KEY}'},
                files={'file': ('audio.ogg', audio_file, 'audio/ogg')},
                data={'model': 'whisper-1', 'language': 'pt'},
                timeout=30,
            )

        if r.status_code == 200:
            text = r.json().get('text', '').strip()
            if text:
                log.info(f'Audio transcribed ({len(audio_bytes)} bytes): "{text[:80]}"')
                return text
            log.warning('Whisper returned empty text')
            return None
        else:
            log.error(f'Whisper API error ({r.status_code}): {r.text[:200]}')
            return None

    except Exception as e:
        log.error(f'Transcription error: {e}')
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def get_audio_metadata(message_data):
    """Extract audio metadata from message payload."""
    audio_msg = message_data.get('message', {}).get('audioMessage', {})
    return {
        'duration_seconds': audio_msg.get('seconds', 0),
        'mimetype': audio_msg.get('mimetype', 'audio/ogg'),
        'file_length': audio_msg.get('fileLength', 0),
        'ptt': audio_msg.get('ptt', False),  # push-to-talk (voice note)
    }
