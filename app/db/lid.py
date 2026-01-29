"""LID (List ID) mapping operations — scoped per WhatsApp account.

Resolves WhatsApp LID JIDs to real phone numbers using multiple strategies.
All mappings are scoped by whatsapp_account_id to prevent cross-tenant leaks.
"""

import logging
from app.db import query, execute, get_pool

log = logging.getLogger('db.lid')


def save_mapping(whatsapp_account_id, lid_jid, phone, resolved_via='', push_name=None):
    """Save a resolved LID -> phone mapping."""
    return execute(
        """INSERT INTO lid_mappings (whatsapp_account_id, lid_jid, phone, resolved_via, push_name)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (lid_jid, whatsapp_account_id)
           DO UPDATE SET phone = EXCLUDED.phone,
                         resolved_via = EXCLUDED.resolved_via,
                         push_name = COALESCE(EXCLUDED.push_name, lid_mappings.push_name)
           RETURNING *""",
        (str(whatsapp_account_id), lid_jid, phone, resolved_via, push_name),
        returning=True,
    )


def get_phone(whatsapp_account_id, lid_jid):
    """Look up a previously resolved phone for a LID."""
    return query(
        """SELECT phone FROM lid_mappings
           WHERE whatsapp_account_id = %s AND lid_jid = %s""",
        (str(whatsapp_account_id), lid_jid),
        fetch='val',
    )


def get_unresolved_lids(whatsapp_account_id=None, limit=100):
    """Get queue items of type pending_lid that haven't been resolved yet."""
    if whatsapp_account_id:
        return query(
            """SELECT * FROM message_queue
               WHERE queue_type = 'pending_lid' AND status = 'pending'
                 AND whatsapp_account_id = %s
               ORDER BY created_at ASC LIMIT %s""",
            (str(whatsapp_account_id), limit),
        )
    return query(
        """SELECT * FROM message_queue
           WHERE queue_type = 'pending_lid' AND status = 'pending'
           ORDER BY created_at ASC LIMIT %s""",
        (limit,),
    )


# --- Evolution DB strategies (read-only access to Evolution schema) ---

def resolve_via_evolution_db_contact(lid_jid):
    """Strategy: Match LID to phone via Evolution's Contact table (profilePicUrl or pushName)."""
    pool = get_pool()
    if not pool:
        return None
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            # Get LID contact's profilePicUrl from Evolution DB
            cur.execute(
                """SELECT "profilePicUrl", "pushName"
                   FROM evolution."Contact"
                   WHERE "remoteJid" = %s
                   LIMIT 1""",
                (lid_jid,),
            )
            lid_row = cur.fetchone()
            if not lid_row:
                return None

            pic_url, push_name = lid_row

            # Strategy A: Match by profilePicUrl
            if pic_url:
                base_pic = pic_url.split('?')[0]
                cur.execute(
                    """SELECT "remoteJid" FROM evolution."Contact"
                       WHERE "remoteJid" LIKE '%%@s.whatsapp.net'
                         AND "profilePicUrl" IS NOT NULL
                         AND split_part("profilePicUrl", '?', 1) = %s
                       LIMIT 1""",
                    (base_pic,),
                )
                match = cur.fetchone()
                if match:
                    return match[0].split('@')[0]

            # Strategy B: Match by pushName (unique only)
            if push_name:
                cur.execute(
                    """SELECT "remoteJid" FROM evolution."Contact"
                       WHERE "remoteJid" LIKE '%%@s.whatsapp.net'
                         AND "pushName" = %s""",
                    (push_name,),
                )
                matches = cur.fetchall()
                if len(matches) == 1:
                    return matches[0][0].split('@')[0]

        return None
    except Exception as e:
        log.debug(f'Evolution DB contact query failed: {e}')
        return None
    finally:
        pool.putconn(conn)


def resolve_via_message_correlation(lid_jid):
    """Strategy: Match LID to phone via message timestamp correlation in Evolution DB."""
    pool = get_pool()
    if not pool:
        return None
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT "messageTimestamp" FROM evolution."Message"
                   WHERE "key"->>'remoteJid' = %s
                   ORDER BY "messageTimestamp" DESC LIMIT 5""",
                (lid_jid,),
            )
            lid_timestamps = [r[0] for r in cur.fetchall()]
            if not lid_timestamps:
                return None

            for ts in lid_timestamps:
                cur.execute(
                    """SELECT "key"->>'remoteJid' AS jid FROM evolution."Message"
                       WHERE "key"->>'remoteJid' LIKE '%%@s.whatsapp.net'
                         AND "messageTimestamp" BETWEEN %s - 2 AND %s + 2
                       LIMIT 5""",
                    (ts, ts),
                )
                candidates = [r[0] for r in cur.fetchall() if r[0]]
                if len(candidates) == 1:
                    return candidates[0].split('@')[0]

        return None
    except Exception as e:
        log.debug(f'Evolution DB message correlation failed: {e}')
        return None
    finally:
        pool.putconn(conn)
