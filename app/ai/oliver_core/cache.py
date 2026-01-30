"""Global response cache for OLIVER.CORE v5.2.

Pre-defined responses for predictable intents. Cache hit = 0 LLM tokens.
Supports {nome} substitution and multi-language variants.

v5.2: Added ABER.retorno (not cached — requires memory context, always LLM),
      added OBJ.depois entries.
"""

import random
import logging

log = logging.getLogger('oliver.cache')

# --- Global cache: (intent_key, language) -> response(s) ---
# Responses can be a string or a list (randomly selected for variation).
#
# NOTE: ABER.retorno is intentionally NOT cached because returning clients
# need personalized context from conversation history (memory).

_GLOBAL_CACHE = {
    # --- ABERTURA (new clients only — returning clients go to LLM) ---
    ('ABER.sem_nome', 'pt'): [
        'Oi! Sou o Oliver, da QuantrexNow. Com quem eu falo?',
        'Oi! Aqui e o Oliver, da QuantrexNow. Como posso te chamar?',
    ],
    ('ABER.com_nome', 'pt'): [
        'Oi {nome}! Sou o Oliver, da QuantrexNow. Me conta, o que te trouxe aqui?',
        'Prazer, {nome}! Sou o Oliver, da QuantrexNow. Qual o ramo do seu negocio?',
    ],

    # --- OBJECOES ---
    ('OBJ.preco', 'pt'): [
        'Entendo. Caro comparado a que? O que importa e o retorno que isso traz pro seu negocio.',
        'Faz sentido essa preocupacao. Me diz: quanto voce acha que perde por mes sem resolver isso?',
    ],
    ('OBJ.tempo', 'pt'): [
        'Justamente por nao ter tempo que faz sentido automatizar. Quando seria melhor pra gente conversar?',
        'Entendo. E se eu te mostrar que da pra comecar com algo simples, sem atrapalhar sua rotina?',
    ],
    ('OBJ.pensar', 'pt'): [
        'Claro, faz total sentido. Tem alguma duvida especifica que eu possa esclarecer?',
        'Claro, sem pressa. Me diz so: ficou alguma duvida que eu possa ajudar?',
    ],
    ('OBJ.socio', 'pt'): [
        'Otimo! Quer que eu prepare um resumo pra voce levar pra essa conversa?',
        'Faz sentido. Quer que eu participe de uma conversa com voces dois?',
    ],
    ('OBJ.tentou', 'pt'): [
        'Puxa, isso e frustrante. O que aconteceu?',
        'Puxa. Me conta o que deu errado? Assim eu entendo o cenario.',
    ],
    ('OBJ.depois', 'pt'): [
        'Tranquilo, sem pressao nenhuma. Posso te mandar um material pra olhar com calma?',
        'Sem problema. Quer que eu te mande algo pra voce ver quando tiver um tempinho?',
    ],

    # --- FECHAMENTO ---
    ('FECH', 'pt'): [
        'Show! Qual seria o proximo passo ideal pra voce?',
        'Otimo! Faz sentido a gente agendar uma conversa rapida pra alinhar os detalhes?',
    ],

    # --- ENGLISH ---
    ('ABER.sem_nome', 'en'): [
        "Hi! I'm Oliver from QuantrexNow. Who am I speaking with?",
    ],
    ('ABER.com_nome', 'en'): [
        "Hi {nome}! I'm Oliver from QuantrexNow. What brings you here?",
    ],
    ('OBJ.preco', 'en'): [
        "I understand. Expensive compared to what? What matters is the return it brings to your business.",
    ],
    ('OBJ.tempo', 'en'): [
        "That's exactly why automation makes sense. When would be better for us to chat?",
    ],
    ('OBJ.pensar', 'en'): [
        "Of course, makes total sense. Any specific question I can clarify to help with that decision?",
    ],
    ('OBJ.depois', 'en'): [
        "No pressure at all. Want me to send you some material to look at when you have a moment?",
    ],
    ('FECH', 'en'): [
        "Great! What would be the ideal next step for you?",
    ],

    # --- SPANISH ---
    ('ABER.sem_nome', 'es'): [
        'Hola! Soy Oliver de QuantrexNow. Con quien hablo?',
    ],
    ('ABER.com_nome', 'es'): [
        'Hola {nome}! Soy Oliver de QuantrexNow. Que te trajo por aqui?',
    ],
    ('OBJ.preco', 'es'): [
        'Entiendo. Caro comparado a que? Lo que importa es el retorno para tu negocio.',
    ],
    ('OBJ.depois', 'es'): [
        'Tranquilo, sin presion. Quieres que te mande material para verlo con calma?',
    ],
    ('FECH', 'es'): [
        'Genial! Cual seria el proximo paso ideal para ti?',
    ],
}


def try_cache(phase, intent_type, lead, language='pt'):
    """Look up a cached response for this intent.

    Args:
        phase: detected phase (ABER, OBJ, FECH, etc.)
        intent_type: specific type (OBJ.preco, ABER.com_nome, etc.) or None
        lead: lead dict or None
        language: 'pt', 'en', or 'es'

    Returns:
        str or None: cached response with variables substituted, or None on miss.
    """
    # Resolve cache key
    key = intent_type or phase

    # For opening: resolve com/sem nome
    if key == 'ABER':
        has_name = lead and lead.get('name')
        key = 'ABER.com_nome' if has_name else 'ABER.sem_nome'

    # ABER.retorno is never cached — needs personalized memory context from LLM
    if key == 'ABER.retorno':
        log.debug('Cache SKIP: ABER.retorno requires LLM for memory context')
        return None

    entry = _GLOBAL_CACHE.get((key, language))
    if entry is None:
        # Try Portuguese fallback for unsupported languages
        if language != 'pt':
            entry = _GLOBAL_CACHE.get((key, 'pt'))
        if entry is None:
            return None

    # Pick response (random if list for variation)
    if isinstance(entry, list):
        response = random.choice(entry)
    else:
        response = entry

    # Variable substitution
    nome = (lead.get('name', '') if lead else '') or ''
    empresa = (lead.get('company', '') if lead else '') or ''
    response = response.replace('{nome}', nome).replace('{empresa}', empresa)

    log.info(f'Cache HIT: ({key}, {language}) -> "{response[:60]}..."')
    return response
