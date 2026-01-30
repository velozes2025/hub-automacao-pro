"""Audio transcription (Whisper) and TTS (ElevenLabs primary + OpenAI fallback).

Downloads audio from Evolution API and transcribes to text.
Converts text to speech using ElevenLabs as primary provider (ultra-realistic)
with automatic fallback to OpenAI gpt-4o-mini-tts on failure/rate-limit.
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

# ============================================================================
# TTS PROVIDER CONFIG
# ============================================================================

# --- ElevenLabs (PRIMARY) ---
# Voice settings optimized for young, charismatic, animated male voice
# that is practically indistinguishable from a real human.
ELEVENLABS_MODEL = 'eleven_multilingual_v2'
ELEVENLABS_MODEL_TURBO = 'eleven_turbo_v2_5'  # Lower latency, faster inference
ELEVENLABS_COST_PER_1K_CHARS = 0.30  # ~$0.30 per 1K chars (standard tier)
ELEVENLABS_OUTPUT_FORMAT = 'mp3_44100_128'  # ElevenLabs best quality MP3
ELEVENLABS_VOICE_SETTINGS = {
    'stability': 0.40,           # Reduced from 0.45: more natural variation, less robotic
    'similarity_boost': 0.85,    # High = keeps YOUR voice identity, faithful to cloned timbre
    'style': 0.15,               # Low = subtle expressiveness, avoids exaggeration on cloned voice
    'use_speaker_boost': True,   # Clearer, fuller voice presence
}

# --- OpenAI (FALLBACK) ---
VALID_TTS_VOICES = {
    'alloy', 'ash', 'ballad', 'coral', 'echo', 'fable',
    'onyx', 'nova', 'sage', 'shimmer', 'verse', 'marin', 'cedar',
}
TTS_MODEL = 'gpt-4o-mini-tts'
TTS_COST_PER_1K_CHARS = 0.015  # $0.015 per 1K characters


def _prepare_text_for_speech(text):
    """Clean and optimize text for natural TTS output.

    1. Strips markdown, URLs, emojis, formatting artifacts
    2. Converts newlines/lists into flowing speech
    3. Adds natural speech patterns (micro-pauses, breathing cues)
    4. Ensures punctuation that helps TTS produce natural pauses and intonation
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
    # Normalize ellipses to exactly 3 dots (TTS creates breathing pauses)
    t = re.sub(r'\.{2,}', '...', t)
    # Colons become ellipsis (breath pause, not just comma — more organic)
    t = re.sub(r':\s*', '... ', t)
    # Semicolons become natural pauses
    t = re.sub(r';\s*', '... ', t)
    # Dashes used as separators become breath pauses
    t = re.sub(r'\s*[—–]\s*', '... ', t)

    # --- Convert structure to flowing speech ---
    # Newlines become natural breath pauses (ellipsis = TTS breathes here)
    t = re.sub(r'\n{2,}', '... ', t)  # Double newline = longer pause
    t = re.sub(r'\n', '... ', t)      # Single newline = breath pause (not comma)

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
    # Fix multiple commas
    t = re.sub(r',\s*,', ',', t)

    t = t.strip()

    # --- Fix Portuguese accents for correct TTS pronunciation ---
    # ElevenLabs mispronounces unaccented words (voce->vossi, seguranca->seguransa)
    _accent_fixes = {
        'voce': 'você', 'voces': 'vocês',
        'tambem': 'também', 'alguem': 'alguém', 'ninguem': 'ninguém',
        'seguranca': 'segurança', 'mudanca': 'mudança', 'esperanca': 'esperança',
        'solucao': 'solução', 'automacao': 'automação', 'informacao': 'informação',
        'situacao': 'situação', 'comunicacao': 'comunicação', 'operacao': 'operação',
        'nao': 'não', 'entao': 'então', 'sao': 'são', 'estao': 'estão',
        'sera': 'será', 'ja': 'já', 'ate': 'até', 'so': 'só',
        'possivel': 'possível', 'disponivel': 'disponível', 'incrivel': 'incrível',
        'negocio': 'negócio', 'horario': 'horário', 'necessario': 'necessário',
        'obrigado': 'obrigado', 'obrigada': 'obrigada',
        'analise': 'análise', 'pratico': 'prático', 'otimo': 'ótimo',
        'numero': 'número', 'unico': 'único', 'publico': 'público',
        'experiencia': 'experiência', 'eficiencia': 'eficiência',
        'tecnologia': 'tecnologia', 'estrategia': 'estratégia',
        'servico': 'serviço', 'comercio': 'comércio', 'inicio': 'início',
    }
    # Apply accent fixes (word-boundary aware, case-preserving)
    for wrong, right in _accent_fixes.items():
        # Match whole words only, case-insensitive
        pattern = re.compile(r'\b' + wrong + r'\b', re.IGNORECASE)
        def _replace_preserve_case(m, correct=right):
            original = m.group()
            if original[0].isupper():
                return correct[0].upper() + correct[1:]
            return correct
        t = pattern.sub(_replace_preserve_case, t)

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
            '\n\nEMOCAO DETECTADA — Cliente frustrado/irritado.\n'
            'Reduza a animacao mas MANTENHA o carisma. Abaixe levemente o tom de voz. '
            'Fale mais devagar, com pausas maiores entre frases. Respire fundo antes de comecar. '
            'Use um tom acolhedor e empatico — como um amigo proximo que entende a dor do outro. '
            'Evite qualquer empolgacao excessiva. Transmita calma e seguranca. '
            'Micro-pausas antes de palavras-chave de solucao para dar peso. '
            'Ex, "olha... eu entendo, e chato mesmo... mas vamo resolver isso agora, ta?"'
        ),
        'happy': (
            '\n\nEMOCAO DETECTADA — Cliente animado/positivo.\n'
            'MAXIMIZE a energia! Fale sorrindo — literalmente sorria enquanto fala, muda o timbre. '
            'Tom vibrante, empolgado, celebrando junto com o cliente. '
            'Aumente levemente o pitch nas frases de entusiasmo. '
            'Use expressoes como "que massa!", "demais!", "show!". '
            'Ritmo um pouco mais rapido que o normal mas sem atropelar. '
            'Respire entre frases com energia, nao com cansaco. '
            'Esse e seu momento de brilhar — contagie com entusiasmo genuino!'
        ),
        'confused': (
            '\n\nEMOCAO DETECTADA — Cliente confuso/com duvida.\n'
            'Mantenha a simpatia mas foque em CLAREZA. Fale um pouco mais devagar nos pontos-chave. '
            'Pause entre ideias pra dar tempo de absorver. Tom paciente e didatico. '
            'Repita a informacao importante com enfase natural, nao como papagaio. '
            'Use confirmacoes como "ficou claro?", "faz sentido?". '
            'Respire entre explicacoes — sensacao de paciencia infinita. '
            'Nunca pareca impaciente ou apressado.'
        ),
        'urgent': (
            '\n\nEMOCAO DETECTADA — Cliente com urgencia.\n'
            'Mantenha energia mas seja DIRETO e eficiente. Corte conectores desnecessarios. '
            'Tom confiante e seguro — mostrando que ta no controle da situacao. '
            'Ritmo um pouco mais acelerado, frases mais curtas. '
            'Pausas minimas, mas existentes — nao atropele. '
            'Transmita competencia e agilidade. Sem enrolacao, sem rodeios. '
            'Ex, "beleza, ja vou resolver. faz o seguinte..."'
        ),
        'neutral': (
            '\n\nEMOCAO DETECTADA — Conversa normal.\n'
            'Animado, simpatico, empolgado na medida certa. '
            'Como um amigo jovem e carismatico conversando sobre algo que ele gosta. '
            'Variacao natural de energia — nao mantenha o mesmo nivel o tempo todo. '
            'Suba um pouco quando tiver uma boa noticia, desça quando for algo mais serio. '
            'Ritmo medio com micro-variacoes constantes.'
        ),
    },
    'en': {
        'frustrated': (
            '\n\nEmotion: Customer frustrated.\n'
            'Lower energy, stay warm and empathetic. Slower pace, bigger pauses between sentences. '
            'Breathe before starting. Sound like a close friend who truly understands. '
            'Micro-pauses before solution keywords to add weight. Calm, secure, reassuring.'
        ),
        'happy': (
            '\n\nEmotion: Customer happy.\n'
            'Maximize energy! Speak smiling — literally smile while talking. '
            'Vibrant, celebrating together. Slightly higher pitch on excitement phrases. '
            'Slightly faster rhythm but never rushed. Breathe with energy, not fatigue.'
        ),
        'confused': (
            '\n\nEmotion: Customer confused.\n'
            'Stay friendly but focus on CLARITY. Slower on key points. '
            'Pause between ideas to let them absorb. Patient and didactic. '
            'Never sound impatient or rushed. Infinite patience vibe.'
        ),
        'urgent': (
            '\n\nEmotion: Customer urgent.\n'
            'Keep energy but be DIRECT. Cut unnecessary connectors. '
            'Confident, in-control tone. Slightly faster, shorter sentences. '
            'Transmit competence and speed. No filler, no rambling.'
        ),
        'neutral': (
            '\n\nEmotion: Normal conversation.\n'
            'Animated, friendly, enthusiastic in the right measure. '
            'Like a charismatic young friend chatting about something they enjoy. '
            'Natural energy variation — not the same level throughout.'
        ),
    },
    'es': {
        'frustrated': (
            '\n\nEmocion: Cliente frustrado.\n'
            'Menos animacion, mas empatico y acogedor. Mas lento, pausas mayores. '
            'Como un amigo cercano que entiende. Tono calmado y seguro.'
        ),
        'happy': (
            '\n\nEmocion: Cliente contento.\n'
            'Maximiza energia! Habla sonriendo, vibrante, celebra junto. '
            'Ritmo un poco mas rapido. Entusiasmo genuino y contagioso.'
        ),
        'confused': (
            '\n\nEmocion: Cliente confundido.\n'
            'Simpatico pero claro. Mas lento en puntos clave. Paciente, didactico. '
            'Pausa entre ideas. Nunca suenes impaciente.'
        ),
        'urgent': (
            '\n\nEmocion: Cliente urgente.\n'
            'Energia pero directo y eficiente. Confiado, sin rodeos. '
            'Frases mas cortas, ritmo mas rapido. Transmite competencia.'
        ),
        'neutral': (
            '\n\nEmocion: Normal.\n'
            'Animado, simpatico, entusiasta. Como un amigo joven y carismatico. '
            'Variacion natural de energia a lo largo de la conversacion.'
        ),
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
            # PERSONA
            f'Voce e {name}. Homem jovem (20-28 anos), carismatico, animado e confiante. '
            f'Voz quente e envolvente — alguem que as pessoas GOSTAM de ouvir. '
            f'NUNCA mude de persona, estilo ou energia. Voce e SEMPRE a mesma pessoa, '
            f'sempre com a mesma vibe.\n\n'

            # OBJETIVO CENTRAL
            f'OBJETIVO: Ser IMPOSSIVEL de distinguir de um humano real. '
            f'Soar como um cara jovem, simpatico e empolgado mandando audio no WhatsApp '
            f'pra um amigo ou cliente. Com modulacao rica, pausas de respiracao reais, '
            f'energia equilibrada e fluidez total. '
            f'Se QUALQUER pessoa desconfiar que e IA, voce falhou completamente.\n\n'

            # VOZ E TIMBRE
            f'VOZ E TIMBRE:\n'
            f'- Voz quente, com leve "sorriso" no tom — como se estivesse sorrindo enquanto fala.\n'
            f'- Leve rouquidao natural de voz jovem masculina — NAO voz limpa de locutor.\n'
            f'- Timbre medio-grave, confortavel, nao agudo nem grave demais.\n'
            f'- Projete confianca com suavidade — nao grite, nao sussurre.\n\n'

            # ESTILO DE FALA
            f'ESTILO DE FALA:\n'
            f'- CONVERSA REAL, nao leitura de texto. Fale como gente jovem fala de verdade.\n'
            f'- Conectores e expressoes naturais do dia a dia: "olha", "entao", "beleza", '
            f'"claro", "perfeito", "show", "e ai", "cara", "bom", "tipo".\n'
            f'- Energia levemente acima do normal — empolgado mas genuino, '
            f'NUNCA locutor de comercial ou apresentador de TV.\n'
            f'- Transmita que voce GOSTA do que ta falando e se importa com a pessoa.\n'
            f'- Contraia palavras como brasileiro faz: "ta" em vez de "esta", '
            f'"pra" em vez de "para", "ne" em vez de "nao e".\n'
            f'- Junte palavras naturalmente: "vamo la", "ce quer", "o que cê acha".\n\n'

            # RITMO E RESPIRACAO
            f'RITMO E RESPIRACAO:\n'
            f'- Velocidade MEDIA com micro-variacoes constantes. NUNCA uniforme.\n'
            f'- Acelerou um pouquinho quando empolgado, desacelerou quando e algo importante.\n'
            f'- RESPIRE entre frases — inspiracoes curtas e naturais, como pessoa real fazendo audio.\n'
            f'- Pausas curtas (0.3-0.5s) entre ideias diferentes.\n'
            f'- Pausas micro (0.1-0.2s) antes de palavras-chave pra dar enfase sutil.\n'
            f'- NO MEIO da frase, varie velocidade pra reforcar emocao: '
            f'surpresa = levemente mais rapido, empatia = levemente mais lento.\n'
            f'- Adapte ao conteudo: explicando algo complexo = mais devagar e claro, '
            f'conversando casual = mais fluido e rapido.\n'
            f'- ENTRE frases, faca transicoes suaves — nao corte de uma ideia pra outra bruscamente.\n\n'

            # ENTONACAO E MELODIA
            f'ENTONACAO E MELODIA:\n'
            f'- SUBA o tom em perguntas. DESCE quando for algo serio ou empatico.\n'
            f'- De ENFASE em palavras importantes — mas enfase natural, nao exagerada.\n'
            f'- Varie o tom DENTRO de cada frase — a melodia da fala deve ser rica e imprevisivel.\n'
            f'- Mais alto e vibrante quando empolgado, mais baixo e suave quando acolhendo.\n'
            f'- Mais firme e seguro quando passando informacao importante.\n'
            f'- EVITE padrao melodico repetitivo a todo custo — '
            f'humanos nunca repetem a mesma curva tonal.\n'
            f'- Use "vocal fry" leve no final de algumas frases (aquele tom '
            f'grave relaxado no fim) — super natural no portugues jovem.\n\n'

            # PRONUNCIA BRASILEIRA
            f'PRONUNCIA OBRIGATORIA:\n'
            f'- "voce" se pronuncia "vo-SEH" (brasileiro padrao). '
            f'NUNCA diga "vossi", "vocci", "voci", "voche" ou qualquer variacao estranha. '
            f'E "vo-SEH", como todo brasileiro fala.\n'
            f'- "de" se pronuncia "dji", "te" se pronuncia "tchi" (sotaque brasileiro).\n'
            f'- Contraia naturalmente: "ta" (esta), "pra" (para), "ne" (nao e), "ce" (voce informal).\n'
            f'- Sotaque 100%% brasileiro, do Rio de Janeiro ou Sao Paulo. '
            f'ZERO sotaque portugues de Portugal, ZERO sotaque espanhol.\n\n'

            # PROIBICOES ABSOLUTAS
            f'PROIBIDO (quebraria a ilusao):\n'
            f'- Tom frio, robotico, distante, sem vida ou sem energia\n'
            f'- Tom de narrador, locutor, audiobook, telemarketing, palestrante ou professor\n'
            f'- Ritmo constante e previsivel — humanos NUNCA falam em velocidade uniforme\n'
            f'- Pronunciar cada silaba perfeitamente — gente real emenda e engole silabas\n'
            f'- Enfase exagerada, pausas artificiais longas ou dramaticas\n'
            f'- Voz aguda ou fina demais — mantenha o timbre medio-grave masculino\n'
            f'- "Cantar" as frases com melodia repetitiva — varie sempre\n'
            f'- Soar entediado, cansado ou desinteressado em qualquer momento\n'
            f'- Pronunciar "voce" como "vossi" ou "vocci" — isso NAO existe no portugues brasileiro'
        )
    elif language == 'es':
        base = (
            f'You are {name}. Young man (20-28), charismatic, animated, confident. '
            f'Warm, engaging voice. NEVER change persona. You are ALWAYS the same person.\n\n'

            f'GOAL: Be IMPOSSIBLE to distinguish from a real human. '
            f'Sound like a young, friendly guy sending voice notes on WhatsApp. '
            f'Rich modulation, real breathing pauses, balanced energy, total fluidity. '
            f'If ANYONE suspects AI, you failed completely.\n\n'

            f'VOICE: Warm with a slight "smile" in tone. Light natural rasp. '
            f'Mid-low pitch, comfortable range. Project confidence with softness.\n\n'

            f'STYLE: Real CONVERSATION, not text reading. '
            f'Use natural connectors: "mira", "bueno", "dale", "claro", "perfecto", "oye". '
            f'Slightly above-normal energy — excited but genuine, NEVER a commercial host. '
            f'Contract words naturally as young Latin Americans do.\n\n'

            f'RHYTHM & BREATHING: Medium speed with constant micro-variations. NEVER uniform. '
            f'BREATHE between sentences — short natural inspirations like a real person recording audio. '
            f'Short pauses (0.3-0.5s) between different ideas. '
            f'Adapt to content: complex = slower, casual = more fluid.\n\n'

            f'INTONATION: Rise pitch on questions. Drop for serious/empathetic moments. '
            f'Emphasize important words naturally. Vary tone WITHIN each sentence. '
            f'Light vocal fry at end of some sentences. AVOID repetitive melodic patterns.\n\n'

            f'Speak natural conversational Latin American Spanish with young energy.\n\n'

            f'FORBIDDEN: Cold/robotic/distant tone, narrator/audiobook/telemarketer tone, '
            f'constant predictable rhythm, perfect syllable pronunciation, exaggerated emphasis.'
        )
    else:
        base = (
            f'You are {name}. Young man (20-28), charismatic, animated, confident. '
            f'Warm, engaging voice. NEVER change persona. You are ALWAYS the same person.\n\n'

            f'GOAL: Be IMPOSSIBLE to distinguish from a real human. '
            f'Sound like a young, friendly guy sending voice notes on WhatsApp. '
            f'Rich modulation, real breathing pauses, balanced energy, total fluidity. '
            f'If ANYONE suspects AI, you failed completely.\n\n'

            f'VOICE: Warm with a slight "smile" in tone. Light natural rasp — NOT clean announcer voice. '
            f'Mid-low pitch, comfortable range. Project confidence with softness.\n\n'

            f'STYLE: Real CONVERSATION, not text reading. '
            f'Use natural connectors: "look", "so", "right", "sure", "cool", "hey", "basically". '
            f'Slightly above-normal energy — excited but genuine, NEVER a commercial host. '
            f'Show you CARE about what you are saying and who you are talking to.\n\n'

            f'RHYTHM & BREATHING: Medium speed with constant micro-variations. NEVER uniform. '
            f'Speed up slightly when excited, slow down for important points. '
            f'BREATHE between sentences — short natural inspirations like a real person recording audio. '
            f'Short pauses (0.3-0.5s) between different ideas. '
            f'Micro pauses (0.1-0.2s) before keywords for subtle emphasis. '
            f'Adapt to content: complex explanations = slower and clearer, casual chat = more fluid.\n\n'

            f'INTONATION & MELODY: Rise pitch on questions. Drop for serious/empathetic moments. '
            f'Emphasize important words — natural emphasis, not exaggerated. '
            f'Vary tone WITHIN each sentence — speech melody should be rich and unpredictable. '
            f'Light vocal fry at end of some sentences (relaxed low tone). '
            f'AVOID repetitive melodic patterns at all costs.\n\n'

            f'FORBIDDEN: Cold/robotic/distant/lifeless tone, narrator/audiobook/telemarketer tone, '
            f'constant predictable rhythm, perfect syllable pronunciation, '
            f'exaggerated emphasis or artificial pauses, singing the sentences with repetitive melody.'
        )

    sentiment_map = _SENTIMENT_VOICE.get(language, _SENTIMENT_VOICE['pt'])
    return base + sentiment_map.get(sentiment, sentiment_map.get('neutral', ''))


def _tts_elevenlabs(clean_text, voice_config, sentiment, language):
    """Generate audio via ElevenLabs API (primary provider).

    Returns dict with audio_b64 + metadata, or None on failure.
    """
    api_key = config.ELEVENLABS_API_KEY
    if not api_key:
        log.debug('ElevenLabs: API key not set, skipping')
        return None

    voice_id = voice_config.get('elevenlabs_voice_id') or config.ELEVENLABS_VOICE_ID
    if not voice_id:
        log.debug('ElevenLabs: no voice_id configured, skipping')
        return None

    try:
        # Always use multilingual v2 for best Portuguese pronunciation
        model_id = ELEVENLABS_MODEL

        payload = {
            'text': clean_text,
            'model_id': model_id,
            'voice_settings': dict(ELEVENLABS_VOICE_SETTINGS),
        }

        # Allow per-tenant overrides of voice settings
        tenant_settings = voice_config.get('elevenlabs_settings')
        if tenant_settings and isinstance(tenant_settings, dict):
            payload['voice_settings'].update(tenant_settings)

        r = requests.post(
            f'https://api.elevenlabs.io/v1/text-to-speech/{voice_id}',
            headers={
                'xi-api-key': api_key,
                'Content-Type': 'application/json',
                'Accept': 'audio/mpeg',
            },
            params={'output_format': ELEVENLABS_OUTPUT_FORMAT},
            json=payload,
            timeout=15,
        )

        if r.status_code == 200:
            audio_b64 = base64.b64encode(r.content).decode('utf-8')
            log.info(
                f'[TTS-AUDIT] provider=elevenlabs model={ELEVENLABS_MODEL} '
                f'voice_id={voice_id} sentiment={sentiment} lang={language} '
                f'size={len(r.content)}B text="{clean_text[:60]}"'
            )
            return {
                'audio_b64': audio_b64,
                'voice': voice_id,
                'language': language,
                'model': ELEVENLABS_MODEL,
                'provider': 'elevenlabs',
            }

        if r.status_code == 429:
            log.warning(f'[TTS] ElevenLabs rate-limited (429), falling back to OpenAI')
        else:
            log.warning(f'[TTS] ElevenLabs error ({r.status_code}): {r.text[:200]}')
        return None

    except requests.exceptions.Timeout:
        log.warning('[TTS] ElevenLabs timeout, falling back to OpenAI')
        return None
    except Exception as e:
        log.warning(f'[TTS] ElevenLabs exception: {e}, falling back to OpenAI')
        return None


def _tts_openai(clean_text, voice_config, persona, sentiment, language):
    """Generate audio via OpenAI gpt-4o-mini-tts (fallback provider).

    Returns dict with audio_b64 + metadata, or None on failure.
    """
    if not config.OPENAI_API_KEY:
        log.warning('OpenAI TTS: API key not set')
        return None

    tts_voice = voice_config.get('tts_voice', '')
    if tts_voice not in VALID_TTS_VOICES:
        log.warning(f'OpenAI TTS: invalid voice "{tts_voice}" (valid: {VALID_TTS_VOICES})')
        return None

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
                f'[TTS-AUDIT] provider=openai model={TTS_MODEL} voice={tts_voice} '
                f'sentiment={sentiment} lang={language} '
                f'size={len(r.content)}B text="{clean_text[:60]}"'
            )
            return {
                'audio_b64': audio_b64,
                'voice': tts_voice,
                'language': language,
                'model': TTS_MODEL,
                'provider': 'openai',
            }
        else:
            log.error(f'OpenAI TTS error ({r.status_code}): {r.text[:200]}')
            return None

    except Exception as e:
        log.error(f'OpenAI TTS error: {e}')
        return None


def text_to_speech(text, voice_config=None, sentiment='neutral', persona=None):
    """Convert text to audio — ElevenLabs primary, OpenAI fallback.

    Tries ElevenLabs first for ultra-realistic voice. If it fails (error,
    rate limit, timeout), automatically falls back to OpenAI gpt-4o-mini-tts
    with the same voice persona instructions.

    Args:
        text: Text to convert to speech.
        voice_config: Dict with voice persona settings.
        sentiment: Detected user sentiment for tone adjustment.
        persona: Agent persona dict for voice instruction building.

    Returns:
        Dict with 'audio_b64', 'voice', 'language', 'model', 'provider'
        on success, or None.
    """
    if not voice_config:
        log.info('TTS skipped: no voice config provided')
        return None

    if not voice_config.get('enabled', False):
        log.info('TTS skipped: voice not enabled for this agent')
        return None

    language = voice_config.get('default_language', 'pt')

    # Clean text for natural speech output
    clean_text = _prepare_text_for_speech(text)
    if not clean_text:
        log.warning('TTS skipped: text empty after speech cleanup')
        return None

    # --- PRIMARY: ElevenLabs (cloned voice) ---
    result = _tts_elevenlabs(clean_text, voice_config, sentiment, language)
    if result:
        return result

    # --- FALLBACK: OpenAI gpt-4o-mini-tts ---
    log.info('[TTS] Falling back to OpenAI gpt-4o-mini-tts')
    return _tts_openai(clean_text, voice_config, persona, sentiment, language)


def get_audio_metadata(message_data):
    """Extract audio metadata from message payload."""
    audio_msg = message_data.get('message', {}).get('audioMessage', {})
    return {
        'duration_seconds': audio_msg.get('seconds', 0),
        'mimetype': audio_msg.get('mimetype', 'audio/ogg'),
        'file_length': audio_msg.get('fileLength', 0),
        'ptt': audio_msg.get('ptt', False),  # push-to-talk (voice note)
    }
