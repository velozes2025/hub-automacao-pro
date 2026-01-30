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


def transcribe_audio(instance_name, message_data, language='pt'):
    """Download audio from WhatsApp and transcribe via Whisper API.

    Args:
        instance_name: Evolution API instance name
        message_data: Full message payload from webhook
        language: Language hint for Whisper (default 'pt')

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
                data={'model': 'whisper-1', 'language': language or 'pt'},
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


import re

VALID_TTS_VOICES = {'alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'}


def _prepare_text_for_speech(text):
    """Clean and optimize text for natural TTS output.

    1. Strips markdown, URLs, emojis, formatting artifacts
    2. Converts newlines/lists into flowing speech
    3. Ensures punctuation that helps TTS produce natural pauses and intonation
    """
    t = text.strip()

    # --- Remove formatting artifacts ---
    # Markdown bold/italic
    t = re.sub(r'\*{1,3}(.+?)\*{1,3}', r'\1', t)
    t = re.sub(r'_{1,3}(.+?)_{1,3}', r'\1', t)
    # Markdown links [text](url) -> text
    t = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)
    # Raw URLs
    t = re.sub(r'https?://\S+', '', t)
    # Bullet points and list markers -> flowing text with pauses
    t = re.sub(r'^\s*[-•*]\s+', '', t, flags=re.MULTILINE)
    t = re.sub(r'^\s*\d+\.\s+', '', t, flags=re.MULTILINE)
    # Emojis
    t = re.sub(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF'
               r'\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0001F900-\U0001F9FF'
               r'\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002600-\U000026FF]+', '', t)

    # --- Add natural speech rhythm ---
    # Normalize ellipses to exactly 3 dots (TTS creates pauses with these)
    t = re.sub(r'\.{2,}', '...', t)
    # Colons become commas (micro-pause, flows better in speech)
    t = re.sub(r':\s*', ', ', t)

    # --- Convert structure to flowing speech ---
    # Newlines become natural sentence connectors
    t = re.sub(r'\n+', ', ', t)

    # --- Cleanup ---
    t = re.sub(r'\s{2,}', ' ', t)
    t = re.sub(r'^\.\s*', '', t)
    # Remove stray single dots (from newline collapse) but PRESERVE ellipses
    # Temporarily protect ellipses
    t = t.replace('...', '\x00PAUSE\x00')
    t = re.sub(r'\.\s*\.', '.', t)
    t = t.replace('\x00PAUSE\x00', '...')
    # Fix double punctuation (but not ellipses)
    t = re.sub(r'([!?])\s*([.!?])', r'\1', t)

    return t.strip()


def text_to_speech(text, voice_config=None):
    """Convert text to audio via OpenAI TTS API using agent voice persona.

    Args:
        text: Text to convert to speech (exact Claude response, no modifications).
        voice_config: Dict with voice persona settings:
            {
                'tts_voice': 'onyx',        # OpenAI TTS voice name
                'enabled': True,             # TTS enabled for this agent
                'default_language': 'pt',    # Primary language
            }
            If None or invalid, returns None (fallback to text).

    Returns:
        Dict {'audio_b64': str, 'voice': str, 'language': str} on success, or None.
    """
    if not config.OPENAI_API_KEY:
        log.warning('OPENAI_API_KEY not set — TTS disabled')
        return None

    # Validate voice config
    if not voice_config:
        log.info('TTS skipped: no voice config provided')
        return None

    if not voice_config.get('enabled', False):
        log.info('TTS skipped: voice not enabled for this agent')
        return None

    tts_voice = voice_config.get('tts_voice', '')
    if tts_voice not in VALID_TTS_VOICES:
        log.warning(f'TTS skipped: invalid voice "{tts_voice}" (valid: {VALID_TTS_VOICES})')
        return None

    language = voice_config.get('default_language', 'pt')

    # Clean text for natural speech output
    clean_text = _prepare_text_for_speech(text)
    if not clean_text:
        log.warning('TTS skipped: text empty after speech cleanup')
        return None

    try:
        # Use tts-1-hd for highest quality, most natural-sounding voice
        r = requests.post(
            'https://api.openai.com/v1/audio/speech',
            headers={
                'Authorization': f'Bearer {config.OPENAI_API_KEY}',
                'Content-Type': 'application/json',
            },
            json={
                'model': 'tts-1-hd',
                'input': clean_text,
                'voice': tts_voice,
                'response_format': 'opus',
                'speed': voice_config.get('speed', 1.0),
            },
            timeout=30,
        )

        if r.status_code == 200:
            audio_b64 = base64.b64encode(r.content).decode('utf-8')
            log.info(
                f'[TTS-AUDIT] voice={tts_voice} lang={language} '
                f'size={len(r.content)}B text="{text[:60]}"'
            )
            return {
                'audio_b64': audio_b64,
                'voice': tts_voice,
                'language': language,
            }
        else:
            log.error(f'TTS API error ({r.status_code}): {r.text[:200]}')
            return None

    except Exception as e:
        log.error(f'TTS error: {e}')
        return None


def get_audio_metadata(message_data):
    """Extract audio metadata from message payload."""
    audio_msg = message_data.get('message', {}).get('audioMessage', {})
    return {
        'duration_seconds': audio_msg.get('seconds', 0),
        'mimetype': audio_msg.get('mimetype', 'audio/ogg'),
        'file_length': audio_msg.get('fileLength', 0),
        'ptt': audio_msg.get('ptt', False),  # push-to-talk (voice note)
    }
