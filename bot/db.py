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
