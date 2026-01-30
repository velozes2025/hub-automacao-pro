"""Database connection layer with automatic failover.

PRIMARY pool: Railway PostgreSQL (DATABASE_URL).
FALLBACK pool: Docker PostgreSQL (DB_HOST/DB_PORT/...).

Every query/execute tries PRIMARY first. On connection-level errors
(OperationalError, InterfaceError), retries transparently on FALLBACK.
SQL-level errors (IntegrityError, ProgrammingError) are never retried
because they would fail on any database.
"""

import logging
import psycopg2
import psycopg2.pool
import psycopg2.extras

from app.config import config

log = logging.getLogger('db')

_pool_primary = None   # Railway (DATABASE_URL)
_pool_fallback = None  # Docker (DB_HOST / DB_PORT / ...)


def init_pool():
    """Initialize connection pools. Safe to call multiple times."""
    global _pool_primary, _pool_fallback
    if _pool_primary is not None or _pool_fallback is not None:
        return

    # --- PRIMARY: Railway via DATABASE_URL ---
    if config.DATABASE_URL:
        try:
            _pool_primary = psycopg2.pool.ThreadedConnectionPool(
                minconn=2, maxconn=20, dsn=config.DATABASE_URL,
            )
            log.info('[DB] PRIMARY pool (Railway) initialized')
        except Exception as e:
            log.warning(f'[DB] PRIMARY pool (Railway) failed to init: {e}')
            _pool_primary = None

    # --- FALLBACK: Docker Postgres via individual vars ---
    try:
        _pool_fallback = psycopg2.pool.ThreadedConnectionPool(
            minconn=2, maxconn=20,
            host=config.DB_HOST, port=config.DB_PORT,
            dbname=config.DB_NAME, user=config.DB_USER,
            password=config.DB_PASSWORD,
        )
        label = 'FALLBACK' if _pool_primary else 'ONLY'
        log.info(f'[DB] {label} pool (Docker) initialized')
    except Exception as e:
        if _pool_primary:
            log.warning(f'[DB] FALLBACK pool (Docker) failed: {e} — running Railway only')
        else:
            log.error('[DB] ALL pools failed to initialize')
            raise

    if not _pool_primary and not _pool_fallback:
        raise RuntimeError('[DB] No database pools available')


def get_pool():
    """Return the fallback (Docker) pool for direct access.

    Used by lid.py to query Evolution API's internal schema
    (evolution."Contact", evolution."Message") which lives only
    in the Docker Postgres, never in Railway.
    """
    return _pool_fallback


def _ordered_pools():
    """Return pools in priority order: primary first, fallback second."""
    pools = []
    if _pool_primary:
        pools.append(('Railway', _pool_primary))
    if _pool_fallback:
        pools.append(('Docker', _pool_fallback))
    return pools


def _with_failover(operation):
    """Execute a DB operation with primary->fallback failover.

    Args:
        operation: callable(conn) -> result. Receives a connection,
                   must return the query result.

    Only connection-level errors (OperationalError, InterfaceError)
    trigger failover. SQL errors are raised immediately.
    """
    pools = _ordered_pools()
    if not pools:
        raise RuntimeError('[DB] No pools initialized — call init_pool() first')

    last_error = None
    for pool_name, pool in pools:
        conn = None
        try:
            conn = pool.getconn()
            result = operation(conn)
            return result
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            last_error = e
            log.warning(f'[DB-FAILOVER] {pool_name} connection failed: {e}')
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

    log.error(f'[DB-FAILOVER] ALL pools failed. Last error: {last_error}')
    raise last_error


# --- Public API (used by all app/db/* modules) ---

def query(sql, params=None, fetch='all'):
    """Execute a SELECT query with automatic failover.

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
    return _with_failover(_do)


def execute(sql, params=None, returning=False):
    """Execute an INSERT/UPDATE/DELETE with automatic failover.

    If returning=True, returns the first row as dict (for RETURNING clauses).
    Otherwise returns rowcount.
    """
    def _do(conn):
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            conn.commit()
            if returning:
                row = cur.fetchone()
                return dict(row) if row else None
            return cur.rowcount
    return _with_failover(_do)


def execute_many(sql, params_list):
    """Execute a statement with multiple param sets, with failover."""
    def _do(conn):
        with conn.cursor() as cur:
            for params in params_list:
                cur.execute(sql, params)
            conn.commit()
    return _with_failover(_do)


def run_migration(sql_path):
    """Run a raw SQL migration file, with failover."""
    def _do(conn):
        with open(sql_path, 'r') as f:
            sql = f.read()
        with conn.cursor() as cur:
            cur.execute(sql)
            conn.commit()
        log.info(f'Migration applied: {sql_path}')
    return _with_failover(_do)
