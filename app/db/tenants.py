"""Tenant, WhatsApp Account, and Agent Config database operations."""

import logging
from app.db import query, execute

log = logging.getLogger('db.tenants')


# --- Tenants ---

def create_tenant(name, slug, settings=None, anthropic_api_key=None):
    return execute(
        """INSERT INTO tenants (name, slug, settings, anthropic_api_key)
           VALUES (%s, %s, %s, %s)
           RETURNING *""",
        (name, slug, settings or '{}', anthropic_api_key),
        returning=True,
    )


def get_tenant(tenant_id):
    return query(
        "SELECT * FROM tenants WHERE id = %s",
        (tenant_id,),
        fetch='one',
    )


def get_tenant_by_slug(slug):
    return query(
        "SELECT * FROM tenants WHERE slug = %s",
        (slug,),
        fetch='one',
    )


def list_tenants(status='active'):
    if status:
        return query(
            "SELECT * FROM tenants WHERE status = %s ORDER BY name",
            (status,),
        )
    return query("SELECT * FROM tenants ORDER BY name")


def update_tenant(tenant_id, **fields):
    sets = []
    vals = []
    for k, v in fields.items():
        sets.append(f"{k} = %s")
        vals.append(v)
    sets.append("updated_at = CURRENT_TIMESTAMP")
    vals.append(tenant_id)
    return execute(
        f"UPDATE tenants SET {', '.join(sets)} WHERE id = %s",
        tuple(vals),
    )


# --- WhatsApp Accounts ---

def create_whatsapp_account(tenant_id, instance_name, phone_number=None, config_json=None):
    return execute(
        """INSERT INTO whatsapp_accounts (tenant_id, instance_name, phone_number, config)
           VALUES (%s, %s, %s, %s)
           RETURNING *""",
        (tenant_id, instance_name, phone_number, config_json or '{}'),
        returning=True,
    )


def get_whatsapp_account(account_id):
    return query(
        "SELECT * FROM whatsapp_accounts WHERE id = %s",
        (account_id,),
        fetch='one',
    )


def get_whatsapp_account_by_instance(instance_name):
    """Critical query: returns account + tenant in a single JOIN.

    Used on every webhook to resolve instance -> tenant context.
    """
    return query(
        """SELECT wa.*, t.name AS tenant_name, t.slug AS tenant_slug,
                  t.status AS tenant_status, t.settings AS tenant_settings,
                  t.anthropic_api_key AS tenant_anthropic_key
           FROM whatsapp_accounts wa
           JOIN tenants t ON t.id = wa.tenant_id
           WHERE wa.instance_name = %s AND wa.status = 'active'""",
        (instance_name,),
        fetch='one',
    )


def list_whatsapp_accounts(tenant_id):
    return query(
        "SELECT * FROM whatsapp_accounts WHERE tenant_id = %s ORDER BY instance_name",
        (tenant_id,),
    )


def update_whatsapp_account(account_id, **fields):
    sets = []
    vals = []
    for k, v in fields.items():
        sets.append(f"{k} = %s")
        vals.append(v)
    sets.append("updated_at = CURRENT_TIMESTAMP")
    vals.append(account_id)
    return execute(
        f"UPDATE whatsapp_accounts SET {', '.join(sets)} WHERE id = %s",
        tuple(vals),
    )


def delete_whatsapp_account(account_id):
    return execute(
        "DELETE FROM whatsapp_accounts WHERE id = %s",
        (account_id,),
    )


# --- Agent Configs ---

def get_active_agent_config(tenant_id, name='default'):
    return query(
        """SELECT * FROM agent_configs
           WHERE tenant_id = %s AND name = %s AND active = TRUE""",
        (tenant_id, name),
        fetch='one',
    )


def upsert_agent_config(tenant_id, name='default', **fields):
    existing = get_active_agent_config(tenant_id, name)
    if existing:
        sets = []
        vals = []
        for k, v in fields.items():
            sets.append(f"{k} = %s")
            vals.append(v)
        sets.append("updated_at = CURRENT_TIMESTAMP")
        vals.append(existing['id'])
        execute(
            f"UPDATE agent_configs SET {', '.join(sets)} WHERE id = %s",
            tuple(vals),
        )
        return get_active_agent_config(tenant_id, name)
    else:
        cols = ['tenant_id', 'name'] + list(fields.keys())
        placeholders = ['%s'] * len(cols)
        vals = [tenant_id, name] + list(fields.values())
        return execute(
            f"""INSERT INTO agent_configs ({', '.join(cols)})
                VALUES ({', '.join(placeholders)})
                RETURNING *""",
            tuple(vals),
            returning=True,
        )


def list_agent_configs(tenant_id):
    return query(
        "SELECT * FROM agent_configs WHERE tenant_id = %s ORDER BY name",
        (tenant_id,),
    )


def list_active_accounts():
    """List all active WhatsApp accounts across all tenants (for health monitoring)."""
    return query(
        """SELECT wa.id, wa.tenant_id, wa.instance_name, wa.status
           FROM whatsapp_accounts wa
           JOIN tenants t ON t.id = wa.tenant_id
           WHERE wa.status = 'active' AND t.status = 'active'""",
    )
