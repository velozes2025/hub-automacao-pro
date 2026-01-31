"""Initialize and manage all background workers with auto-restart.

Workers are daemon threads that run forever. If a worker dies from an
unhandled exception, the supervisor thread detects it and restarts it
automatically. This prevents silent worker death.
"""

import logging
import threading
import time

log = logging.getLogger('workers.manager')

_started = False
_workers = {}     # name -> (target_fn, thread)
_lock = threading.Lock()

# How often the supervisor checks worker health (seconds)
_SUPERVISOR_INTERVAL = 30


def _make_worker(name, target):
    """Create and start a worker thread. Returns the thread."""
    t = threading.Thread(target=_safe_run, args=(name, target),
                         name=name, daemon=True)
    t.start()
    return t


def _safe_run(name, target):
    """Wrapper that catches ALL exceptions and logs them.

    This prevents the thread from dying silently. The supervisor
    thread will detect the death and restart.
    """
    try:
        target()
    except Exception as e:
        log.error(f'[WORKER-CRASH] {name} died: {e}', exc_info=True)


def _supervisor_loop():
    """Monitor all workers and restart any that have died."""
    while True:
        time.sleep(_SUPERVISOR_INTERVAL)
        with _lock:
            for name, (target, thread) in list(_workers.items()):
                if not thread.is_alive():
                    log.warning(f'[WORKER-RESTART] {name} is dead, restarting...')
                    new_thread = _make_worker(name, target)
                    _workers[name] = (target, new_thread)
                    log.info(f'[WORKER-RESTART] {name} restarted successfully')


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

    worker_defs = [
        ('retry-worker', run_retry),
        ('reengagement-worker', run_reengage),
        ('lid-worker', run_lid),
        ('health-monitor', run_health),
    ]

    with _lock:
        for name, target in worker_defs:
            thread = _make_worker(name, target)
            _workers[name] = (target, thread)
            log.info(f'Worker started: {name}')

    # Start supervisor thread that monitors worker health
    supervisor = threading.Thread(
        target=_supervisor_loop,
        name='worker-supervisor',
        daemon=True,
    )
    supervisor.start()
    log.info(f'Worker supervisor started (checking every {_SUPERVISOR_INTERVAL}s)')
