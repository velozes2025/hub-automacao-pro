"""Lead database operations."""

import json
import logging
from app.db import query, execute

log = logging.getLogger('db.leads')


def upsert_lead(tenant_id, phone, name=None, conversation_id=None,
                company=None, stage=None, metadata=None):
    """Create or update a lead. Returns the lead dict."""
    meta_json = json.dumps(metadata) if metadata else '{}'
    return execute(
        """INSERT INTO leads_v2 (tenant_id, phone, name, conversation_id, company, stage, metadata)
           VALUES (%s, %s, %s, %s, %s, COALESCE(%s, 'new'), %s)
           ON CONFLICT (tenant_id, phone)
           DO UPDATE SET
               name = COALESCE(EXCLUDED.name, leads_v2.name),
               conversation_id = COALESCE(EXCLUDED.conversation_id, leads_v2.conversation_id),
               company = COALESCE(EXCLUDED.company, leads_v2.company),
               stage = COALESCE(EXCLUDED.stage, leads_v2.stage),
               updated_at = CURRENT_TIMESTAMP
           RETURNING *""",
        (str(tenant_id), phone, name, str(conversation_id) if conversation_id else None,
         company, stage, meta_json),
        returning=True,
    )


def get_lead(tenant_id, phone):
    return query(
        "SELECT * FROM leads_v2 WHERE tenant_id = %s AND phone = %s",
        (str(tenant_id), phone),
        fetch='one',
    )


def get_lead_by_conversation(conversation_id, tenant_id=None):
    """Get lead linked to a conversation. Enforces tenant isolation when tenant_id provided."""
    if tenant_id:
        return query(
            "SELECT * FROM leads_v2 WHERE conversation_id = %s AND tenant_id = %s",
            (str(conversation_id), str(tenant_id)),
            fetch='one',
        )
    return query(
        "SELECT * FROM leads_v2 WHERE conversation_id = %s",
        (str(conversation_id),),
        fetch='one',
    )


def update_lead_stage(tenant_id, phone, stage):
    return execute(
        """UPDATE leads_v2
           SET stage = %s, updated_at = CURRENT_TIMESTAMP
           WHERE tenant_id = %s AND phone = %s""",
        (stage, str(tenant_id), phone),
    )


def list_leads(tenant_id, stage=None, limit=50, offset=0):
    if stage:
        return query(
            """SELECT l.*, c.contact_name, c.last_message_at
               FROM leads_v2 l
               LEFT JOIN conversations c ON c.id = l.conversation_id
               WHERE l.tenant_id = %s AND l.stage = %s
               ORDER BY l.updated_at DESC
               LIMIT %s OFFSET %s""",
            (str(tenant_id), stage, limit, offset),
        )
    return query(
        """SELECT l.*, c.contact_name, c.last_message_at
           FROM leads_v2 l
           LEFT JOIN conversations c ON c.id = l.conversation_id
           WHERE l.tenant_id = %s
           ORDER BY l.updated_at DESC
           LIMIT %s OFFSET %s""",
        (str(tenant_id), limit, offset),
    )


def count_leads(tenant_id, stage=None):
    if stage:
        return query(
            "SELECT COUNT(*) AS cnt FROM leads_v2 WHERE tenant_id = %s AND stage = %s",
            (str(tenant_id), stage),
            fetch='val',
        )
    return query(
        "SELECT COUNT(*) AS cnt FROM leads_v2 WHERE tenant_id = %s",
        (str(tenant_id),),
        fetch='val',
    )
