"""Background worker: retry failed message deliveries.

Runs every 30 seconds. Picks up messages from message_queue
with queue_type='failed' and attempts to resend them.
Max 5 attempts per message with exponential backoff.
"""

import time
import logging

from app.config import config
from app.db import queue as queue_db
from app.channels import whatsapp

log = logging.getLogger('workers.retry')


def run():
    """Main loop — runs forever as daemon thread."""
    while True:
        try:
            time.sleep(config.RETRY_INTERVAL_SECONDS)
            _process_retries()
        except Exception as e:
            log.error(f'Retry worker error: {e}', exc_info=True)


def _process_retries():
    pending = queue_db.get_pending(queue_type='failed', limit=50)
    if not pending:
        return

    log.info(f'[RETRY] Processing {len(pending)} failed messages')

    for entry in pending:
        queue_id = entry['id']
        instance_name = entry.get('instance_name', '')
        phone = entry['phone']
        text = entry['content']
        attempts = entry['attempts']

        sent = whatsapp.send_message(instance_name, phone, text)
        if sent:
            queue_db.mark_delivered(queue_id)
            log.info(f'[RETRY] Delivered: {instance_name} -> {phone} (attempt {attempts + 1})')
        else:
            queue_db.increment_attempt(queue_id, error='send_failed')
            if attempts + 1 >= entry.get('max_attempts', config.RETRY_MAX_ATTEMPTS):
                log.error(f'[RETRY] Gave up after {attempts + 1} attempts: {instance_name} -> {phone}')
            else:
                log.warning(f'[RETRY] Failed again ({attempts + 1}/{entry.get("max_attempts", config.RETRY_MAX_ATTEMPTS)}): {instance_name} -> {phone}')

    # Expire very old messages
    queue_db.expire_old(max_age_hours=24)
