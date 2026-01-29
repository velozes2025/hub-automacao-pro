-- ============================================
-- Data Migration: Old schema -> New schema
-- ============================================
-- Migra dados de empresas, conversas, leads, admin_users
-- para as novas tabelas multi-tenant.
-- ============================================

-- 1. Migrar empresas -> tenants
INSERT INTO tenants (id, name, slug, status, settings, created_at)
SELECT
    id,
    nome,
    COALESCE(whatsapp_instance, LOWER(REPLACE(nome, ' ', '-'))),
    CASE WHEN ativo = true THEN 'active' ELSE 'inactive' END,
    jsonb_build_object(
        'greeting_message', COALESCE(greeting_message, ''),
        'persona_name', COALESCE(persona_name, ''),
        'business_hours_start', COALESCE(business_hours_start::text, ''),
        'business_hours_end', COALESCE(business_hours_end::text, ''),
        'outside_hours_message', COALESCE(outside_hours_message, ''),
        'typing_delay_ms', COALESCE(typing_delay_ms, 800)
    ),
    COALESCE(created_at, CURRENT_TIMESTAMP)
FROM empresas
ON CONFLICT (slug) DO NOTHING;

-- 2. Migrar empresas -> whatsapp_accounts
INSERT INTO whatsapp_accounts (tenant_id, instance_name, status, config, webhook_configured, client_token)
SELECT
    id,
    whatsapp_instance,
    CASE WHEN ativo = true THEN 'active' ELSE 'inactive' END,
    jsonb_build_object(
        'business_hours_start', COALESCE(business_hours_start::text, ''),
        'business_hours_end', COALESCE(business_hours_end::text, ''),
        'outside_hours_message', COALESCE(outside_hours_message, ''),
        'typing_delay_ms', COALESCE(typing_delay_ms, 800)
    ),
    COALESCE(webhook_configured, false),
    COALESCE(client_token, encode(gen_random_bytes(32), 'hex'))
FROM empresas
WHERE whatsapp_instance IS NOT NULL
ON CONFLICT (instance_name) DO NOTHING;

-- 3. Migrar empresas -> agent_configs
INSERT INTO agent_configs (tenant_id, name, system_prompt, model, max_tokens, max_history_messages, persona)
SELECT
    id,
    'default',
    COALESCE(system_prompt, ''),
    COALESCE(model, 'claude-sonnet-4-20250514'),
    COALESCE(max_tokens, 150),
    COALESCE(max_history_messages, 10),
    jsonb_build_object('name', COALESCE(persona_name, 'Oliver'))
FROM empresas
ON CONFLICT (tenant_id, name) DO NOTHING;

-- 4. Migrar conversas -> conversations + messages
-- First create conversations from distinct (empresa_id, phone) pairs
INSERT INTO conversations (tenant_id, whatsapp_account_id, contact_phone, contact_name, last_message_at)
SELECT DISTINCT ON (c.empresa_id, c.phone)
    c.empresa_id,
    wa.id,
    c.phone,
    c.push_name,
    MAX(c.created_at)
FROM conversas c
JOIN whatsapp_accounts wa ON wa.tenant_id = c.empresa_id
GROUP BY c.empresa_id, c.phone, c.push_name, wa.id
ON CONFLICT (whatsapp_account_id, contact_phone) DO NOTHING;

-- Then migrate messages
INSERT INTO messages (conversation_id, role, content, metadata, created_at)
SELECT
    conv.id,
    c.role,
    c.content,
    jsonb_build_object('push_name', COALESCE(c.push_name, ''), 'migrated', true),
    c.created_at
FROM conversas c
JOIN whatsapp_accounts wa ON wa.tenant_id = c.empresa_id
JOIN conversations conv ON conv.whatsapp_account_id = wa.id AND conv.contact_phone = c.phone;

-- 5. Migrar leads -> leads_v2
INSERT INTO leads_v2 (tenant_id, phone, name, stage, metadata, created_at, updated_at)
SELECT
    empresa_id,
    phone,
    NULLIF(push_name, ''),
    CASE
        WHEN status = 'novo' THEN 'new'
        WHEN status = 'em_andamento' THEN 'qualifying'
        WHEN status = 'convertido' THEN 'closing'
        ELSE 'new'
    END,
    jsonb_build_object(
        'origin', COALESCE(origin, 'whatsapp'),
        'first_message', COALESCE(first_message, ''),
        'detected_language', COALESCE(detected_language, 'pt'),
        'lid', COALESCE(lid, ''),
        'migrated', true
    ),
    COALESCE(created_at, CURRENT_TIMESTAMP),
    COALESCE(updated_at, CURRENT_TIMESTAMP)
FROM leads
ON CONFLICT (tenant_id, phone) DO NOTHING;

-- 6. Link leads to conversations
UPDATE leads_v2 l
SET conversation_id = c.id
FROM conversations c
WHERE c.tenant_id = l.tenant_id AND c.contact_phone = l.phone
  AND l.conversation_id IS NULL;

-- 7. Migrar admin_users -> admin_users_v2
INSERT INTO admin_users_v2 (username, password_hash, role)
SELECT username, password_hash, 'super_admin'
FROM admin_users
ON CONFLICT (username) DO NOTHING;

-- 8. Migrar logs_consumo -> consumption_logs
INSERT INTO consumption_logs (tenant_id, model, input_tokens, output_tokens, cost, operation, created_at)
SELECT
    empresa_id,
    model,
    input_tokens,
    output_tokens,
    custo,
    'chat',
    created_at
FROM logs_consumo;

-- 9. Migrar failed_responses -> message_queue
INSERT INTO message_queue (tenant_id, whatsapp_account_id, phone, content, queue_type, status, attempts)
SELECT
    wa.tenant_id,
    wa.id,
    fr.phone,
    fr.response_text,
    'failed',
    CASE WHEN fr.delivered THEN 'delivered' ELSE 'pending' END,
    fr.attempts
FROM failed_responses fr
JOIN whatsapp_accounts wa ON wa.instance_name = fr.instance_name;
