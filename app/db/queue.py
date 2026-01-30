"""Message queue operations — unified retry, pending LID, and scheduled messages."""

import json
import logging
from app.db import query, execute

log = logging.getLogger('db.queue')


def enqueue(tenant_id, whatsapp_account_id, phone, content,
            queue_type='failed', metadata=None, max_attempts=5):
    """Add a message to the queue."""
    meta_json = json.dumps(metadata) if metadata else '{}'
    return execute(
        """INSERT INTO message_queue
           (tenant_id, whatsapp_account_id, phone, content, queue_type, metadata, max_attempts)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           RETURNING *""",
        (str(tenant_id), str(whatsapp_account_id), phone, content,
         queue_type, meta_json, max_attempts),
        returning=True,
    )


def get_pending(queue_type='failed', limit=50, tenant_id=None):
    """Get pending messages ready for retry, scoped by tenant for isolation."""
    base = """SELECT mq.*, wa.instance_name, t.anthropic_api_key AS tenant_api_key
           FROM message_queue mq
           JOIN whatsapp_accounts wa ON wa.id = mq.whatsapp_account_id
           JOIN tenants t ON t.id = mq.tenant_id
           WHERE mq.status = 'pending'
             AND mq.queue_type = %s
             AND mq.attempts < mq.max_attempts
             AND mq.next_attempt_at <= CURRENT_TIMESTAMP"""
    params = [queue_type]

    if tenant_id:
        base += " AND mq.tenant_id = %s"
        params.append(str(tenant_id))

    base += " ORDER BY mq.created_at ASC LIMIT %s"
    params.append(limit)

    return query(base, tuple(params))


def mark_delivered(queue_id, tenant_id=None):
    if tenant_id:
        return execute(
            """UPDATE message_queue
               SET status = 'delivered', updated_at = CURRENT_TIMESTAMP
               WHERE id = %s AND tenant_id = %s""",
            (queue_id, str(tenant_id)),
        )
    return execute(
        """UPDATE message_queue
           SET status = 'delivered', updated_at = CURRENT_TIMESTAMP
           WHERE id = %s""",
        (queue_id,),
    )


def increment_attempt(queue_id, error=None):
    """Increment attempt count and set next retry time (exponential backoff)."""
    meta_update = ''
    params = [queue_id]
    if error:
        meta_update = ", metadata = jsonb_set(metadata, '{last_error}', %s::jsonb)"
        params = [json.dumps(error), queue_id]

    return execute(
        f"""UPDATE message_queue
           SET attempts = attempts + 1,
               next_attempt_at = CURRENT_TIMESTAMP + make_interval(secs => POWER(2, attempts) * 30),
               updated_at = CURRENT_TIMESTAMP
               {meta_update}
           WHERE id = %s""",
        tuple(params),
    )


def expire_old(max_age_hours=24):
    """Mark old undelivered messages as expired."""
    return execute(
        """UPDATE message_queue
           SET status = 'expired', updated_at = CURRENT_TIMESTAMP
           WHERE status = 'pending'
             AND created_at < CURRENT_TIMESTAMP - make_interval(hours => %s)""",
        (max_age_hours,),
    )


def get_queue_stats(tenant_id=None):
    """Get queue statistics, optionally filtered by tenant."""
    if tenant_id:
        return query(
            """SELECT queue_type, status, COUNT(*) AS cnt
               FROM message_queue
               WHERE tenant_id = %s
               GROUP BY queue_type, status
               ORDER BY queue_type, status""",
            (str(tenant_id),),
        )
    return query(
        """SELECT queue_type, status, COUNT(*) AS cnt
           FROM message_queue
           GROUP BY queue_type, status
           ORDER BY queue_type, status""",
    )
