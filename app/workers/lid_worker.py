"""Background worker: resolve pending LID JIDs.

Runs every 30 seconds. Picks up unresolved LIDs from message_queue
and attempts to resolve them using the 7-strategy resolver.
"""

import time
import logging

from app.config import config
from app.db import tenants as tenants_db
from app.db import queue as queue_db
from app.channels import lid_resolver
from app.services.message_handler import _deliver_pending_lid_responses

log = logging.getLogger('workers.lid')


def run():
    """Main loop — runs forever as daemon thread."""
    while True:
        try:
            time.sleep(config.LID_RESOLVE_INTERVAL_SECONDS)
            _resolve_pending()
        except Exception as e:
            log.error(f'LID worker error: {e}', exc_info=True)


def _resolve_pending():
    pending = queue_db.get_pending(queue_type='pending_lid', limit=50)
    if not pending:
        return

    # Expire entries older than 24 hours
    queue_db.expire_old(max_age_hours=24)

    for entry in pending:
        entry_id = entry.get('id')
        metadata = entry.get('metadata', {})
        if isinstance(metadata, str):
            import json
            metadata = json.loads(metadata) if metadata else {}

        lid_jid = metadata.get('lid_jid', '')
        if not lid_jid:
            # Bad entry — mark as expired so it stops being picked up
            if entry_id:
                queue_db.increment_attempt(entry_id, error='missing lid_jid')
            continue

        instance_name = entry.get('instance_name', '')
        account_id = str(entry.get('whatsapp_account_id', ''))

        phone = lid_resolver.resolve(account_id, instance_name, lid_jid)
        if phone:
            log.info(f'[LID-WORKER] Resolved {lid_jid} -> {phone}')
            account = tenants_db.get_whatsapp_account(account_id)
            if account:
                _deliver_pending_lid_responses(account, instance_name, lid_jid, phone)
        else:
            # Increment attempt so exponential backoff applies and max_attempts is enforced
            queue_db.increment_attempt(entry_id, error=f'unresolved after 7 strategies')
            log.info(f'[LID-WORKER] Attempt incremented for {lid_jid} (id={entry_id})')
