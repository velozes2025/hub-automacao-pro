import os
import logging
import psycopg2
import psycopg2.pool
import psycopg2.extras

log = logging.getLogger('qr.db')

_pool_primary = None   # Railway
_pool_fallback = None  # Docker


def init_pool():
    global _pool_primary, _pool_fallback
    dsn = os.getenv('DATABASE_URL', '')
    if dsn:
        try:
            _pool_primary = psycopg2.pool.ThreadedConnectionPool(
                minconn=2, maxconn=10, dsn=dsn,
            )
            log.info('[DB] PRIMARY pool (Railway) initialized')
        except Exception as e:
            log.warning(f'[DB] PRIMARY pool (Railway) failed: {e}')
            _pool_primary = None
    try:
        _pool_fallback = psycopg2.pool.ThreadedConnectionPool(
            minconn=2, maxconn=10,
            host=os.getenv('DB_HOST', 'postgres'),
            port=int(os.getenv('DB_PORT', '5432')),
            dbname=os.getenv('DB_NAME', 'hub_database'),
            user=os.getenv('DB_USER', 'hub_user'),
            password=os.getenv('DB_PASSWORD', ''),
        )
        log.info(f'[DB] {"FALLBACK" if _pool_primary else "ONLY"} pool (Docker) initialized')
    except Exception as e:
        if not _pool_primary:
            raise
        log.warning(f'[DB] FALLBACK pool (Docker) failed: {e}')


def _ordered_pools():
    pools = []
    if _pool_primary:
        pools.append(('Railway', _pool_primary))
    if _pool_fallback:
        pools.append(('Docker', _pool_fallback))
    return pools


def _query(sql, params=None, fetch=True):
    pools = _ordered_pools()
    last_error = None
    for pool_name, pool in pools:
        conn = None
        try:
            conn = pool.getconn()
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                if fetch:
                    return cur.fetchall()
                conn.commit()
                return None
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            last_error = e
            log.warning(f'[DB-FAILOVER] {pool_name}: {e}')
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
                try:
                    pool.putconn(conn, close=True)
                except Exception:
                    pass
                conn = None
            continue
        except Exception:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            if conn:
                try:
                    pool.putconn(conn)
                except Exception:
                    pass
    raise last_error


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
