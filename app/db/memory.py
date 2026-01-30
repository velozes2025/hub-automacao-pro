"""Client memory persistence for OLIVER.CORE v6.0.

Key-value facts per lead, extracted from conversations.
"""

import json
import logging
from app.db import query, execute

log = logging.getLogger('db.memory')


def get_facts(lead_id):
    """Get all facts for a lead as a dict {key: value}.

    Fast path (~5ms) — called synchronously in the hot path.
    """
    rows = query(
        """SELECT fact_key, fact_value FROM client_memory
           WHERE lead_id = %s
           ORDER BY updated_at DESC""",
        (str(lead_id),),
    )
    return {row['fact_key']: row['fact_value'] for row in rows}


def get_facts_with_meta(lead_id):
    """Get all facts with metadata (source, confidence, timestamps)."""
    return query(
        """SELECT fact_key, fact_value, source, confidence, created_at, updated_at
           FROM client_memory
           WHERE lead_id = %s
           ORDER BY updated_at DESC""",
        (str(lead_id),),
    )


def upsert_fact(lead_id, tenant_id, key, value, source='extraction',
                confidence=0.8):
    """Insert or update a single fact."""
    return execute(
        """INSERT INTO client_memory
           (lead_id, tenant_id, fact_key, fact_value, source, confidence)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (lead_id, fact_key)
           DO UPDATE SET
               fact_value = EXCLUDED.fact_value,
               source = EXCLUDED.source,
               confidence = EXCLUDED.confidence,
               updated_at = CURRENT_TIMESTAMP
           RETURNING *""",
        (str(lead_id), str(tenant_id), key, value, source, confidence),
        returning=True,
    )


def upsert_facts_batch(lead_id, tenant_id, facts_dict, source='extraction',
                       confidence=0.8):
    """Upsert multiple facts at once.

    Args:
        facts_dict: dict of {fact_key: fact_value}
    """
    if not facts_dict:
        return

    for key, value in facts_dict.items():
        if value and str(value).strip():
            try:
                upsert_fact(lead_id, tenant_id, key, str(value).strip(),
                           source, confidence)
            except Exception as e:
                log.error(f'[MEMORY] Failed to upsert fact {key}: {e}')


def delete_fact(lead_id, key):
    """Delete a single fact."""
    execute(
        "DELETE FROM client_memory WHERE lead_id = %s AND fact_key = %s",
        (str(lead_id), key),
    )


def get_facts_for_tenant(tenant_id, limit=100):
    """Get all facts for a tenant (admin/debug use)."""
    return query(
        """SELECT cm.*, l.phone, l.name as lead_name
           FROM client_memory cm
           JOIN leads_v2 l ON l.id = cm.lead_id
           WHERE cm.tenant_id = %s
           ORDER BY cm.updated_at DESC
           LIMIT %s""",
        (str(tenant_id), limit),
    )
