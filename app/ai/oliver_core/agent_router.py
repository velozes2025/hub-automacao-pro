"""OLIVER.CORE v6.0 — Agent Router with Invisible Handoff.

Routes conversations to specialized agents based on state machine node.
The lead never knows the agent changed — Oliver is always Oliver.

Agents:
    oliver      - Default sales consultant (vendas consultivas)
    tech_agent  - Technical support specialist
    fin_agent   - Financial/billing specialist
"""

import logging

log = logging.getLogger('oliver.agent_router')

# --- Agent Registry ---

AGENT_REGISTRY = {
    'oliver': {
        'name': 'Oliver',
        'specialty': 'vendas consultivas',
        'prompt_modifier': '',
    },
    'tech_agent': {
        'name': 'Oliver (Suporte)',
        'specialty': 'suporte tecnico',
        'prompt_modifier': (
            'MODO ESPECIALISTA TECNICO ativado. '
            'Voce agora atua como especialista tecnico, mas continua sendo Oliver. '
            'Diagnosticar problema passo a passo: '
            '1.Entender o que aconteceu 2.Pedir detalhes (versao/navegador/prints) '
            '3.Tentar resolver (reiniciar/cache/config) '
            '4.Se complexo: "Vou escalar pro time tecnico com todas as infos". '
            'Ser paciente e didatico. Nao apressar diagnostico.'
        ),
    },
    'fin_agent': {
        'name': 'Oliver (Financeiro)',
        'specialty': 'financeiro',
        'prompt_modifier': (
            'MODO FINANCEIRO ativado. '
            'Voce agora trata assuntos financeiros, mas continua sendo Oliver. '
            'Ser claro e transparente com valores. Explicar beneficios de cada plano. '
            'Se duvida de cobranca: "Deixa eu verificar sua situacao" > resolver ou escalar. '
            'Focar em valor entregue, nao apenas preco. Sem pressao.'
        ),
    },
}

# Node → agent mapping
_NODE_AGENT_MAP = {
    'SUPORTE': 'tech_agent',
    'FINANCEIRO': 'fin_agent',
}


def resolve_agent(state, intent_type=None):
    """Resolve which agent should handle this conversation.

    Uses sticky assignment: once an agent is assigned via state machine,
    it stays until the state transitions to a different node.

    Args:
        state: conversation_states dict (with current_node, active_agent)
        intent_type: detected intent (for override in edge cases)

    Returns:
        str: agent ID from AGENT_REGISTRY
    """
    current_node = state.get('current_node', 'ABERTURA')

    # Node-based routing (primary)
    agent_id = _NODE_AGENT_MAP.get(current_node, 'oliver')

    # Log handoff if agent changed
    previous_agent = state.get('active_agent', 'oliver')
    if agent_id != previous_agent:
        log.info(f'[HANDOFF] {previous_agent} -> {agent_id} '
                 f'(node={current_node}, intent={intent_type})')

    return agent_id


def get_prompt_modifier(agent_id):
    """Get the prompt modifier for an agent.

    Returns empty string for default oliver agent.
    """
    agent = AGENT_REGISTRY.get(agent_id)
    if not agent:
        log.warning(f'[AGENT] Unknown agent: {agent_id}, falling back to oliver')
        return ''
    return agent.get('prompt_modifier', '')


def get_agent_info(agent_id):
    """Get full agent info dict."""
    return AGENT_REGISTRY.get(agent_id, AGENT_REGISTRY['oliver'])


def list_agents():
    """List all registered agents."""
    return list(AGENT_REGISTRY.keys())
