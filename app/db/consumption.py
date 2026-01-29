"""Consumption logging for AI usage tracking."""

import json
import logging
from app.db import query, execute

log = logging.getLogger('db.consumption')


def log_usage(tenant_id, model, input_tokens, output_tokens, cost,
              conversation_id=None, operation='chat', metadata=None):
    """Log AI consumption for a tenant."""
    meta_json = json.dumps(metadata) if metadata else '{}'
    return execute(
        """INSERT INTO consumption_logs
           (tenant_id, conversation_id, model, input_tokens, output_tokens, cost, operation, metadata)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (str(tenant_id), str(conversation_id) if conversation_id else None,
         model, input_tokens, output_tokens, cost, operation, meta_json),
    )


def get_tenant_consumption(tenant_id, days=30):
    """Get aggregated consumption for a tenant over N days."""
    return query(
        """SELECT model,
                  COUNT(*) AS calls,
                  SUM(input_tokens) AS total_input,
                  SUM(output_tokens) AS total_output,
                  SUM(input_tokens + output_tokens) AS total_tokens,
                  SUM(cost) AS total_cost
           FROM consumption_logs
           WHERE tenant_id = %s
             AND created_at > CURRENT_TIMESTAMP - make_interval(days => %s)
           GROUP BY model
           ORDER BY total_cost DESC""",
        (str(tenant_id), days),
    )


def get_daily_consumption(tenant_id, days=30):
    """Get daily consumption breakdown."""
    return query(
        """SELECT DATE(created_at) AS day,
                  COUNT(*) AS calls,
                  SUM(input_tokens + output_tokens) AS total_tokens,
                  SUM(cost) AS total_cost
           FROM consumption_logs
           WHERE tenant_id = %s
             AND created_at > CURRENT_TIMESTAMP - make_interval(days => %s)
           GROUP BY DATE(created_at)
           ORDER BY day DESC""",
        (str(tenant_id), days),
    )


def get_global_consumption(days=30):
    """Get consumption across all tenants (super_admin view)."""
    return query(
        """SELECT t.name AS tenant_name, t.slug,
                  COUNT(*) AS calls,
                  SUM(cl.input_tokens + cl.output_tokens) AS total_tokens,
                  SUM(cl.cost) AS total_cost
           FROM consumption_logs cl
           JOIN tenants t ON t.id = cl.tenant_id
           WHERE cl.created_at > CURRENT_TIMESTAMP - make_interval(days => %s)
           GROUP BY t.id, t.name, t.slug
           ORDER BY total_cost DESC""",
        (days,),
    )
