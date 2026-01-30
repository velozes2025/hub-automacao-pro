"""LID (List ID) mapping operations — scoped per WhatsApp account.

Resolves WhatsApp LID JIDs to real phone numbers using multiple strategies.
All mappings are scoped by whatsapp_account_id to prevent cross-tenant leaks.

Source priority prevents low-confidence strategies (msg correlation)
from overwriting high-confidence ones (manual, contacts event, profilePic).
"""

import logging
from app.db import query, execute, get_pool

log = logging.getLogger('db.lid')

# Higher number = more trustworthy source
_SOURCE_PRIORITY = {
    'manual': 100,
    'contacts event': 90,
    'sent profilePic': 80,
    'profilePic API': 70,
    'pushName API': 60,
    'sent pushName': 50,
    'Evolution DB Contact': 40,
    'msg correlation': 10,
}


def get_phone_with_source(whatsapp_account_id, lid_jid):
    """Look up a previously resolved phone + source for a LID."""
    row = query(
        """SELECT phone, resolved_via FROM lid_mappings
           WHERE whatsapp_account_id = %s AND lid_jid = %s""",
        (str(whatsapp_account_id), lid_jid),
        fetch='one',
    )
    if row:
        return row.get('phone') if isinstance(row, dict) else row[0], \
               row.get('resolved_via', '') if isinstance(row, dict) else (row[1] if len(row) > 1 else '')
    return None, None


def save_mapping(whatsapp_account_id, lid_jid, phone, resolved_via='', push_name=None):
    """Save a resolved LID -> phone mapping.

    Respects source priority: low-confidence sources (msg correlation)
    cannot overwrite high-confidence ones (manual, contacts event).
    Returns the mapping row on success, None if blocked by priority.
    """
    new_priority = _SOURCE_PRIORITY.get(resolved_via, 0)

    existing_phone, existing_source = get_phone_with_source(whatsapp_account_id, lid_jid)
    if existing_source:
        existing_priority = _SOURCE_PRIORITY.get(existing_source, 0)
        if new_priority < existing_priority:
            log.info(
                f'LID save BLOCKED: {resolved_via} (pri={new_priority}) '
                f'cannot overwrite {existing_source} (pri={existing_priority}) '
                f'for {lid_jid} (existing={existing_phone}, proposed={phone})'
            )
            return None

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
    """Strategy: Match LID to phone via message timestamp correlation in Evolution DB.

    STRICT matching to avoid false positives:
    - Requires at least 3 timestamps to attempt correlation
    - Phone must appear in majority of timestamp windows (3+ of 5)
    - Candidate phone must not already be mapped to a different LID
      via a high-confidence source
    """
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
            if len(lid_timestamps) < 3:
                return None

            # Collect candidate phones across ALL timestamps
            phone_counts = {}
            for ts in lid_timestamps:
                cur.execute(
                    """SELECT DISTINCT "key"->>'remoteJid' AS jid
                       FROM evolution."Message"
                       WHERE "key"->>'remoteJid' LIKE '%%@s.whatsapp.net'
                         AND "messageTimestamp" BETWEEN %s - 2 AND %s + 2
                       LIMIT 10""",
                    (ts, ts),
                )
                for r in cur.fetchall():
                    if r[0]:
                        phone = r[0].split('@')[0]
                        phone_counts[phone] = phone_counts.get(phone, 0) + 1

            if not phone_counts:
                return None

            # Require majority consensus: 3+ out of checked timestamps
            min_matches = max(3, len(lid_timestamps) // 2 + 1)
            best_phone = None
            best_count = 0
            for phone, count in phone_counts.items():
                if count >= min_matches and count > best_count:
                    best_phone = phone
                    best_count = count

            if not best_phone:
                return None

            # Safety: candidate must not already be mapped to a DIFFERENT LID
            # via a reliable source (anything except msg correlation itself)
            existing_lid = query(
                """SELECT lid_jid FROM lid_mappings
                   WHERE phone = %s AND lid_jid != %s
                   AND resolved_via NOT IN ('msg correlation')""",
                (best_phone, lid_jid),
                fetch='val',
            )
            if existing_lid:
                log.warning(
                    f'msg correlation BLOCKED: {best_phone} already mapped to '
                    f'{existing_lid} via reliable source (not {lid_jid})'
                )
                return None

            return best_phone

    except Exception as e:
        log.debug(f'Evolution DB message correlation failed: {e}')
        return None
    finally:
        pool.putconn(conn)
