"""OLIVER.CORE v6.0 — Deterministic State Machine.

LangGraph-style conversation graph with 8 nodes and guard-based transitions.
No LLM calls — all transitions are deterministic via regex + lead data (~0ms).

Nodes:
    ABERTURA → DIAGNOSTICO → EDUCACAO → PROPOSTA → FECHAMENTO → ENCERRADO
    (+ SUPORTE, FINANCEIRO for specialist delegation)
"""

import re
import json
import logging

from app.db import states as states_db

log = logging.getLogger('oliver.state_machine')

# --- Node definitions ---

NODES = {
    'ABERTURA', 'DIAGNOSTICO', 'EDUCACAO', 'PROPOSTA',
    'FECHAMENTO', 'SUPORTE', 'FINANCEIRO', 'ENCERRADO',
}

# Node → compressor phase mapping
NODE_TO_PHASE = {
    'ABERTURA': 'ABER',
    'DIAGNOSTICO': 'DIAG',
    'EDUCACAO': 'EDUC',
    'PROPOSTA': 'PROP',
    'FECHAMENTO': 'FECH',
    'SUPORTE': 'TECH',
    'FINANCEIRO': 'FIN',
    'ENCERRADO': 'FECH',
}

# --- Transition graph ---
# (from_node, to_node) → guard function name
# Each guard returns True if transition is allowed.

_TRANSITIONS = {
    ('ABERTURA', 'DIAGNOSTICO'): '_guard_abertura_to_diag',
    ('ABERTURA', 'SUPORTE'): '_guard_tech_intent',
    ('ABERTURA', 'FINANCEIRO'): '_guard_fin_intent',
    ('DIAGNOSTICO', 'EDUCACAO'): '_guard_diag_to_educ',
    ('DIAGNOSTICO', 'SUPORTE'): '_guard_tech_intent',
    ('DIAGNOSTICO', 'FINANCEIRO'): '_guard_fin_intent',
    ('EDUCACAO', 'PROPOSTA'): '_guard_educ_to_prop',
    ('PROPOSTA', 'FECHAMENTO'): '_guard_fech_intent',
    ('PROPOSTA', 'DIAGNOSTICO'): '_guard_objection_requalify',
    ('FECHAMENTO', 'ENCERRADO'): '_guard_deal_confirmed',
    ('SUPORTE', 'DIAGNOSTICO'): '_guard_specialist_done',
    ('FINANCEIRO', 'DIAGNOSTICO'): '_guard_specialist_done',
}

# --- Guard data extraction patterns ---

_RAMO_PATTERNS = re.compile(
    r'\b(loja|restaurante|clinica|consultorio|escritorio|padaria|academia|'
    r'salao|barbearia|imobiliaria|advocacia|contabilidade|dentista|'
    r'mecanica|oficina|farmacia|pet|veterinaria|escola|creche|'
    r'ecommerce|e-commerce|dropshipping|saas|startup|agencia|'
    r'tecnologia|desenvolvimento|marketing|consultoria|'
    r'alimentacao|saude|educacao|moda|beleza|fitness|servicos|'
    r'construcao|arquitetura|engenharia|transporte|logistica|'
    r'store|shop|clinic|office|restaurant|agency|tech|health)\b',
    re.IGNORECASE,
)

_DOR_PATTERNS = re.compile(
    r'\b(perco|perdendo|demora|demoro|lento|manual|planilha|desorganiz|'
    r'nao consigo|dificuldade|problema|gargalo|atendimento|'
    r'cliente sumiu|cliente some|nao responde|falta|preciso de|'
    r'quero melhorar|quero automatizar|quero crescer|quero escalar|'
    r'lose|losing|slow|manual|disorganized|bottleneck)\b',
    re.IGNORECASE,
)

_INTERESSE_PATTERNS = re.compile(
    r'\b(quero saber mais|me explica|como funciona|quanto custa|'
    r'quanto fica|proposta|orcamento|valores|planos|'
    r'me mostra|demonstra|demonstracao|demo|teste|'
    r'tell me more|how does it work|pricing|proposal)\b',
    re.IGNORECASE,
)

_DEAL_PATTERNS = re.compile(
    r'\b(fechado|fechar|vamos|contrato|assinar|comprar|contratar|'
    r'quando comeca|vamos comecar|fecha|manda o link|pix|'
    r'deal|sign|buy|lets go|start|closed)\b',
    re.IGNORECASE,
)

_RESOLVED_PATTERNS = re.compile(
    r'\b(resolvido|funcionou|consegui|deu certo|obrigado|valeu|'
    r'era isso|pronto|ok|perfeito|resolved|fixed|working|thanks)\b',
    re.IGNORECASE,
)


# --- Guard functions ---

def _guard_abertura_to_diag(state, intent_type, conversation, lead):
    """Transition when we have the client's name and business info."""
    gd = state.get('guard_data', {})
    has_name = bool(gd.get('has_name') or (lead and lead.get('name')))
    has_ramo = bool(gd.get('has_ramo'))

    # Also check from messages if ramo was mentioned
    if not has_ramo:
        messages = conversation.get('messages', [])
        for msg in messages[-4:]:
            if msg.get('role') == 'user' and _RAMO_PATTERNS.search(msg.get('content', '')):
                has_ramo = True
                break

    return has_name and has_ramo


def _guard_tech_intent(state, intent_type, conversation, lead):
    """Transition to SUPORTE on TECH.* intent."""
    return bool(intent_type and intent_type.startswith('TECH'))


def _guard_fin_intent(state, intent_type, conversation, lead):
    """Transition to FINANCEIRO on FIN.* intent."""
    return bool(intent_type and intent_type.startswith('FIN'))


def _guard_diag_to_educ(state, intent_type, conversation, lead):
    """Transition when pain point is identified or enough questions asked."""
    gd = state.get('guard_data', {})
    has_dor = bool(gd.get('has_dor'))
    question_count = gd.get('question_count', 0)

    # Check if dor was mentioned in recent user messages
    if not has_dor:
        messages = conversation.get('messages', [])
        for msg in messages[-6:]:
            if msg.get('role') == 'user' and _DOR_PATTERNS.search(msg.get('content', '')):
                has_dor = True
                break

    return has_dor or question_count >= 3


def _guard_educ_to_prop(state, intent_type, conversation, lead):
    """Transition when client shows explicit interest."""
    # PROP intent from detector
    if intent_type == 'PROP':
        return True

    # Check recent messages for interest signals
    messages = conversation.get('messages', [])
    for msg in messages[-4:]:
        if msg.get('role') == 'user' and _INTERESSE_PATTERNS.search(msg.get('content', '')):
            return True
    return False


def _guard_fech_intent(state, intent_type, conversation, lead):
    """Transition on FECH intent (closing signals)."""
    return intent_type == 'FECH'


def _guard_objection_requalify(state, intent_type, conversation, lead):
    """Transition back to DIAGNOSTICO on objection (OBJ.*)."""
    return bool(intent_type and intent_type.startswith('OBJ'))


def _guard_deal_confirmed(state, intent_type, conversation, lead):
    """Transition to ENCERRADO when deal is confirmed."""
    messages = conversation.get('messages', [])
    for msg in messages[-4:]:
        if msg.get('role') == 'user' and _DEAL_PATTERNS.search(msg.get('content', '')):
            return True
    return False


def _guard_specialist_done(state, intent_type, conversation, lead):
    """Transition back from specialist mode when issue resolved."""
    messages = conversation.get('messages', [])
    for msg in messages[-4:]:
        if msg.get('role') == 'user' and _RESOLVED_PATTERNS.search(msg.get('content', '')):
            return True
    return False


# Guard function lookup
_GUARD_FUNCS = {
    '_guard_abertura_to_diag': _guard_abertura_to_diag,
    '_guard_tech_intent': _guard_tech_intent,
    '_guard_fin_intent': _guard_fin_intent,
    '_guard_diag_to_educ': _guard_diag_to_educ,
    '_guard_educ_to_prop': _guard_educ_to_prop,
    '_guard_fech_intent': _guard_fech_intent,
    '_guard_objection_requalify': _guard_objection_requalify,
    '_guard_deal_confirmed': _guard_deal_confirmed,
    '_guard_specialist_done': _guard_specialist_done,
}


# --- Public API ---

def get_or_create_state(conversation_id, tenant_id):
    """Get or create conversation state from DB."""
    try:
        state = states_db.get_or_create_state(conversation_id, tenant_id)
        if state:
            gd = state.get('guard_data', {})
            if isinstance(gd, str):
                try:
                    state['guard_data'] = json.loads(gd)
                except (ValueError, TypeError):
                    state['guard_data'] = {}
        return state
    except Exception as e:
        log.error(f'[STATE] Failed to get/create state: {e}')
        return {
            'conversation_id': conversation_id,
            'tenant_id': tenant_id,
            'current_node': 'ABERTURA',
            'previous_node': None,
            'active_agent': 'oliver',
            'guard_data': {},
            'transition_count': 0,
        }


def evaluate_transition(state, intent_type, conversation):
    """Evaluate all possible transitions from current node.

    Returns updated state (possibly with new node if transition occurred).
    Deterministic — no LLM call.
    """
    current = state.get('current_node', 'ABERTURA')
    lead = conversation.get('lead')

    # Find valid transitions from current node (order matters — first match wins)
    for (from_node, to_node), guard_name in _TRANSITIONS.items():
        if from_node != current:
            continue

        guard_fn = _GUARD_FUNCS.get(guard_name)
        if not guard_fn:
            continue

        try:
            if guard_fn(state, intent_type, conversation, lead):
                log.info(f'[STATE] Transition: {current} -> {to_node} '
                         f'(guard={guard_name}, intent={intent_type})')

                # Determine agent for new node
                agent = _node_to_agent(to_node)

                # Persist transition
                conversation_id = state.get('conversation_id', '')
                tenant_id = state.get('tenant_id', '')
                guard_data = state.get('guard_data', {})
                if conversation_id and tenant_id:
                    try:
                        states_db.transition(
                            conversation_id, tenant_id, to_node,
                            new_agent=agent, guard_data=guard_data,
                        )
                    except Exception as e:
                        log.error(f'[STATE] Failed to persist transition: {e}')

                # Update in-memory state
                state['previous_node'] = current
                state['current_node'] = to_node
                state['active_agent'] = agent
                state['transition_count'] = state.get('transition_count', 0) + 1
                return state
        except Exception as e:
            log.error(f'[STATE] Guard {guard_name} error: {e}')
            continue

    return state


def update_guards(state, ai_response, lead, facts):
    """Update guard_data based on AI response, lead info, and facts.

    Called after AI responds — updates guards for next transition evaluation.
    """
    conversation_id = state.get('conversation_id', '')
    tenant_id = state.get('tenant_id', '')
    gd = dict(state.get('guard_data', {}))

    # Track if we have name
    if lead and lead.get('name'):
        gd['has_name'] = True
    if facts and facts.get('nome'):
        gd['has_name'] = True

    # Track if we have ramo
    if facts and facts.get('ramo'):
        gd['has_ramo'] = True
    if lead:
        meta = lead.get('metadata', {})
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (ValueError, TypeError):
                meta = {}
        if meta.get('setor'):
            gd['has_ramo'] = True

    # Track if dor was identified
    if facts and facts.get('dor_principal'):
        gd['has_dor'] = True
    if lead:
        meta = lead.get('metadata', {})
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (ValueError, TypeError):
                meta = {}
        if meta.get('dor'):
            gd['has_dor'] = True

    # Count assistant questions (approximate — count '?' in AI response)
    if ai_response and '?' in ai_response:
        gd['question_count'] = gd.get('question_count', 0) + 1

    # Persist if changed
    if gd != state.get('guard_data', {}):
        state['guard_data'] = gd
        if conversation_id and tenant_id:
            try:
                states_db.update_state(
                    conversation_id, tenant_id, guard_data=gd,
                )
            except Exception as e:
                log.error(f'[STATE] Failed to update guards: {e}')


def get_phase_for_node(node):
    """Map state machine node to compressor phase."""
    return NODE_TO_PHASE.get(node, 'DIAG')


def _node_to_agent(node):
    """Map node to agent ID."""
    if node == 'SUPORTE':
        return 'tech_agent'
    if node == 'FINANCEIRO':
        return 'fin_agent'
    return 'oliver'
