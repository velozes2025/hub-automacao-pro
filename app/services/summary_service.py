"""Conversation summary generation and storage.

After every 3 user-assistant exchanges (6 messages), generates a structured
summary using a lightweight Claude call and stores it in conversation_summaries.
Runs in background threads to never block user responses.
"""

import json
import logging

from app.db import summaries as summaries_db
from app.db import consumption as consumption_db
from app.ai.client import call_api, estimate_cost

log = logging.getLogger('services.summary')

SUMMARY_INTERVAL = 6  # messages (3 exchanges = 6 messages: 3 user + 3 assistant)
SUMMARY_MODEL = 'claude-3-5-haiku-20241022'

SUMMARY_PROMPT = (
    'Analise a conversa abaixo e extraia um resumo estruturado em JSON:\n'
    '{\n'
    '  "nome": "nome do cliente ou null",\n'
    '  "telefone": "telefone se mencionado ou null",\n'
    '  "intencao_compra": "alta|media|baixa|nenhuma",\n'
    '  "resumo_dor": "breve descricao do problema/necessidade do cliente",\n'
    '  "produtos_interesse": ["lista de produtos/servicos mencionados"],\n'
    '  "objecoes": ["lista de objecoes levantadas"],\n'
    '  "proximo_passo": "o que foi combinado como proximo passo",\n'
    '  "sentimento_geral": "positivo|neutro|negativo|frustrado"\n'
    '}\n\n'
    'Responda APENAS o JSON, sem explicacao.\n\n'
    'CONVERSA:\n'
)


def should_generate_summary(conversation_id, current_message_count):
    """Check if we should generate a new summary based on message count."""
    if current_message_count < SUMMARY_INTERVAL:
        return False

    last = summaries_db.get_last_summary(conversation_id)
    last_count = last['message_count_at_summary'] if last else 0
    return (current_message_count - last_count) >= SUMMARY_INTERVAL


def generate_summary(conversation_id, tenant_id, messages, api_key=None):
    """Generate and store a conversation summary.

    This is designed to run in a background thread.
    Uses Claude Haiku for minimal cost (~$0.0004 per call).
    """
    if not messages or len(messages) < SUMMARY_INTERVAL:
        return None

    # Build conversation text for summary
    conv_text = ''
    for msg in messages:
        role_label = 'Cliente' if msg.get('role') == 'user' else 'Oliver'
        content = msg.get('content', '')
        if content:
            conv_text += f'{role_label}: {content}\n'

    prompt_text = SUMMARY_PROMPT + conv_text

    try:
        data = call_api(
            model=SUMMARY_MODEL,
            max_tokens=300,
            system_prompt='Voce e um assistente que gera resumos estruturados de conversas em JSON.',
            messages=[{'role': 'user', 'content': prompt_text}],
            api_key=api_key,
        )
        if not data:
            log.warning(f'[SUMMARY] API returned None for {conversation_id}')
            return None

        # Extract text from response blocks
        text = ''
        for block in data.get('content', []):
            if block.get('type') == 'text':
                text += block.get('text', '')

        # Parse JSON (strip markdown code fences if present)
        clean = text.strip()
        if clean.startswith('```'):
            clean = clean.split('\n', 1)[-1].rsplit('```', 1)[0].strip()

        summary_json = json.loads(clean)

        # Save to database
        summaries_db.save_summary(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            summary_json=summary_json,
            message_count=len(messages),
        )

        # Log consumption
        usage = data.get('usage', {})
        input_t = usage.get('input_tokens', 0)
        output_t = usage.get('output_tokens', 0)
        cost = estimate_cost(SUMMARY_MODEL, input_t, output_t)
        try:
            consumption_db.log_usage(
                tenant_id=tenant_id,
                model=SUMMARY_MODEL,
                input_tokens=input_t,
                output_tokens=output_t,
                cost=cost,
                conversation_id=conversation_id,
                operation='summary',
                metadata={'message_count': len(messages)},
            )
        except Exception as e:
            log.error(f'[SUMMARY] Cost logging error: {e}')

        log.info(f'[SUMMARY] Generated for {conversation_id}: '
                 f'{json.dumps(summary_json, ensure_ascii=False)[:100]}')
        return summary_json

    except json.JSONDecodeError:
        log.warning(f'[SUMMARY] Invalid JSON response for {conversation_id}')
        return None
    except Exception as e:
        log.error(f'[SUMMARY] Error generating summary for {conversation_id}: {e}')
        return None
