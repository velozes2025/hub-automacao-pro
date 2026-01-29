"""Lead management service."""

import logging
from app.db import leads as leads_db
from app.ai.prompts import is_real_name

log = logging.getLogger('services.lead')


def upsert_lead(tenant_id, phone, push_name='', conversation_id=None,
                language='pt', company=None):
    """Create or update a lead with name cleaning."""
    name = push_name.strip() if push_name and is_real_name(push_name) else None
    return leads_db.upsert_lead(
        tenant_id=tenant_id,
        phone=phone,
        name=name,
        conversation_id=conversation_id,
        company=company,
    )


def update_stage(tenant_id, phone, stage):
    """Update lead stage in the funnel."""
    valid_stages = {'new', 'qualifying', 'nurturing', 'closing', 'support', 'closed'}
    if stage not in valid_stages:
        log.warning(f'Invalid stage: {stage}')
        return
    return leads_db.update_lead_stage(tenant_id, phone, stage)
