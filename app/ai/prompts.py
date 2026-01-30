"""System prompt assembly and text utilities."""

import re
import logging

log = logging.getLogger('ai.prompts')

# --- Fake name detection ---

_FAKE_NAMES = {
    'automation', 'bot', 'business', 'company', 'enterprise', 'admin',
    'test', 'teste', 'user', 'usuario', 'client', 'cliente', 'support',
    'suporte', 'info', 'contact', 'contato', 'shop', 'store', 'loja',
    'marketing', 'sales', 'vendas', 'service', 'servico', 'official',
    'oficial', 'news', 'tech', 'digital', 'group', 'grupo', 'team',
    'equipe', 'manager', 'gerente', 'assistant', 'assistente', 'help',
    'ajuda', 'welcome', 'delivery', 'app', 'web', 'dev', 'api',
}

_BIZ_PATTERN = re.compile(r'\b(llc|ltd|inc|corp|sa|ltda|eireli|mei|co\.)\b', re.IGNORECASE)


def is_real_name(name):
    """Detect if a push_name looks like a real person name."""
    if not name or len(name.strip()) < 2:
        return False
    n = name.strip().lower()
    if n in _FAKE_NAMES:
        return False
    if not re.search(r'[a-zA-ZÀ-ÿ]', name):
        return False
    if len(name.strip()) == 1:
        return False
    if _BIZ_PATTERN.search(n):
        return False
    return True


# --- Language detection ---

_EN_WORDS = re.compile(
    r'\b(hi|hello|hey|how|what|where|when|why|can|could|would|should|the|is|are|'
    r'do|does|have|has|yes|no|please|thanks|thank|you|your|need|help|want|looking|'
    r'business|company)\b',
    re.IGNORECASE,
)
_ES_WORDS = re.compile(
    r'\b(hola|como|estas|donde|cuando|porque|puedo|quiero|necesito|gracias|bueno|'
    r'bien|empresa|negocio|ayuda|por favor|tengo|tiene|hacer|estoy)\b',
    re.IGNORECASE,
)
_PT_WORDS = re.compile(
    r'\b(oi|ola|tudo|bem|como|voce|onde|quando|porque|preciso|quero|obrigado|bom|'
    r'empresa|ajuda|por favor|tenho|tem|fazer|estou|nao|sim)\b',
    re.IGNORECASE,
)


def detect_language(text):
    """Detect language via simple heuristics. Returns 'pt', 'en', or 'es'."""
    t = text.lower()
    scores = {
        'en': len(_EN_WORDS.findall(t)),
        'es': len(_ES_WORDS.findall(t)),
        'pt': len(_PT_WORDS.findall(t)),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else 'pt'


# --- Sentiment detection ---

_FRUSTRATED_WORDS = re.compile(
    r'\b(problema|nao funciona|nao consegui|nao consigo|travou|bugou|quebrou|erro|'
    r'irritado|irritada|cansado|cansada|demora|demorou|absurdo|pessimo|horrivel|'
    r'reclamacao|reclamar|insatisfeito|decepcionado|raiva|revoltado|porcaria|'
    r'lixo|merda|droga|cacete|pqp|ridiculo|sem resposta|ninguem responde|'
    r'frustrated|angry|broken|terrible|horrible|worst|hate|furious|'
    r'doesnt work|not working|still waiting|ridiculous)\b',
    re.IGNORECASE,
)
_HAPPY_WORDS = re.compile(
    r'\b(obrigado|obrigada|valeu|top|otimo|otima|perfeito|show|maravilha|'
    r'excelente|incrivel|amei|adorei|gostei|feliz|satisfeito|parabens|'
    r'muito bom|sensacional|massa|demais|genial|legal|bacana|'
    r'thanks|thank you|great|amazing|awesome|perfect|excellent|love it|wonderful|'
    r'happy|glad|appreciate)\b',
    re.IGNORECASE,
)
_CONFUSED_WORDS = re.compile(
    r'\b(nao entendi|como funciona|como faz|nao sei|confuso|confusa|duvida|'
    r'explica|explicar|pode repetir|como assim|que|o que|nao compreendi|'
    r'lost|confused|dont understand|how does|what do you mean|'
    r'can you explain|im not sure|unclear)\b',
    re.IGNORECASE,
)
_URGENT_WORDS = re.compile(
    r'\b(urgente|urgencia|agora|rapido|imediato|emergencia|socorro|'
    r'preciso agora|ja|logo|correndo|pressa|deadline|prazo|'
    r'urgent|asap|emergency|right now|immediately|hurry)\b',
    re.IGNORECASE,
)


def detect_sentiment(text):
    """Detect emotional tone from user message.

    Returns: 'frustrated', 'happy', 'confused', 'urgent', or 'neutral'.
    """
    t = text.lower()
    scores = {
        'frustrated': len(_FRUSTRATED_WORDS.findall(t)) * 2,  # Weight frustration higher
        'happy': len(_HAPPY_WORDS.findall(t)),
        'confused': len(_CONFUSED_WORDS.findall(t)),
        'urgent': len(_URGENT_WORDS.findall(t)),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else 'neutral'


# --- System prompt builder ---

def build_system_prompt(agent_config, conversation, lead=None, language='pt',
                        spoken_mode=False, sentiment='neutral'):
    """Build the full system prompt for a Claude call.

    Combines:
    - agent_config.system_prompt (base prompt from tenant)
    - agent_config.persona (name, role, tone)
    - Conversation context (contact name, history count, stage)
    - Lead info if available
    - Language instruction
    """
    import json as _json
    base = agent_config.get('system_prompt', '')
    persona = agent_config.get('persona', {})
    if isinstance(persona, str):
        try:
            persona = _json.loads(persona) if persona else {}
        except (ValueError, TypeError):
            persona = {}
    contact_name = conversation.get('contact_name', '')
    messages = conversation.get('messages', [])
    stage = conversation.get('stage', 'new')

    # Name handling
    nome = contact_name if is_real_name(contact_name) else ''
    nome_instrucao = ''
    if not nome:
        nome_instrucao = (
            'IMPORTANTE: Voce NAO sabe o nome dessa pessoa. '
            'Pergunte o nome dela de forma natural antes de continuar. '
            'NAO invente nenhum nome, NAO use apelidos do perfil como nome. '
        )

    # Language instruction — strict: always match the user's language
    lang_names = {'pt': 'português brasileiro', 'en': 'English', 'es': 'español'}
    lang_name = lang_names.get(language, 'português brasileiro')
    lang_rule = (
        f'IDIOMA OBRIGATORIO: Responda EXCLUSIVAMENTE em {lang_name}. '
        f'NAO troque de idioma. NAO misture idiomas. '
        f'Se o usuario trocar de idioma, acompanhe o idioma dele.'
    )

    # Brevity, variation, and strategic sales intelligence
    brevity_rule = (
        'REGRA DE OURO: Curto, estrategico e humano. '
        'Maximo 1 a 3 frases por mensagem. Varie SEMPRE. '
        'NUNCA paredes de texto. NUNCA listas. WhatsApp style. '

        'VENDAS CONSULTIVAS: Voce NAO vende. Voce EDUCA e CONQUISTA CONFIANCA. '
        'A venda e consequencia. '
        'Analise as necessidades do cliente e mostre solucoes que ele pode escalar. '
        'Pinte o cenario atual do mercado — empresas que nao se adaptam a essa nova era '
        'corporativa com IA e automacao estao ficando pra tras. '
        'Eduque com dados e exemplos reais: mostre o que os concorrentes estao fazendo, '
        'mostre o potencial de crescimento, mostre o que ele esta perdendo. '

        'GATILHOS: Use gatilhos que tornam a conversa viciante — '
        'curiosidade ("sabe o que as maiores empresas do seu setor estao fazendo agora?"), '
        'escassez ("isso ta mudando rapido"), '
        'prova social ("ja ajudei negocios parecidos com o seu"), '
        'visao de futuro ("imagina seu negocio daqui 6 meses com isso rodando"). '
        'Cada mensagem tem que deixar o cliente querendo saber MAIS. '
        'Faca perguntas inteligentes que mostram que voce entende do negocio dele. '
    )

    # Context block
    total_msgs = len(messages)
    if total_msgs > 1:
        ctx = (
            f'\n\nCONTEXTO: Ja trocaram {total_msgs} msgs. '
            f'{lang_rule} '
            f'{brevity_rule}'
            f'{f"Nome do cliente: {nome}. Chame pelo nome. " if nome else nome_instrucao}'
            f'NAO se apresente de novo. Continue a conversa naturalmente. '
            f'Seja proativo, sugira, pergunte.'
        )
    else:
        persona_name = persona.get('name', 'Oliver')
        ctx = (
            f'\n\nCONTEXTO: Primeiro contato. '
            f'{lang_rule} '
            f'{brevity_rule}'
            f'{f"Nome do cliente: {nome}. " if nome else nome_instrucao}'
            f'Se apresente: {persona_name}. '
            f'Pergunte o ramo do negocio e como pode ajudar. So nesta primeira vez.'
        )

    # Lead context
    lead_ctx = ''
    if lead:
        lead_name = lead.get('name', '')
        lead_company = lead.get('company', '')
        lead_stage = lead.get('stage', '')
        parts = []
        if lead_name:
            parts.append(f'Nome registrado: {lead_name}')
        if lead_company:
            parts.append(f'Empresa: {lead_company}')
        if lead_stage:
            parts.append(f'Estagio no funil: {lead_stage}')
        if parts:
            lead_ctx = f'\n\nDADOS DO LEAD: {". ".join(parts)}.'

    # Stage context
    stage_ctx = ''
    if stage and stage != 'new':
        stage_ctx = f'\n\nESTAGIO DA CONVERSA: {stage}. Adapte seu tom e abordagem.'

    # Spoken mode: optimize text for TTS when response will be audio
    # Implements the OLIVER voice spec — text must be designed for
    # ultra-natural TTS conversion, impossible to identify as AI.
    spoken_ctx = ''
    if spoken_mode:
        emotion_guide = _SENTIMENT_SPEECH_GUIDES.get(sentiment, _SENTIMENT_SPEECH_GUIDES['neutral'])

        spoken_ctx = (
            '\n\nMODO VOZ ATIVO — Sua resposta sera convertida em AUDIO de WhatsApp. '
            'Voce esta GRAVANDO um audio, nao escrevendo um texto.\n\n'

            'PRIORIDADE MAXIMA: A voz precisa soar como um atendente humano real '
            'conversando. NAO como um robo lendo script.\n\n'

            'COMO ESCREVER PRA VOZ:\n'
            '- Frases CURTAS e diretas, como conversa real. Nada de redacao.\n'
            '- Use conectores naturais: "olha", "entao", "beleza", "claro", "perfeito".\n'
            '- Quebre entre ideias pra criar pausas naturais na fala.\n'
            '- Use "..." pra pausas de respiracao, "," pra micro-pausas.\n'
            '- "?" sobe tom no final. "!" da enfase. "." pausa media.\n'
            '- Evite periodos gigantes, listas enormes, muitos numeros grudados.\n'
            '- Se precisar listar passos, faca curto e claro, um de cada vez.\n\n'

            f'TOM EMOCIONAL AGORA: {emotion_guide}\n\n'

            'FORMATO:\n'
            '- Maximo 2 a 3 frases. Audio longo = ruim.\n'
            '- Fale como brasileiro: "a gente", "pra", "ta", "ne", "ce".\n'
            '- Comece com conectivo natural: "Olha...", "Entao...", "Ah,", "Opa!".\n'
            '- TERMINE com pergunta ou convite pra continuar.\n'
            '- ZERO markdown, negrito, listas, emojis, links.\n'
            '- ZERO linguagem corporativa ou formal.\n'
            '- O audio TEM que ser fiel ao texto — nada diferente.'
        )

    return base + ctx + lead_ctx + stage_ctx + spoken_ctx


# --- Sentiment-specific speech guides ---

_SENTIMENT_SPEECH_GUIDES = {
    'frustrated': (
        'O cliente esta FRUSTRADO ou irritado. Voce precisa:\n'
        '- Ser EMPATICO: "Poxa... eu entendo, isso e chato mesmo."\n'
        '- Tom calmo, acolhedor, paciente. Fale devagar (mais virgulas, mais pausas).\n'
        '- Valide o sentimento PRIMEIRO antes de oferecer solucao.\n'
        '- Use: "Olha... eu entendo sua frustracao...", "Poxa, sinto muito por isso...", '
        '"Calma que a gente resolve isso, ta bom?".\n'
        '- NAO seja animado. NAO minimize o problema. NAO diga "sem problemas".'
    ),
    'happy': (
        'O cliente esta FELIZ ou positivo. Voce precisa:\n'
        '- Acompanhar a energia! Seja animado tambem.\n'
        '- Use "!" pra enfase, tom alegre e vibrante.\n'
        '- Use: "Que bom!", "Fico feliz demais!", "Show! Isso ai!", "Que otimo ouvir isso!".\n'
        '- Celebre junto, mas sem exagerar. Mantenha o profissionalismo.'
    ),
    'confused': (
        'O cliente esta CONFUSO ou com duvida. Voce precisa:\n'
        '- Ser PACIENTE e CLARO. Explique de forma simples.\n'
        '- Use pausas pra dar tempo de absorver: "Entao... funciona assim,"\n'
        '- Divida em passos curtos. Uma ideia por frase.\n'
        '- Use: "Olha, e bem simples...", "Calma, vou te explicar...", '
        '"Basicamente, o que acontece e...".\n'
        '- Pergunte se ficou claro no final.'
    ),
    'urgent': (
        'O cliente tem URGENCIA. Voce precisa:\n'
        '- Ser DIRETO e EFICIENTE. Sem enrolacao.\n'
        '- Tom firme e confiante, mostrando que esta no controle.\n'
        '- Use: "Certo, vou resolver isso agora.", "Entendi, ja to vendo isso pra voce.", '
        '"Pode deixar, vou tratar disso agora mesmo.".\n'
        '- Frases curtissimas. Vá direto ao ponto.'
    ),
    'neutral': (
        'Tom neutro, conversacional e amigavel. Voce precisa:\n'
        '- Ser natural, como numa conversa entre conhecidos.\n'
        '- Alternar entre afirmacoes e perguntas pra manter o dialogo vivo.\n'
        '- Use: "Olha...", "Entao...", "Sabe o que e...", "E assim...".\n'
        '- Demonstre interesse genuino. Pergunte, sugira, seja proativo.'
    ),
}
