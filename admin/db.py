"""Admin panel database operations using the new platform schema."""

import logging
import psycopg2
import psycopg2.pool
import psycopg2.extras

log = logging.getLogger('admin.db')

_pool = None


def init_pool(host, port, dbname, user, password):
    global _pool
    _pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=1, maxconn=5,
        host=host, port=port, dbname=dbname, user=user, password=password,
    )
    log.info('Admin DB pool initialized')


def _query(sql, params=None, fetch='all'):
    conn = _pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if fetch == 'one':
                row = cur.fetchone()
                return dict(row) if row else None
            elif fetch == 'val':
                row = cur.fetchone()
                return list(row.values())[0] if row else None
            return [dict(r) for r in cur.fetchall()]
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def _execute(sql, params=None, returning=False):
    conn = _pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            conn.commit()
            if returning:
                row = cur.fetchone()
                return dict(row) if row else None
            return cur.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


# --- Admin Users (v2 with RBAC) ---

def count_admin_users():
    return _query("SELECT COUNT(*) AS cnt FROM admin_users_v2", fetch='val') or 0


def create_admin_user(username, password_hash, role='super_admin', tenant_id=None):
    return _execute(
        """INSERT INTO admin_users_v2 (username, password_hash, role, tenant_id)
           VALUES (%s, %s, %s, %s)
           RETURNING *""",
        (username, password_hash, role, tenant_id),
        returning=True,
    )


def get_admin_user(username):
    return _query(
        "SELECT * FROM admin_users_v2 WHERE username = %s",
        (username,),
        fetch='one',
    )


# --- Tenants ---

def list_tenants(tenant_id=None):
    """List tenants. If tenant_id given, returns only that tenant (for scoped admins)."""
    if tenant_id:
        return _query("SELECT * FROM tenants WHERE id = %s", (str(tenant_id),))
    return _query("SELECT * FROM tenants WHERE status = 'active' ORDER BY name")


def get_tenant(tenant_id):
    return _query("SELECT * FROM tenants WHERE id = %s", (str(tenant_id),), fetch='one')


def create_tenant(name, slug, settings='{}', api_key=None):
    return _execute(
        """INSERT INTO tenants (name, slug, settings, anthropic_api_key)
           VALUES (%s, %s, %s, %s)
           RETURNING *""",
        (name, slug, settings, api_key),
        returning=True,
    )


def update_tenant(tenant_id, **fields):
    sets = []
    vals = []
    for k, v in fields.items():
        sets.append(f"{k} = %s")
        vals.append(v)
    sets.append("updated_at = CURRENT_TIMESTAMP")
    vals.append(str(tenant_id))
    return _execute(
        f"UPDATE tenants SET {', '.join(sets)} WHERE id = %s",
        tuple(vals),
    )


# --- WhatsApp Accounts ---

def list_whatsapp_accounts(tenant_id=None):
    if tenant_id:
        return _query(
            """SELECT wa.*, t.name AS tenant_name
               FROM whatsapp_accounts wa
               JOIN tenants t ON t.id = wa.tenant_id
               WHERE wa.tenant_id = %s
               ORDER BY wa.instance_name""",
            (str(tenant_id),),
        )
    return _query(
        """SELECT wa.*, t.name AS tenant_name
           FROM whatsapp_accounts wa
           JOIN tenants t ON t.id = wa.tenant_id
           WHERE wa.status = 'active'
           ORDER BY t.name, wa.instance_name""",
    )


def get_whatsapp_account(account_id):
    return _query(
        "SELECT * FROM whatsapp_accounts WHERE id = %s",
        (str(account_id),),
        fetch='one',
    )


def get_whatsapp_account_by_instance(instance_name):
    return _query(
        "SELECT * FROM whatsapp_accounts WHERE instance_name = %s",
        (instance_name,),
        fetch='one',
    )


def create_whatsapp_account(tenant_id, instance_name, phone_number=None):
    return _execute(
        """INSERT INTO whatsapp_accounts (tenant_id, instance_name, phone_number)
           VALUES (%s, %s, %s)
           RETURNING *""",
        (str(tenant_id), instance_name, phone_number),
        returning=True,
    )


def set_webhook_configured(account_id, configured):
    return _execute(
        "UPDATE whatsapp_accounts SET webhook_configured = %s WHERE id = %s",
        (configured, str(account_id)),
    )


def deactivate_whatsapp_account(account_id):
    return _execute(
        "UPDATE whatsapp_accounts SET status = 'inactive' WHERE id = %s",
        (str(account_id),),
    )


# --- Agent Configs ---

def get_agent_config(tenant_id):
    return _query(
        "SELECT * FROM agent_configs WHERE tenant_id = %s AND active = TRUE AND name = 'default'",
        (str(tenant_id),),
        fetch='one',
    )


def upsert_agent_config(tenant_id, system_prompt, model, max_tokens,
                        max_history_messages=10, persona=None, tools_enabled=None):
    import json
    persona_json = json.dumps(persona) if persona else '{}'
    tools_json = json.dumps(tools_enabled) if tools_enabled else '["web_search"]'

    existing = get_agent_config(tenant_id)
    if existing:
        return _execute(
            """UPDATE agent_configs
               SET system_prompt = %s, model = %s, max_tokens = %s,
                   max_history_messages = %s, persona = %s, tools_enabled = %s,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = %s""",
            (system_prompt, model, max_tokens, max_history_messages,
             persona_json, tools_json, str(existing['id'])),
        )
    return _execute(
        """INSERT INTO agent_configs (tenant_id, name, system_prompt, model, max_tokens,
               max_history_messages, persona, tools_enabled)
           VALUES (%s, 'default', %s, %s, %s, %s, %s, %s)
           RETURNING *""",
        (str(tenant_id), system_prompt, model, max_tokens, max_history_messages,
         persona_json, tools_json),
        returning=True,
    )


# --- Consumption ---

def get_consumption(tenant_id=None, days=30):
    if tenant_id:
        return _query(
            """SELECT model, COUNT(*) AS calls,
                      SUM(input_tokens + output_tokens) AS total_tokens,
                      SUM(cost) AS total_cost
               FROM consumption_logs
               WHERE tenant_id = %s
                 AND created_at > CURRENT_TIMESTAMP - make_interval(days => %s)
               GROUP BY model ORDER BY total_cost DESC""",
            (str(tenant_id), days),
        )
    return _query(
        """SELECT t.name AS tenant_name, cl.model,
                  COUNT(*) AS calls,
                  SUM(cl.input_tokens + cl.output_tokens) AS total_tokens,
                  SUM(cl.cost) AS total_cost
           FROM consumption_logs cl
           JOIN tenants t ON t.id = cl.tenant_id
           WHERE cl.created_at > CURRENT_TIMESTAMP - make_interval(days => %s)
           GROUP BY t.name, cl.model
           ORDER BY total_cost DESC""",
        (days,),
    )


def get_messages_today(tenant_id):
    return _query(
        """SELECT COUNT(*) AS total FROM messages m
           JOIN conversations c ON c.id = m.conversation_id
           WHERE c.tenant_id = %s AND m.created_at::date = CURRENT_DATE""",
        (str(tenant_id),),
        fetch='one',
    )


# --- API Costs Dashboard ---

def get_costs_today(tenant_id=None):
    """Get total costs for today, optionally scoped to tenant."""
    where = "WHERE created_at::date = CURRENT_DATE"
    params = ()
    if tenant_id:
        where += " AND tenant_id = %s"
        params = (str(tenant_id),)
    return _query(
        f"""SELECT
                COALESCE(SUM(cost), 0) AS total_cost,
                COUNT(*) AS total_calls,
                COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens
           FROM consumption_logs {where}""",
        params, fetch='one',
    )


def get_costs_month(tenant_id=None):
    """Get total costs for current month."""
    where = "WHERE DATE_TRUNC('month', created_at) = DATE_TRUNC('month', CURRENT_DATE)"
    params = ()
    if tenant_id:
        where += " AND tenant_id = %s"
        params = (str(tenant_id),)
    return _query(
        f"""SELECT
                COALESCE(SUM(cost), 0) AS total_cost,
                COUNT(*) AS total_calls,
                COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens
           FROM consumption_logs {where}""",
        params, fetch='one',
    )


def get_costs_by_operation(tenant_id=None, days=30):
    """Breakdown by operation type (chat, tts, transcription)."""
    where = "WHERE created_at > CURRENT_TIMESTAMP - make_interval(days => %s)"
    params = [days]
    if tenant_id:
        where += " AND tenant_id = %s"
        params.append(str(tenant_id))
    return _query(
        f"""SELECT operation, model,
                   COUNT(*) AS calls,
                   COALESCE(SUM(input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(cost), 0) AS total_cost
           FROM consumption_logs {where}
           GROUP BY operation, model
           ORDER BY total_cost DESC""",
        tuple(params),
    )


def get_daily_costs(tenant_id=None, days=30):
    """Daily cost breakdown for charts."""
    where = "WHERE created_at > CURRENT_TIMESTAMP - make_interval(days => %s)"
    params = [days]
    if tenant_id:
        where += " AND tenant_id = %s"
        params.append(str(tenant_id))
    return _query(
        f"""SELECT DATE(created_at) AS day,
                   operation,
                   COUNT(*) AS calls,
                   COALESCE(SUM(cost), 0) AS total_cost
           FROM consumption_logs {where}
           GROUP BY DATE(created_at), operation
           ORDER BY day DESC""",
        tuple(params),
    )


def get_costs_by_tenant(days=30):
    """Per-tenant cost breakdown (super_admin view)."""
    return _query(
        """SELECT t.id AS tenant_id, t.name AS tenant_name, t.slug,
                  COUNT(*) AS calls,
                  COALESCE(SUM(cl.cost), 0) AS total_cost,
                  COALESCE(SUM(CASE WHEN cl.operation = 'chat' THEN cl.cost ELSE 0 END), 0) AS ai_cost,
                  COALESCE(SUM(CASE WHEN cl.operation = 'tts' THEN cl.cost ELSE 0 END), 0) AS tts_cost,
                  COALESCE(SUM(CASE WHEN cl.operation = 'transcription' THEN cl.cost ELSE 0 END), 0) AS transcription_cost,
                  COUNT(DISTINCT cl.conversation_id) AS conversations
           FROM consumption_logs cl
           JOIN tenants t ON t.id = cl.tenant_id
           WHERE cl.created_at > CURRENT_TIMESTAMP - make_interval(days => %s)
           GROUP BY t.id, t.name, t.slug
           ORDER BY total_cost DESC""",
        (days,),
    )


def get_tenants_with_stats():
    """Get all active tenants with usage stats for the clients page."""
    return _query("""
        SELECT t.id, t.name, t.slug, t.status, t.created_at,
               COALESCE(wa_stats.instance_count, 0) AS instance_count,
               COALESCE(msg_stats.msgs_today, 0) AS msgs_today,
               COALESCE(cost_stats.cost_30d, 0) AS cost_30d,
               COALESCE(cost_stats.calls_30d, 0) AS calls_30d,
               COALESCE(cost_stats.ai_cost, 0) AS ai_cost,
               COALESCE(cost_stats.tts_cost, 0) AS tts_cost,
               COALESCE(cost_stats.stt_cost, 0) AS stt_cost,
               COALESCE(conv_stats.total_conversations, 0) AS total_conversations
        FROM tenants t
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS instance_count
            FROM whatsapp_accounts wa
            WHERE wa.tenant_id = t.id AND wa.status = 'active'
        ) wa_stats ON TRUE
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS msgs_today
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE c.tenant_id = t.id AND m.created_at::date = CURRENT_DATE
        ) msg_stats ON TRUE
        LEFT JOIN LATERAL (
            SELECT SUM(cost) AS cost_30d,
                   COUNT(*) AS calls_30d,
                   SUM(CASE WHEN operation = 'chat' THEN cost ELSE 0 END) AS ai_cost,
                   SUM(CASE WHEN operation = 'tts' THEN cost ELSE 0 END) AS tts_cost,
                   SUM(CASE WHEN operation = 'transcription' THEN cost ELSE 0 END) AS stt_cost
            FROM consumption_logs cl
            WHERE cl.tenant_id = t.id
              AND cl.created_at > CURRENT_TIMESTAMP - INTERVAL '30 days'
        ) cost_stats ON TRUE
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS total_conversations
            FROM conversations c
            WHERE c.tenant_id = t.id
        ) conv_stats ON TRUE
        WHERE t.status = 'active'
        ORDER BY t.name
    """)


def get_consumption_by_operation(tenant_id, days=30):
    """Get consumption breakdown by operation type for a specific tenant."""
    return _query(
        """SELECT operation, model,
                  COUNT(*) AS calls,
                  COALESCE(SUM(input_tokens), 0) AS input_tokens,
                  COALESCE(SUM(output_tokens), 0) AS output_tokens,
                  COALESCE(SUM(cost), 0) AS total_cost
           FROM consumption_logs
           WHERE tenant_id = %s
             AND created_at > CURRENT_TIMESTAMP - make_interval(days => %s)
           GROUP BY operation, model
           ORDER BY total_cost DESC""",
        (str(tenant_id), days),
    )


def get_voice_costs_by_provider(tenant_id=None, days=30):
    """Breakdown of TTS costs by provider (ElevenLabs vs OpenAI)."""
    where = "WHERE operation = 'tts' AND created_at > CURRENT_TIMESTAMP - make_interval(days => %s)"
    params = [days]
    if tenant_id:
        where += " AND tenant_id = %s"
        params.append(str(tenant_id))
    return _query(
        f"""SELECT
                COALESCE(metadata->>'provider', 'openai') AS provider,
                model,
                COUNT(*) AS calls,
                COALESCE(SUM(input_tokens), 0) AS total_chars,
                COALESCE(SUM(cost), 0) AS total_cost
           FROM consumption_logs {where}
           GROUP BY COALESCE(metadata->>'provider', 'openai'), model
           ORDER BY total_cost DESC""",
        tuple(params),
    )


def get_voice_costs_by_tenant(days=30):
    """Per-tenant TTS cost breakdown with provider split (super_admin)."""
    return _query(
        """SELECT t.id AS tenant_id, t.name AS tenant_name,
                  COALESCE(cl.metadata->>'provider', 'openai') AS provider,
                  cl.model,
                  COUNT(*) AS calls,
                  COALESCE(SUM(cl.input_tokens), 0) AS total_chars,
                  COALESCE(SUM(cl.cost), 0) AS total_cost
           FROM consumption_logs cl
           JOIN tenants t ON t.id = cl.tenant_id
           WHERE cl.operation = 'tts'
             AND cl.created_at > CURRENT_TIMESTAMP - make_interval(days => %s)
           GROUP BY t.id, t.name, COALESCE(cl.metadata->>'provider', 'openai'), cl.model
           ORDER BY total_cost DESC""",
        (days,),
    )


def get_daily_voice_costs(tenant_id=None, days=30):
    """Daily voice cost breakdown by provider for chart."""
    where = "WHERE operation = 'tts' AND created_at > CURRENT_TIMESTAMP - make_interval(days => %s)"
    params = [days]
    if tenant_id:
        where += " AND tenant_id = %s"
        params.append(str(tenant_id))
    return _query(
        f"""SELECT DATE(created_at) AS day,
                   COALESCE(metadata->>'provider', 'openai') AS provider,
                   COUNT(*) AS calls,
                   COALESCE(SUM(cost), 0) AS total_cost
           FROM consumption_logs {where}
           GROUP BY DATE(created_at), COALESCE(metadata->>'provider', 'openai')
           ORDER BY day DESC""",
        tuple(params),
    )


def get_projected_monthly_cost(tenant_id=None):
    """Project monthly cost based on current month's average daily spend."""
    where = "WHERE DATE_TRUNC('month', created_at) = DATE_TRUNC('month', CURRENT_DATE)"
    params = ()
    if tenant_id:
        where += " AND tenant_id = %s"
        params = (str(tenant_id),)
    return _query(
        f"""SELECT
                COALESCE(SUM(cost), 0) AS month_so_far,
                COUNT(DISTINCT DATE(created_at)) AS days_active,
                EXTRACT(DAY FROM CURRENT_DATE) AS current_day,
                EXTRACT(DAY FROM
                    (DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month' - INTERVAL '1 day')
                ) AS days_in_month
           FROM consumption_logs {where}""",
        params, fetch='one',
    )
