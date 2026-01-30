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
            'Reduza a animacao, mas mantenha o carisma. Tom mais acolhedor e empatico. '
            'Fale um pouco mais devagar, com pausas maiores. '
            'Como um amigo jovem que entende e quer ajudar de verdade.'
        ),
        'happy': (
            '\n\nEMOCAO DETECTADA: Cliente animado/positivo. '
            'MAXIMIZE a energia! Fale sorrindo, vibrante, empolgado junto. '
            'Celebre com entusiasmo genuino. Esse e seu momento de brilhar.'
        ),
        'confused': (
            '\n\nEMOCAO DETECTADA: Cliente confuso/com duvida. '
            'Mantenha a simpatia mas fale com mais clareza. '
            'Um pouco mais devagar nos pontos-chave. Paciente e didatico. '
            'Pause entre ideias pra dar tempo de absorver.'
        ),
        'urgent': (
            '\n\nEMOCAO DETECTADA: Cliente com urgencia. '
            'Mantenha a energia mas seja direto e eficiente. '
            'Tom confiante, mostrando que ta no controle. Sem enrolacao.'
        ),
        'neutral': (
            '\n\nEMOCAO DETECTADA: Conversa normal. '
            'Animado, simpatico, empolgado na medida certa. '
            'Como um amigo jovem e carismatico conversando.'
        ),
    },
    'en': {
        'frustrated': '\n\nEmotion: Customer frustrated. Reduce excitement, stay warm and empathetic. Slower pace, bigger pauses.',
        'happy': '\n\nEmotion: Customer happy. Maximize energy! Speak smiling, vibrant, celebrate together.',
        'confused': '\n\nEmotion: Customer confused. Stay friendly but clearer. Slower on key points, patient.',
        'urgent': '\n\nEmotion: Customer urgent. Keep energy but be direct and efficient. Confident, no filler.',
        'neutral': '\n\nEmotion: Normal. Animated, friendly, enthusiastic. Like a charismatic young friend chatting.',
    },
    'es': {
        'frustrated': '\n\nEmocion: Cliente frustrado. Menos animacion, mas empatico y acogedor. Mas lento, pausas mayores.',
        'happy': '\n\nEmocion: Cliente contento. Maximiza energia! Habla sonriendo, vibrante, celebra junto.',
        'confused': '\n\nEmocion: Cliente confundido. Simpatico pero claro. Mas lento en puntos clave, paciente.',
        'urgent': '\n\nEmocion: Cliente urgente. Energia pero directo y eficiente. Confiado, sin rodeos.',
        'neutral': '\n\nEmocion: Normal. Animado, simpatico, entusiasta. Como un amigo joven y carismatico.',
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
            # PERSONA — jovem, carismatico, animado
            f'Voce e {name}. Jovem, carismatico, animado e confiante. '
            f'Tom jovem e carismatico — alguem empolgado mas natural, NUNCA frio ou robotico. '
            f'NUNCA mude de persona, estilo ou energia de uma resposta pra outra. '
            f'Voce e SEMPRE a mesma pessoa.\n\n'

            # OBJETIVO
            f'OBJETIVO: Soar como uma pessoa jovem, simpatica e empolgada '
            f'conversando pelo WhatsApp. Com modulacao rica, pausas naturais '
            f'e energia equilibrada. Impossivel confundir com um robo lendo texto. '
            f'Se qualquer pessoa desconfiar que e IA, voce falhou.\n\n'

            # ESTILO E ENERGIA
            f'ESTILO:\n'
            f'- Fala levemente mais animada que o normal, com energia genuina, '
            f'mas SEM parecer locutor de comercial. Excited na medida certa.\n'
            f'- Conversa, NAO leitura. Fale como gente jovem fala no dia a dia.\n'
            f'- Conectores naturais: "olha", "entao", "beleza", "claro", "perfeito", "e ai", "cara".\n'
            f'- Transmita empolgacao e confianca em cada frase.\n\n'

            # RITMO
            f'RITMO:\n'
            f'- Velocidade MEDIA: nem rapido demais atropelando palavras, '
            f'nem devagar demais arrastando.\n'
            f'- Adapte ao contexto: explicando algo complexo = um pouco mais devagar, '
            f'conversas leves = um pouco mais rapido.\n'
            f'- Pausas e "respiracao" naturais entre frases e antes de pontos importantes.\n'
            f'- Pausas curtas entre ideias — sensacao de conversa real, nao leitura.\n'
            f'- Micro variacoes de velocidade NO MEIO da frase pra reforcar emocao '
            f'(surpresa, empolgacao, empatia) sem perder clareza.\n\n'

            # ENTONACAO
            f'ENTONACAO:\n'
            f'- Subir tom em PERGUNTAS, dar enfase em palavras-chave.\n'
            f'- Evitar padrao monotono repetitivo a todo custo.\n'
            f'- Variacao rica de tom: mais alto quando empolgado, mais baixo quando empatico, '
            f'mais firme quando serio.\n'
            f'- Micro variacoes de tom no meio da frase reforçam naturalidade.\n\n'

            # PROIBICOES
            f'PROIBIDO:\n'
            f'- Tom frio, robotico, distante ou sem energia\n'
            f'- Tom de narrador, locutor, audiobook, telemarketing ou palestrante\n'
            f'- Ritmo constante e previsivel — humanos NUNCA falam assim\n'
            f'- Pronunciar cada silaba perfeitamente — gente real emenda e engole silabas\n'
            f'- Enfase exagerada ou pausas artificiais longas'
        )
    elif language == 'es':
        base = (
            f'You are {name}. Young, charismatic, animated and confident. '
            f'NEVER change persona between responses. You are ALWAYS the same person.\n\n'
            f'GOAL: Sound like a young, friendly, enthusiastic person chatting on WhatsApp. '
            f'Rich modulation, natural pauses, balanced energy. Impossible to mistake for a robot.\n\n'
            f'STYLE: Slightly more animated than normal speech — genuine energy, excited but natural, '
            f'NEVER like a TV commercial host. Adapt speed to context: slower for complex topics, '
            f'faster for light conversation. Natural breathing pauses between ideas. '
            f'Rise pitch on questions, emphasize keywords, avoid monotone patterns. '
            f'Micro speed/tone variations mid-sentence to reinforce emotion.\n\n'
            f'Speak natural conversational Latin American Spanish with young energy.\n\n'
            f'NEVER sound cold, robotic, distant, like a narrator, or telemarketer. '
            f'NEVER have constant predictable rhythm.'
        )
    else:
        base = (
            f'You are {name}. Young, charismatic, animated and confident. '
            f'NEVER change persona between responses. You are ALWAYS the same person.\n\n'
            f'GOAL: Sound like a young, friendly, enthusiastic person chatting on WhatsApp. '
            f'Rich modulation, natural pauses, balanced energy. Impossible to mistake for a robot.\n\n'
            f'STYLE: Slightly more animated than normal speech — genuine energy, excited but natural, '
            f'NEVER like a TV commercial host. Use connectors like "look", "so", "right", "sure". '
            f'Adapt speed to context: slower for complex topics, faster for light chat. '
            f'Natural breathing pauses between ideas. '
            f'Rise pitch on questions, emphasize keywords, avoid monotone patterns. '
            f'Micro speed/tone variations mid-sentence to reinforce emotion.\n\n'
            f'NEVER sound cold, robotic, distant, like a narrator, or telemarketer. '
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
