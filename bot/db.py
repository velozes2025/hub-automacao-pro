import psycopg2
import psycopg2.pool
import psycopg2.extras
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

_pool = None


def init_pool():
    global _pool
    _pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=2, maxconn=10,
        host=DB_HOST, port=DB_PORT,
        dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD
    )


def _query(sql, params=None, fetch=True):
    conn = _pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if fetch:
                return cur.fetchall()
            conn.commit()
            return None
    finally:
        _pool.putconn(conn)


def get_empresa_by_instance(instance_name):
    rows = _query(
        """SELECT id, nome, whatsapp_instance, status, system_prompt, model,
                  max_tokens, greeting_message, persona_name,
                  business_hours_start, business_hours_end,
                  outside_hours_message, typing_delay_ms,
                  max_history_messages
           FROM empresas
           WHERE whatsapp_instance = %s AND status = 'ativo'
           LIMIT 1""",
        (instance_name,)
    )
    return dict(rows[0]) if rows else None


def get_conversation_history(empresa_id, phone, limit):
    rows = _query(
        """SELECT role, content FROM (
               SELECT role, content, created_at
               FROM conversas
               WHERE empresa_id = %s AND phone = %s
               ORDER BY created_at DESC
               LIMIT %s
           ) sub ORDER BY created_at ASC""",
        (empresa_id, phone, limit)
    )
    return [{'role': r['role'], 'content': r['content']} for r in rows]


def save_message(empresa_id, phone, role, content, push_name=None):
    _query(
        """INSERT INTO conversas (empresa_id, phone, role, content, push_name)
           VALUES (%s, %s, %s, %s, %s)""",
        (empresa_id, phone, role, content, push_name),
        fetch=False
    )


def log_token_usage(empresa_id, model, input_tokens, output_tokens, cost):
    _query(
        """INSERT INTO logs_consumo
               (empresa_id, modelo, tokens_entrada, tokens_saida, custo_estimado, tipo_operacao)
           VALUES (%s, %s, %s, %s, %s, 'chat')""",
        (empresa_id, model, input_tokens, output_tokens, cost),
        fetch=False
    )


def get_contact_info(empresa_id, phone):
    """Retorna info do contato: total de msgs, push_name, primeira interacao."""
    rows = _query(
        """SELECT
               COUNT(*) as total_msgs,
               MAX(push_name) as push_name,
               MIN(created_at) as first_seen
           FROM conversas
           WHERE empresa_id = %s AND phone = %s AND role = 'user'""",
        (empresa_id, phone)
    )
    if rows and rows[0]['total_msgs'] > 0:
        return dict(rows[0])
    return None


def get_lid_phone(lid_jid, instance_name):
    rows = _query(
        "SELECT phone FROM lid_phone_map WHERE lid = %s AND instance_name = %s LIMIT 1",
        (lid_jid, instance_name)
    )
    return rows[0]['phone'] if rows else None


def save_lid_phone(lid_jid, phone, instance_name, push_name=None):
    _query(
        """INSERT INTO lid_phone_map (lid, phone, instance_name, push_name)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (lid, instance_name) DO UPDATE SET phone = EXCLUDED.phone""",
        (lid_jid, phone, instance_name, push_name),
        fetch=False
    )


def save_unresolved_lid(lid_jid, instance_name, push_name='', payload_key=''):
    _query(
        """INSERT INTO unresolved_lids (lid, instance_name, push_name, payload_key)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (lid, instance_name) DO UPDATE SET
               push_name = EXCLUDED.push_name,
               attempts = unresolved_lids.attempts + 1,
               last_seen = CURRENT_TIMESTAMP""",
        (lid_jid, instance_name, push_name, payload_key),
        fetch=False
    )


def get_unresolved_lids():
    rows = _query(
        """SELECT lid, instance_name, push_name, attempts, last_seen
           FROM unresolved_lids
           WHERE resolved = false
           ORDER BY last_seen DESC LIMIT 50"""
    )
    return [dict(r) for r in rows] if rows else []


def mark_lid_resolved(lid_jid, instance_name):
    _query(
        """UPDATE unresolved_lids SET resolved = true
           WHERE lid = %s AND instance_name = %s""",
        (lid_jid, instance_name),
        fetch=False
    )


# --- Pending LID responses ---

def ensure_pending_table():
    _query(
        """CREATE TABLE IF NOT EXISTS pending_lid_responses (
               id SERIAL PRIMARY KEY,
               lid TEXT NOT NULL,
               instance_name TEXT NOT NULL,
               response_text TEXT NOT NULL,
               push_name TEXT DEFAULT '',
               created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
               delivered BOOLEAN DEFAULT false
           )""",
        fetch=False
    )


def save_pending_response(lid_jid, instance_name, response_text, push_name=''):
    _query(
        """INSERT INTO pending_lid_responses (lid, instance_name, response_text, push_name)
           VALUES (%s, %s, %s, %s)""",
        (lid_jid, instance_name, response_text, push_name),
        fetch=False
    )


def get_pending_responses(lid_jid, instance_name):
    rows = _query(
        """SELECT id, response_text, push_name, created_at,
                  EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - created_at)) as age_seconds
           FROM pending_lid_responses
           WHERE lid = %s AND instance_name = %s AND delivered = false
           ORDER BY created_at ASC""",
        (lid_jid, instance_name)
    )
    return [dict(r) for r in rows] if rows else []


def mark_responses_delivered(ids):
    if not ids:
        return
    _query(
        "UPDATE pending_lid_responses SET delivered = true WHERE id = ANY(%s)",
        (ids,),
        fetch=False
    )


# --- Evolution Internal DB Queries ---

def resolve_lid_via_evolution_db(lid_jid):
    """Query Evolution internal Contact table to resolve LID via profilePicUrl or pushName."""
    try:
        lid_rows = _query(
            """SELECT "remoteJid", "pushName", "profilePicUrl"
               FROM evolution."Contact"
               WHERE "remoteJid" = %s LIMIT 1""",
            (lid_jid,)
        )
        if not lid_rows:
            return None

        lid_contact = lid_rows[0]
        pic_url = lid_contact.get('profilePicUrl')
        push_name = lid_contact.get('pushName', '')

        # Match by profilePicUrl (base path only, ignore query params)
        if pic_url:
            base_pic = pic_url.split('?')[0]
            phone_rows = _query(
                """SELECT "remoteJid" FROM evolution."Contact"
                   WHERE SPLIT_PART("profilePicUrl", '?', 1) = %s
                   AND "remoteJid" LIKE '%%@s.whatsapp.net'
                   LIMIT 1""",
                (base_pic,)
            )
            if phone_rows:
                return phone_rows[0]['remoteJid'].split('@')[0]

        # Match by pushName (unique only)
        if push_name:
            phone_rows = _query(
                """SELECT "remoteJid" FROM evolution."Contact"
                   WHERE "pushName" = %s
                   AND "remoteJid" LIKE '%%@s.whatsapp.net'""",
                (push_name,)
            )
            if phone_rows and len(phone_rows) == 1:
                return phone_rows[0]['remoteJid'].split('@')[0]

        return None
    except Exception:
        return None


def resolve_lid_via_message_correlation(lid_jid):
    """Match LID to phone via sent/received message timestamp correlation in Evolution DB."""
    try:
        rows = _query(
            """WITH lid_times AS (
                   SELECT MIN("messageTimestamp") as first_ts,
                          MAX("messageTimestamp") as last_ts
                   FROM evolution."Message"
                   WHERE key->>'remoteJid' = %s
                     AND key->>'fromMe' = 'false'
               )
               SELECT DISTINCT key->>'remoteJid' as phone_jid
               FROM evolution."Message", lid_times
               WHERE key->>'fromMe' = 'true'
                 AND key->>'remoteJid' LIKE '%%@s.whatsapp.net'
                 AND "messageTimestamp" BETWEEN lid_times.first_ts - 600
                     AND lid_times.last_ts + 600""",
            (lid_jid,)
        )
        if rows and len(rows) == 1:
            return rows[0]['phone_jid'].split('@')[0]
        return None
    except Exception:
        return None


def resolve_lid_via_isonwhatsapp_elimination(lid_jid):
    """Last resort: find unmapped phones in IsOnWhatsapp. If only one, it's the match."""
    try:
        all_phones_rows = _query(
            """SELECT "remoteJid" FROM evolution."IsOnWhatsapp"
               WHERE "remoteJid" LIKE '%%@s.whatsapp.net'"""
        )
        if not all_phones_rows:
            return None

        all_phones = {r['remoteJid'].split('@')[0] for r in all_phones_rows}

        mapped_rows = _query("SELECT DISTINCT phone FROM lid_phone_map")
        mapped_phones = {r['phone'] for r in mapped_rows} if mapped_rows else set()

        # Also exclude phones that appear as contacts with @s.whatsapp.net
        # (they are already known and would have been matched by other strategies)
        known_rows = _query(
            """SELECT "remoteJid" FROM evolution."Contact"
               WHERE "remoteJid" LIKE '%%@s.whatsapp.net'"""
        )
        known_phones = {r['remoteJid'].split('@')[0] for r in known_rows} if known_rows else set()

        unmapped = all_phones - mapped_phones - known_phones
        if len(unmapped) == 1:
            return unmapped.pop()
        return None
    except Exception:
        return None
