"""Database connection layer — single pool with failover.

Uses ONE primary database. Priority:
  1. Docker Postgres (DB_HOST/DB_PORT) if available
  2. Railway (DATABASE_URL) as fallback

All reads and writes go to the SAME pool. No dual-write.
This eliminates UUID desync, ghost bugs, and inconsistent state.
"""

import logging
import psycopg2
import psycopg2.pool
import psycopg2.extras

from app.config import config

log = logging.getLogger('db')

_pool = None          # Single active pool
_pool_name = None     # 'Docker' or 'Railway' (for logging)
_pool_docker = None   # Keep Docker pool reference for get_pool() (Evolution schema)


def init_pool():
    """Initialize connection pool. Safe to call multiple times."""
    global _pool, _pool_name, _pool_docker
    if _pool is not None:
        return

    # --- Try Docker Postgres first (local, fast) ---
    if config.DB_HOST and config.DB_PASSWORD:
        try:
            _pool_docker = psycopg2.pool.ThreadedConnectionPool(
                minconn=2, maxconn=20,
                host=config.DB_HOST, port=config.DB_PORT,
                dbname=config.DB_NAME, user=config.DB_USER,
                password=config.DB_PASSWORD,
            )
            _pool = _pool_docker
            _pool_name = 'Docker'
            log.info('[DB] Pool initialized: Docker Postgres (primary)')
            return
        except Exception as e:
            log.warning(f'[DB] Docker pool failed: {e}')
            _pool_docker = None

    # --- Fallback: Railway via DATABASE_URL ---
    if config.DATABASE_URL:
        try:
            _pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=2, maxconn=20, dsn=config.DATABASE_URL,
            )
            _pool_name = 'Railway'
            log.info('[DB] Pool initialized: Railway (fallback)')
            return
        except Exception as e:
            log.error(f'[DB] Railway pool failed: {e}')

    raise RuntimeError('[DB] No database pool available. Check DB_HOST/DB_PASSWORD or DATABASE_URL.')


def get_pool():
    """Return the Docker pool for direct access.

    Used by lid.py to query Evolution API's internal schema
    (evolution."Contact", evolution."Message") which lives only
    in the Docker Postgres.
    """
    return _pool_docker or _pool


def _execute_op(operation):
    """Execute a database operation with connection management."""
    if not _pool:
        raise RuntimeError('[DB] No pool initialized — call init_pool() first')

    conn = None
    try:
        conn = _pool.getconn()
        result = operation(conn)
        return result
    except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
        log.error(f'[DB] {_pool_name} connection error: {e}')
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                _pool.putconn(conn, close=True)
            except Exception:
                pass
            conn = None
        raise
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
                _pool.putconn(conn)
            except Exception:
                pass


# --- Public API (used by all app/db/* modules) ---

def query(sql, params=None, fetch='all'):
    """Execute a SELECT query.

    fetch: 'all' -> list of dicts, 'one' -> single dict or None, 'val' -> scalar
    """
    def _do(conn):
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
    return _execute_op(_do)


def execute(sql, params=None, returning=False):
    """Execute an INSERT/UPDATE/DELETE on the single active pool."""
    def _do(conn):
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            conn.commit()
            if returning:
                row = cur.fetchone()
                return dict(row) if row else None
            return cur.rowcount
    return _execute_op(_do)


def execute_many(sql, params_list):
    """Execute a statement with multiple param sets."""
    def _do(conn):
        with conn.cursor() as cur:
            for params in params_list:
                cur.execute(sql, params)
            conn.commit()
    return _execute_op(_do)


def run_migration(sql_path):
    """Run a raw SQL migration file."""
    def _do(conn):
        with open(sql_path, 'r') as f:
            sql = f.read()
        with conn.cursor() as cur:
            cur.execute(sql)
            conn.commit()
        log.info(f'Migration applied: {sql_path}')
    return _execute_op(_do)
