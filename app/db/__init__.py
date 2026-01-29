import logging
import psycopg2
import psycopg2.pool
import psycopg2.extras

from app.config import config

log = logging.getLogger('db')

_pool = None


def init_pool():
    """Initialize the connection pool. Called once at app startup."""
    global _pool
    if _pool is not None:
        return
    try:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=20,
            host=config.DB_HOST,
            port=config.DB_PORT,
            dbname=config.DB_NAME,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
        )
        log.info('Database pool initialized')
    except Exception as e:
        log.error(f'Failed to initialize DB pool: {e}')
        raise


def get_pool():
    """Return the active pool (for modules that need raw access)."""
    return _pool


def _get_conn():
    if _pool is None:
        raise RuntimeError('DB pool not initialized — call init_pool() first')
    return _pool.getconn()


def _put_conn(conn):
    if _pool and conn:
        _pool.putconn(conn)


def query(sql, params=None, fetch='all'):
    """Execute a SELECT query and return results.

    fetch: 'all' -> list of dicts, 'one' -> single dict or None, 'val' -> scalar
    """
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if fetch == 'one':
                row = cur.fetchone()
                return dict(row) if row else None
            elif fetch == 'val':
                row = cur.fetchone()
                return list(row.values())[0] if row else None
            else:
                return [dict(r) for r in cur.fetchall()]
    except Exception:
        conn.rollback()
        raise
    finally:
        _put_conn(conn)


def execute(sql, params=None, returning=False):
    """Execute an INSERT/UPDATE/DELETE.

    If returning=True, returns the first row as dict (for RETURNING clauses).
    Otherwise returns rowcount.
    """
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            conn.commit()
            if returning:
                row = cur.fetchone()
                return dict(row) if row else None
            return cur.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        _put_conn(conn)


def execute_many(sql, params_list):
    """Execute a statement with multiple param sets."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            for params in params_list:
                cur.execute(sql, params)
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _put_conn(conn)


def run_migration(sql_path):
    """Run a raw SQL migration file."""
    conn = _get_conn()
    try:
        with open(sql_path, 'r') as f:
            sql = f.read()
        with conn.cursor() as cur:
            cur.execute(sql)
            conn.commit()
        log.info(f'Migration applied: {sql_path}')
    except Exception:
        conn.rollback()
        raise
    finally:
        _put_conn(conn)
