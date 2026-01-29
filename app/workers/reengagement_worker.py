"""Background worker: reengagement of stale conversations.

Runs every 5 minutes. Checks all tenants for conversations
where the client messaged but hasn't received a response.
Max 2 reengagement attempts per conversation.
"""

import time
import logging

from app.config import config
from app.db import tenants as tenants_db
from app.services import automation_service

log = logging.getLogger('workers.reengagement')


def run():
    """Main loop — runs forever as daemon thread."""
    while True:
        try:
            time.sleep(config.REENGAGE_INTERVAL_SECONDS)
            _check_all_tenants()
        except Exception as e:
            log.error(f'Reengagement worker error: {e}', exc_info=True)


def _check_all_tenants():
    tenants = tenants_db.list_tenants(status='active')
    total_sent = 0

    for tenant in tenants:
        try:
            sent = automation_service.run_reengagement(str(tenant['id']))
            total_sent += sent
        except Exception as e:
            log.error(f'Reengagement error for tenant {tenant["slug"]}: {e}')

    if total_sent:
        log.info(f'[REENGAGE] Total sent across all tenants: {total_sent}')
