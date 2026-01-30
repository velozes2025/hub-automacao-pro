"""Background worker: health monitoring for WhatsApp instances.

Runs every 5 minutes. Checks all active instances and alerts
admin on disconnected instances that exceed failure threshold.
"""

import time
import logging

log = logging.getLogger('workers.health')

HEALTH_CHECK_INTERVAL = 300  # 5 minutes


def run():
    """Main loop — runs forever as daemon thread."""
    # Wait 60 seconds on startup to let services initialize
    time.sleep(60)
    while True:
        try:
            _check_health()
        except Exception as e:
            log.error(f'Health worker error: {e}', exc_info=True)
        time.sleep(HEALTH_CHECK_INTERVAL)


def _check_health():
    from app.services import health_service
    health_service.check_all_instances()
