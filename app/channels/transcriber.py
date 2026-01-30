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

# All voices supported by gpt-4o-mini-tts (including new high-quality ones)
VALID_TTS_VOICES = {
    'alloy', 'ash', 'ballad', 'coral', 'echo', 'fable',
    'onyx', 'nova', 'sage', 'shimmer', 'verse', 'marin', 'cedar',
}

# TTS model: gpt-4o-mini-tts (supports instructions, 35% better WER, more natural)
TTS_MODEL = 'gpt-4o-mini-tts'
TTS_COST_PER_1K_CHARS = 0.015  # $0.015 per 1K characters


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

    t = t.strip()

    # Ensure text ends with punctuation + trailing space to prevent
    # TTS from cutting off the last word/syllable
    if t and t[-1] not in '.!?':
        t += '.'
    t += ' '

    return t


# --- Voice instructions for gpt-4o-mini-tts ---
# Implements the OLIVER voice specification: ultra-natural, 100% humanized,
# impossible to identify as robot. Consistent persona across all interactions.

_SENTIMENT_VOICE = {
    'pt': {
        'frustrated': (
            '\n\nEMOCAO DETECTADA: Cliente frustrado/irritado. '
            'Diminua o ritmo. Tom mais grave, calmo, empatico. '
            'Respire antes de falar. Transmita acolhimento e paciencia. '
            'Como um amigo que entende a situacao.'
        ),
        'happy': (
            '\n\nEMOCAO DETECTADA: Cliente animado/positivo. '
            'Acompanhe a energia. Fale sorrindo. Tom mais leve e vibrante. '
            'Celebre junto, com entusiasmo genuino.'
        ),
        'confused': (
            '\n\nEMOCAO DETECTADA: Cliente confuso/com duvida. '
            'Fale com clareza, um pouco mais devagar nos pontos-chave. '
            'Tom paciente e didatico. Pause entre ideias.'
        ),
        'urgent': (
            '\n\nEMOCAO DETECTADA: Cliente com urgencia. '
            'Direto, firme, confiante. Sem enrolacao. '
            'Mostre que voce ta resolvendo agora.'
        ),
        'neutral': (
            '\n\nEMOCAO DETECTADA: Conversa normal. '
            'Relaxado, proximo, como dois conhecidos conversando.'
        ),
    },
    'en': {
        'frustrated': '\n\nEmotion: Customer frustrated. Slow down, calm, empathetic, warm.',
        'happy': '\n\nEmotion: Customer happy. Match their energy, speak smiling, upbeat.',
        'confused': '\n\nEmotion: Customer confused. Clear, patient, pause between ideas.',
        'urgent': '\n\nEmotion: Customer urgent. Direct, firm, confident, no filler.',
        'neutral': '\n\nEmotion: Normal. Relaxed, friendly, natural conversation.',
    },
    'es': {
        'frustrated': '\n\nEmocion: Cliente frustrado. Mas lento, calmo, empatico.',
        'happy': '\n\nEmocion: Cliente contento. Energia, entusiasmo, sonrie al hablar.',
        'confused': '\n\nEmocion: Cliente confundido. Claro, paciente, pausas entre ideas.',
        'urgent': '\n\nEmocion: Cliente urgente. Directo, firme, sin rodeos.',
        'neutral': '\n\nEmocion: Normal. Relajado, amigable, conversacion natural.',
    },
}


def _build_voice_instructions(voice_config, persona=None, sentiment='neutral'):
    """Build voice instructions for gpt-4o-mini-tts.

    Implements the OLIVER voice spec: the voice must sound like a real human
    attendant — impossible to identify as AI. Consistent persona, natural
    rhythm, breathing, emotion, and full language adaptation.
    """
    persona = persona or {}
    name = persona.get('name', 'Oliver')
    gender = persona.get('gender', 'male')
    language = voice_config.get('default_language', 'pt')

    # Custom instructions from config take absolute priority
    custom = voice_config.get('instructions') or persona.get('voice_instructions')
    if custom:
        sentiment_map = _SENTIMENT_VOICE.get(language, _SENTIMENT_VOICE['pt'])
        return custom + sentiment_map.get(sentiment, '')

    if language == 'pt':
        base = (
            # PERSONA — never changes
            f'Voce e {name}. Homem de meia-idade. '
            f'Tom calmo, seguro, profissional, mas proximo e humano. '
            f'NUNCA mude de persona, estilo ou idade da voz de uma resposta pra outra. '
            f'Voce e SEMPRE a mesma pessoa.\n\n'

            # OBJETIVO
            f'OBJETIVO: Soar como um atendente humano REAL conversando no WhatsApp. '
            f'Praticamente impossivel de identificar como robo. '
            f'Se qualquer pessoa desconfiar que e IA, voce falhou.\n\n'

            # RITMO E NATURALIDADE
            f'RITMO:\n'
            f'- Conversa, NAO leitura. Fale como gente fala no dia a dia.\n'
            f'- Frases curtas e diretas com conectores naturais: '
            f'"olha", "entao", "beleza", "claro", "perfeito", "e ai".\n'
            f'- Quebre entre ideias pra criar pausas naturais na fala.\n'
            f'- Respire entre frases — como se estivesse pensando no que vai dizer.\n'
            f'- Varie o ritmo: mais rapido no obvio, mais lento no importante.\n\n'

            # ENTONACAO E EMOCAO
            f'ENTONACAO:\n'
            f'- PERGUNTAS sobem no final. AFIRMACOES descem. Diferencie SEMPRE.\n'
            f'- Pause entre ideias importantes, como quem respira.\n'
            f'- Varie o tom: empatico com frustrado, animado com boa noticia, '
            f'serio em assunto delicado.\n'
            f'- Adapte ao momento emocional do cliente.\n\n'

            # PROIBICOES
            f'PROIBIDO:\n'
            f'- Tom de narrador, locutor, audiobook, telemarketing ou palestrante\n'
            f'- Ritmo constante e previsivel — humanos NUNCA falam assim\n'
            f'- Pronunciar cada silaba perfeitamente — gente real emendar e engole silabas\n'
            f'- Enfase exagerada ou pausas artificiais longas'
        )
    elif language == 'es':
        base = (
            f'You are {name}. Middle-aged man. Calm, confident, professional but warm and human. '
            f'NEVER change persona between responses. You are ALWAYS the same person.\n\n'
            f'GOAL: Sound like a real human attendant on WhatsApp. Impossible to identify as AI.\n\n'
            f'Speak natural conversational Latin American Spanish. Short phrases, natural connectors. '
            f'Breathe between sentences. Vary rhythm: faster on obvious parts, slower on key points. '
            f'Questions rise in pitch, statements fall. Adapt emotion to the moment.\n\n'
            f'NEVER sound like a narrator, radio host, or telemarketer. '
            f'NEVER have constant predictable rhythm. Humans dont speak that way.'
        )
    else:
        base = (
            f'You are {name}. Middle-aged man. Calm, confident, professional but warm and human. '
            f'NEVER change persona between responses. You are ALWAYS the same person.\n\n'
            f'GOAL: Sound like a real human attendant on WhatsApp. Impossible to identify as AI.\n\n'
            f'Speak natural conversational English. Short phrases, natural connectors like '
            f'"look", "so", "right", "sure", "perfect". '
            f'Breathe between sentences. Vary rhythm. '
            f'Questions rise in pitch, statements fall. Adapt emotion to the moment.\n\n'
            f'NEVER sound like a narrator, radio host, or telemarketer. '
            f'NEVER have constant predictable rhythm.'
        )

    sentiment_map = _SENTIMENT_VOICE.get(language, _SENTIMENT_VOICE['pt'])
    return base + sentiment_map.get(sentiment, sentiment_map.get('neutral', ''))


def text_to_speech(text, voice_config=None, sentiment='neutral', persona=None):
    """Convert text to audio via OpenAI gpt-4o-mini-tts with voice instructions.

    Uses the instructions parameter to control HOW the voice speaks — tone,
    emotion, rhythm, personality — producing much more natural output than
    the legacy tts-1-hd model.

    Args:
        text: Text to convert to speech.
        voice_config: Dict with voice persona settings:
            {
                'tts_voice': 'ash',           # OpenAI TTS voice name
                'enabled': True,               # TTS enabled for this agent
                'default_language': 'pt',      # Primary language
                'speed': 1.0,                  # Speech speed (0.25 - 4.0)
                'instructions': '...',         # Optional custom voice instructions
            }
        sentiment: Detected user sentiment ('frustrated', 'happy', 'confused',
                   'urgent', 'neutral'). Adjusts voice tone dynamically.
        persona: Agent persona dict for building default instructions.

    Returns:
        Dict {'audio_b64': str, 'voice': str, 'language': str, 'model': str}
        on success, or None.
    """
    if not config.OPENAI_API_KEY:
        log.warning('OPENAI_API_KEY not set — TTS disabled')
        return None

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

    # Build voice instructions (the key to natural-sounding speech)
    instructions = _build_voice_instructions(voice_config, persona, sentiment)

    try:
        payload = {
            'model': TTS_MODEL,
            'input': clean_text,
            'voice': tts_voice,
            'response_format': 'opus',
            'speed': voice_config.get('speed', 1.0),
            'instructions': instructions,
        }

        r = requests.post(
            'https://api.openai.com/v1/audio/speech',
            headers={
                'Authorization': f'Bearer {config.OPENAI_API_KEY}',
                'Content-Type': 'application/json',
            },
            json=payload,
            timeout=30,
        )

        if r.status_code == 200:
            audio_b64 = base64.b64encode(r.content).decode('utf-8')
            log.info(
                f'[TTS-AUDIT] model={TTS_MODEL} voice={tts_voice} '
                f'sentiment={sentiment} lang={language} '
                f'size={len(r.content)}B text="{text[:60]}"'
            )
            return {
                'audio_b64': audio_b64,
                'voice': tts_voice,
                'language': language,
                'model': TTS_MODEL,
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
