import os
import psycopg2
import psycopg2.pool
import psycopg2.extras

_pool = None


def init_pool():
    global _pool
    _pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=2, maxconn=10,
        host=os.getenv('DB_HOST', 'postgres'),
        port=int(os.getenv('DB_PORT', '5432')),
        dbname=os.getenv('DB_NAME', 'hub_database'),
        user=os.getenv('DB_USER', 'hub_user'),
        password=os.getenv('DB_PASSWORD', '')
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


def _query_one(sql, params=None):
    rows = _query(sql, params)
    return dict(rows[0]) if rows else None


# --- Empresas ---

def list_empresas():
    return [dict(r) for r in _query(
        "SELECT * FROM empresas ORDER BY created_at DESC"
    )]


def get_empresa(empresa_id):
    return _query_one(
        "SELECT * FROM empresas WHERE id = %s", (empresa_id,)
    )


def get_empresa_by_token(token):
    return _query_one(
        "SELECT * FROM empresas WHERE client_token = %s", (token,)
    )


def create_empresa(nome, whatsapp_instance, system_prompt, model, max_tokens,
                   greeting_message=None, persona_name=None,
                   business_hours_start=None, business_hours_end=None,
                   outside_hours_message=None, typing_delay_ms=800,
                   max_history_messages=10):
    return _query_one(
        """INSERT INTO empresas
               (nome, whatsapp_instance, system_prompt, model, max_tokens,
                greeting_message, persona_name, business_hours_start,
                business_hours_end, outside_hours_message, typing_delay_ms,
                max_history_messages)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING *""",
        (nome, whatsapp_instance, system_prompt, model, max_tokens,
         greeting_message, persona_name, business_hours_start,
         business_hours_end, outside_hours_message, typing_delay_ms,
         max_history_messages)
    )


def update_empresa(empresa_id, **kwargs):
    if not kwargs:
        return
    sets = ', '.join(f'{k} = %s' for k in kwargs)
    vals = list(kwargs.values()) + [empresa_id]
    _query(
        f"UPDATE empresas SET {sets} WHERE id = %s",
        vals, fetch=False
    )


def set_webhook_configured(empresa_id, value=True):
    _query(
        "UPDATE empresas SET webhook_configured = %s WHERE id = %s",
        (value, empresa_id), fetch=False
    )


def deactivate_empresa(empresa_id):
    _query(
        "UPDATE empresas SET status = 'inativo' WHERE id = %s",
        (empresa_id,), fetch=False
    )


# --- Consumo ---

def get_consumo_empresa(empresa_id):
    return _query_one(
        """SELECT * FROM consumo_por_empresa WHERE empresa_id = %s""",
        (empresa_id,)
    )


def get_consumo_global():
    return [dict(r) for r in _query(
        "SELECT * FROM consumo_por_empresa ORDER BY custo_total_estimado DESC"
    )]


def get_mensagens_hoje(empresa_id):
    return _query_one(
        """SELECT COUNT(*) as total FROM conversas
           WHERE empresa_id = %s AND created_at >= CURRENT_DATE""",
        (empresa_id,)
    )


# --- Admin Users ---

def get_admin_user(username):
    return _query_one(
        "SELECT * FROM admin_users WHERE username = %s", (username,)
    )


def create_admin_user(username, password_hash):
    _query(
        "INSERT INTO admin_users (username, password_hash) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (username, password_hash), fetch=False
    )


def count_admin_users():
    r = _query_one("SELECT COUNT(*) as total FROM admin_users")
    return r['total'] if r else 0
