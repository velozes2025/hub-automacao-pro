"""Conversation and Message database operations.

The `conversations` table is the core entity that solves the name-confusion bug.
Each conversation is unique per (whatsapp_account_id, contact_phone).
"""

import logging
from app.db import query, execute

log = logging.getLogger('db.conversations')


def get_or_create_conversation(tenant_id, whatsapp_account_id, contact_phone,
                                contact_name=None):
    """Get existing conversation or create a new one.

    If conversation exists but contact_name changed, update it.
    Returns conversation dict.
    """
    conv = query(
        """SELECT * FROM conversations
           WHERE whatsapp_account_id = %s AND contact_phone = %s""",
        (str(whatsapp_account_id), contact_phone),
        fetch='one',
    )

    if conv:
        # Update name if it changed and new name is non-empty
        if contact_name and contact_name != conv.get('contact_name'):
            execute(
                """UPDATE conversations
                   SET contact_name = %s, updated_at = CURRENT_TIMESTAMP
                   WHERE id = %s""",
                (contact_name, str(conv['id'])),
            )
            conv['contact_name'] = contact_name
        # Touch last_message_at
        execute(
            """UPDATE conversations
               SET last_message_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
               WHERE id = %s""",
            (str(conv['id']),),
        )
        return conv

    return execute(
        """INSERT INTO conversations
           (tenant_id, whatsapp_account_id, contact_phone, contact_name)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (whatsapp_account_id, contact_phone)
           DO UPDATE SET
               contact_name = COALESCE(EXCLUDED.contact_name, conversations.contact_name),
               last_message_at = CURRENT_TIMESTAMP,
               updated_at = CURRENT_TIMESTAMP
           RETURNING *""",
        (str(tenant_id), str(whatsapp_account_id), contact_phone, contact_name),
        returning=True,
    )


def get_conversation(conversation_id):
    return query(
        "SELECT * FROM conversations WHERE id = %s",
        (str(conversation_id),),
        fetch='one',
    )


def update_conversation(conversation_id, **fields):
    sets = []
    vals = []
    for k, v in fields.items():
        sets.append(f"{k} = %s")
        vals.append(v)
    sets.append("updated_at = CURRENT_TIMESTAMP")
    vals.append(str(conversation_id))
    return execute(
        f"UPDATE conversations SET {', '.join(sets)} WHERE id = %s",
        tuple(vals),
    )


def save_message(conversation_id, role, content, metadata=None):
    """Save a message and return it."""
    import json
    meta_json = json.dumps(metadata) if metadata else '{}'
    return execute(
        """INSERT INTO messages (conversation_id, role, content, metadata)
           VALUES (%s, %s, %s, %s)
           RETURNING *""",
        (str(conversation_id), role, content, meta_json),
        returning=True,
    )


def get_message_history(conversation_id, limit=10):
    """Get the last N messages for a conversation, ordered oldest-first."""
    rows = query(
        """SELECT role, content, metadata, created_at FROM messages
           WHERE conversation_id = %s
           ORDER BY created_at DESC
           LIMIT %s""",
        (str(conversation_id), limit),
    )
    rows.reverse()
    return rows


def get_conversation_with_context(conversation_id):
    """Get conversation + lead + recent messages in one call."""
    conv = get_conversation(conversation_id)
    if not conv:
        return None
    conv['messages'] = get_message_history(conversation_id)
    # Attach lead if exists
    lead = query(
        "SELECT * FROM leads_v2 WHERE conversation_id = %s",
        (str(conversation_id),),
        fetch='one',
    )
    conv['lead'] = lead
    return conv


def list_conversations(tenant_id, limit=50, offset=0):
    return query(
        """SELECT c.*, wa.instance_name
           FROM conversations c
           JOIN whatsapp_accounts wa ON wa.id = c.whatsapp_account_id
           WHERE c.tenant_id = %s
           ORDER BY c.last_message_at DESC
           LIMIT %s OFFSET %s""",
        (str(tenant_id), limit, offset),
    )


def get_stale_conversations(tenant_id, stale_minutes=25, max_reengagement=2):
    """Find conversations where the client messaged but bot hasn't replied within N minutes."""
    return query(
        """SELECT c.*, wa.instance_name
           FROM conversations c
           JOIN whatsapp_accounts wa ON wa.id = c.whatsapp_account_id
           LEFT JOIN LATERAL (
               SELECT role, created_at FROM messages
               WHERE conversation_id = c.id
               ORDER BY created_at DESC LIMIT 1
           ) last_msg ON TRUE
           WHERE c.tenant_id = %s
             AND c.stage != 'closed'
             AND last_msg.role = 'user'
             AND last_msg.created_at < CURRENT_TIMESTAMP - make_interval(mins => %s)
             AND (c.metadata->>'reengagement_count')::int < %s
        """,
        (str(tenant_id), stale_minutes, max_reengagement),
    )


def increment_reengagement(conversation_id):
    execute(
        """UPDATE conversations
           SET metadata = jsonb_set(
               COALESCE(metadata, '{}'),
               '{reengagement_count}',
               to_jsonb(COALESCE((metadata->>'reengagement_count')::int, 0) + 1)
           ),
           updated_at = CURRENT_TIMESTAMP
           WHERE id = %s""",
        (str(conversation_id),),
    )


def reset_reengagement(conversation_id):
    execute(
        """UPDATE conversations
           SET metadata = jsonb_set(
               COALESCE(metadata, '{}'),
               '{reengagement_count}',
               '0'::jsonb
           ),
           updated_at = CURRENT_TIMESTAMP
           WHERE id = %s""",
        (str(conversation_id),),
    )
