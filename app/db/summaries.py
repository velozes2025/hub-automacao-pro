"""Database operations for conversation_summaries table."""

import json
import logging
from app.db import query, execute

log = logging.getLogger('db.summaries')


def get_last_summary(conversation_id):
    """Get the most recent summary for a conversation."""
    return query(
        """SELECT id, tenant_id, conversation_id, summary_json,
                  message_count_at_summary, created_at
           FROM conversation_summaries
           WHERE conversation_id = %s
           ORDER BY created_at DESC LIMIT 1""",
        (str(conversation_id),),
        fetch='one',
    )


def save_summary(tenant_id, conversation_id, summary_json, message_count):
    """Save a new conversation summary."""
    execute(
        """INSERT INTO conversation_summaries
           (tenant_id, conversation_id, summary_json, message_count_at_summary)
           VALUES (%s, %s, %s, %s)""",
        (str(tenant_id), str(conversation_id),
         json.dumps(summary_json, ensure_ascii=False), message_count),
    )
    log.info(f'[SUMMARY] Saved for conversation {conversation_id} (msgs={message_count})')


def list_summaries(tenant_id, conversation_id=None, limit=20):
    """List summaries, optionally filtered by conversation."""
    if conversation_id:
        return query(
            """SELECT id, conversation_id, summary_json, message_count_at_summary, created_at
               FROM conversation_summaries
               WHERE tenant_id = %s AND conversation_id = %s
               ORDER BY created_at DESC LIMIT %s""",
            (str(tenant_id), str(conversation_id), limit),
            fetch='all',
        )
    return query(
        """SELECT id, conversation_id, summary_json, message_count_at_summary, created_at
           FROM conversation_summaries
           WHERE tenant_id = %s
           ORDER BY created_at DESC LIMIT %s""",
        (str(tenant_id), limit),
        fetch='all',
    )
