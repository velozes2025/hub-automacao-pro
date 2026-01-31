"""Lead management service — auto-syncs with Airtable CRM."""

import logging
import threading
from datetime import datetime, timezone
from app.db import leads as leads_db
from app.ai.prompts import is_real_name

log = logging.getLogger('services.lead')

_STAGE_MAP = {
    'new': 'Novo', 'qualifying': 'Qualificando', 'nurturing': 'Nutrição',
    'closing': 'Fechando', 'support': 'Suporte', 'closed': 'Fechado',
    'lost': 'Perdido',
}


def _sync_to_airtable(phone, name, stage='new'):
    """Sync lead to Airtable in background (non-blocking)."""
    try:
        from app.integrations import airtable_client
        if not airtable_client.is_configured():
            return

        # Check if lead already exists in Airtable
        existing = airtable_client.search_records('Leads', 'Telefone', phone, max_records=1)
        if existing:
            # Update name/stage if changed
            rec_id = existing[0].get('id')
            updates = {}
            if name and not existing[0].get('Nome'):
                updates['Nome'] = name
            updates['Ultima Interacao'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
            if updates:
                airtable_client.update_record('Leads', rec_id, updates)
            return

        # Create new lead
        fields = {
            'Telefone': phone,
            'Status': _STAGE_MAP.get(stage, 'Novo'),
            'Origem': 'WhatsApp',
            'Data Entrada': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            'Ultima Interacao': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
        }
        if name:
            fields['Nome'] = name
        airtable_client.create_record('Leads', fields)
        log.info(f'[AIRTABLE-SYNC] New lead synced: {phone} ({name or "unnamed"})')
    except Exception as e:
        log.warning(f'[AIRTABLE-SYNC] Failed for {phone}: {e}')


def upsert_lead(tenant_id, phone, push_name='', conversation_id=None,
                language='pt', company=None):
    """Create or update a lead with name cleaning + auto Airtable sync."""
    name = push_name.strip() if push_name and is_real_name(push_name) else None
    result = leads_db.upsert_lead(
        tenant_id=tenant_id,
        phone=phone,
        name=name,
        conversation_id=conversation_id,
        company=company,
    )
    # Sync to Airtable in background (never blocks WhatsApp response)
    threading.Thread(
        target=_sync_to_airtable,
        args=(phone, name),
        daemon=True,
    ).start()
    return result


def update_stage(tenant_id, phone, stage):
    """Update lead stage in the funnel + sync to Airtable."""
    valid_stages = {'new', 'qualifying', 'nurturing', 'closing', 'support', 'closed'}
    if stage not in valid_stages:
        log.warning(f'Invalid stage: {stage}')
        return
    result = leads_db.update_lead_stage(tenant_id, phone, stage)
    # Sync stage to Airtable
    threading.Thread(
        target=_sync_stage_to_airtable,
        args=(phone, stage),
        daemon=True,
    ).start()
    return result


def _sync_stage_to_airtable(phone, stage):
    """Update lead stage in Airtable."""
    try:
        from app.integrations import airtable_client
        if not airtable_client.is_configured():
            return
        existing = airtable_client.search_records('Leads', 'Telefone', phone, max_records=1)
        if existing:
            airtable_client.update_record('Leads', existing[0]['id'], {
                'Status': _STAGE_MAP.get(stage, 'Novo'),
                'Ultima Interacao': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            })
    except Exception as e:
        log.warning(f'[AIRTABLE-SYNC] Stage update failed for {phone}: {e}')
