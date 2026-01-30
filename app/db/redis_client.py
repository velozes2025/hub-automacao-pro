"""Redis connection pool for deduplication and health tracking.

Uses DB 1 to avoid collision with Evolution API (DB 0).
Graceful degradation: if Redis is unavailable, all operations
return safe defaults and the system continues without Redis features.
"""

import logging
import redis

from app.config import config

log = logging.getLogger('db.redis')

_pool = None


def init_redis():
    """Initialize Redis connection pool. Safe to call multiple times."""
    global _pool
    if not config.REDIS_URL:
        log.info('REDIS_URL not set — Redis features disabled')
        return
    try:
        _pool = redis.ConnectionPool.from_url(
            config.REDIS_URL,
            decode_responses=True,
            max_connections=20,
        )
        r = redis.Redis(connection_pool=_pool)
        r.ping()
        log.info(f'Redis connected: {config.REDIS_URL}')
    except Exception as e:
        log.warning(f'Redis unavailable ({e}) — Redis features disabled')
        _pool = None


def get_redis():
    """Get a Redis client. Returns None if unavailable."""
    if _pool is None:
        return None
    try:
        return redis.Redis(connection_pool=_pool)
    except Exception:
        return None
