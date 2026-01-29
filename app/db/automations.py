"""Automation rules per tenant."""

import json
import logging
from app.db import query, execute

log = logging.getLogger('db.automations')


def get_automations(tenant_id, automation_type=None, active_only=True):
    """Get automation rules for a tenant."""
    conditions = ["tenant_id = %s"]
    params = [str(tenant_id)]

    if automation_type:
        conditions.append("type = %s")
        params.append(automation_type)
    if active_only:
        conditions.append("active = TRUE")

    where = " AND ".join(conditions)
    return query(
        f"SELECT * FROM automations WHERE {where} ORDER BY type",
        tuple(params),
    )


def create_automation(tenant_id, automation_type, config_json=None, active=True):
    return execute(
        """INSERT INTO automations (tenant_id, type, config, active)
           VALUES (%s, %s, %s, %s)
           RETURNING *""",
        (str(tenant_id), automation_type, config_json or '{}', active),
        returning=True,
    )


def update_automation(automation_id, **fields):
    sets = []
    vals = []
    for k, v in fields.items():
        sets.append(f"{k} = %s")
        vals.append(v)
    sets.append("updated_at = CURRENT_TIMESTAMP")
    vals.append(str(automation_id))
    return execute(
        f"UPDATE automations SET {', '.join(sets)} WHERE id = %s",
        tuple(vals),
    )


def toggle_automation(automation_id, active):
    return execute(
        """UPDATE automations
           SET active = %s, updated_at = CURRENT_TIMESTAMP
           WHERE id = %s""",
        (active, str(automation_id)),
    )
