-- ============================================
-- Views for consumption reporting
-- ============================================

-- Daily consumption per tenant
CREATE OR REPLACE VIEW v_daily_consumption AS
SELECT
    t.name AS tenant_name,
    t.slug AS tenant_slug,
    DATE(cl.created_at) AS day,
    cl.model,
    COUNT(*) AS calls,
    SUM(cl.input_tokens) AS input_tokens,
    SUM(cl.output_tokens) AS output_tokens,
    SUM(cl.input_tokens + cl.output_tokens) AS total_tokens,
    SUM(cl.cost) AS total_cost
FROM consumption_logs cl
JOIN tenants t ON t.id = cl.tenant_id
GROUP BY t.name, t.slug, DATE(cl.created_at), cl.model
ORDER BY day DESC, total_cost DESC;

-- Tenant summary (last 30 days)
CREATE OR REPLACE VIEW v_tenant_summary AS
SELECT
    t.id AS tenant_id,
    t.name AS tenant_name,
    t.slug,
    t.status,
    COUNT(DISTINCT wa.id) AS whatsapp_accounts,
    COUNT(DISTINCT c.id) AS total_conversations,
    COUNT(DISTINCT l.id) AS total_leads,
    COALESCE(SUM(cl.cost), 0) AS total_cost_30d,
    COALESCE(SUM(cl.input_tokens + cl.output_tokens), 0) AS total_tokens_30d
FROM tenants t
LEFT JOIN whatsapp_accounts wa ON wa.tenant_id = t.id AND wa.status = 'active'
LEFT JOIN conversations c ON c.tenant_id = t.id
LEFT JOIN leads_v2 l ON l.tenant_id = t.id
LEFT JOIN consumption_logs cl ON cl.tenant_id = t.id
    AND cl.created_at > CURRENT_TIMESTAMP - INTERVAL '30 days'
GROUP BY t.id, t.name, t.slug, t.status
ORDER BY t.name;

-- Message queue status
CREATE OR REPLACE VIEW v_queue_status AS
SELECT
    t.name AS tenant_name,
    mq.queue_type,
    mq.status,
    COUNT(*) AS count,
    MIN(mq.created_at) AS oldest,
    MAX(mq.created_at) AS newest
FROM message_queue mq
JOIN tenants t ON t.id = mq.tenant_id
GROUP BY t.name, mq.queue_type, mq.status
ORDER BY t.name, mq.queue_type, mq.status;
