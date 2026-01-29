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

    for entry in pending:
        metadata = entry.get('metadata', {})
        if isinstance(metadata, str):
            import json
            metadata = json.loads(metadata) if metadata else {}

        lid_jid = metadata.get('lid_jid', '')
        if not lid_jid:
            continue

        instance_name = entry.get('instance_name', '')
        account_id = str(entry.get('whatsapp_account_id', ''))

        phone = lid_resolver.resolve(account_id, instance_name, lid_jid)
        if phone:
            log.info(f'[LID-WORKER] Resolved {lid_jid} -> {phone}')

            # Get account for delivery
            account = tenants_db.get_whatsapp_account(account_id)
            if account:
                _deliver_pending_lid_responses(account, instance_name, lid_jid, phone)
