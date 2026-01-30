"""Initialize and manage all background workers."""

import logging
import threading

log = logging.getLogger('workers.manager')

_started = False


def start_all_workers():
    """Start all background worker threads. Safe to call multiple times."""
    global _started
    if _started:
        return
    _started = True

    from app.workers.retry_worker import run as run_retry
    from app.workers.reengagement_worker import run as run_reengage
    from app.workers.lid_worker import run as run_lid
    from app.workers.health_worker import run as run_health

    workers = [
        ('retry-worker', run_retry),
        ('reengagement-worker', run_reengage),
        ('lid-worker', run_lid),
        ('health-monitor', run_health),
    ]

    for name, target in workers:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        log.info(f'Worker started: {name}')
