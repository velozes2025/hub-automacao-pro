-- ============================================
-- Hub Automacao Pro — Platform Schema
-- ============================================
-- 11 tabelas para arquitetura multi-tenant
-- Rodar: psql -U hub_user -d hub_database < migrations/001_platform_schema.sql
-- ============================================

-- Extensoes necessarias
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================
-- 1. tenants (substitui empresas)
-- ============================================
CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive', 'suspended')),
    settings JSONB NOT NULL DEFAULT '{}',
    anthropic_api_key TEXT DEFAULT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- 2. whatsapp_accounts (1 tenant -> N numeros)
-- ============================================
CREATE TABLE IF NOT EXISTS whatsapp_accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    instance_name VARCHAR(100) UNIQUE NOT NULL,
    phone_number VARCHAR(50) DEFAULT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    config JSONB NOT NULL DEFAULT '{}',
    webhook_configured BOOLEAN NOT NULL DEFAULT FALSE,
    client_token VARCHAR(64) UNIQUE DEFAULT encode(gen_random_bytes(32), 'hex'),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wa_accounts_tenant
    ON whatsapp_accounts(tenant_id);

-- ============================================
-- 3. agent_configs (config de IA por tenant)
-- ============================================
CREATE TABLE IF NOT EXISTS agent_configs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL DEFAULT 'default',
    system_prompt TEXT NOT NULL DEFAULT '',
    model VARCHAR(100) NOT NULL DEFAULT 'claude-sonnet-4-20250514',
    max_tokens INTEGER NOT NULL DEFAULT 150,
    max_history_messages INTEGER NOT NULL DEFAULT 10,
    persona JSONB NOT NULL DEFAULT '{}',
    tools_enabled JSONB NOT NULL DEFAULT '["web_search"]',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, name)
);

-- ============================================
-- 4. conversations (entidade de conversa)
-- ============================================
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    whatsapp_account_id UUID NOT NULL REFERENCES whatsapp_accounts(id),
    contact_phone VARCHAR(50) NOT NULL,
    contact_name VARCHAR(255) DEFAULT NULL,
    language VARCHAR(10) DEFAULT 'pt',
    stage VARCHAR(30) NOT NULL DEFAULT 'new'
        CHECK (stage IN ('new', 'qualifying', 'nurturing', 'closing', 'support', 'closed')),
    metadata JSONB NOT NULL DEFAULT '{}',
    last_message_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(whatsapp_account_id, contact_phone)
);

CREATE INDEX IF NOT EXISTS idx_conversations_tenant
    ON conversations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_conversations_last_msg
    ON conversations(last_message_at DESC);

-- ============================================
-- 5. messages (substitui conversas)
-- ============================================
CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages(conversation_id, created_at DESC);

-- ============================================
-- 6. leads
-- ============================================
CREATE TABLE IF NOT EXISTS leads_v2 (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id UUID REFERENCES conversations(id),
    phone VARCHAR(50) NOT NULL,
    name VARCHAR(255) DEFAULT NULL,
    company VARCHAR(255) DEFAULT NULL,
    stage VARCHAR(30) NOT NULL DEFAULT 'new',
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, phone)
);

CREATE INDEX IF NOT EXISTS idx_leads_v2_tenant
    ON leads_v2(tenant_id);
CREATE INDEX IF NOT EXISTS idx_leads_v2_stage
    ON leads_v2(tenant_id, stage);

-- ============================================
-- 7. automations (regras por tenant)
-- ============================================
CREATE TABLE IF NOT EXISTS automations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    type VARCHAR(50) NOT NULL
        CHECK (type IN ('reengagement', 'business_hours', 'welcome', 'follow_up')),
    config JSONB NOT NULL DEFAULT '{}',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- 8. message_queue (unifica failed + pending_lid + scheduled)
-- ============================================
CREATE TABLE IF NOT EXISTS message_queue (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    whatsapp_account_id UUID NOT NULL REFERENCES whatsapp_accounts(id),
    phone VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    queue_type VARCHAR(20) NOT NULL
        CHECK (queue_type IN ('failed', 'pending_lid', 'scheduled')),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'delivered', 'expired', 'cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    metadata JSONB NOT NULL DEFAULT '{}',
    next_attempt_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_queue_pending
    ON message_queue(status, queue_type, next_attempt_at)
    WHERE status = 'pending';

-- ============================================
-- 9. lid_mappings (scoped por whatsapp_account)
-- ============================================
CREATE TABLE IF NOT EXISTS lid_mappings (
    id SERIAL PRIMARY KEY,
    whatsapp_account_id UUID NOT NULL REFERENCES whatsapp_accounts(id),
    lid_jid VARCHAR(100) NOT NULL,
    phone VARCHAR(50) NOT NULL,
    resolved_via VARCHAR(50) DEFAULT '',
    push_name VARCHAR(255) DEFAULT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(lid_jid, whatsapp_account_id)
);

-- ============================================
-- 10. consumption_logs
-- ============================================
CREATE TABLE IF NOT EXISTS consumption_logs (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    conversation_id UUID REFERENCES conversations(id),
    model VARCHAR(100) NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER GENERATED ALWAYS AS (input_tokens + output_tokens) STORED,
    cost DECIMAL(10, 6) NOT NULL DEFAULT 0,
    operation VARCHAR(50) NOT NULL DEFAULT 'chat',
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_consumption_tenant
    ON consumption_logs(tenant_id, created_at DESC);

-- ============================================
-- 11. admin_users_v2 (com RBAC)
-- ============================================
CREATE TABLE IF NOT EXISTS admin_users_v2 (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'admin'
        CHECK (role IN ('super_admin', 'admin', 'viewer')),
    tenant_id UUID REFERENCES tenants(id) DEFAULT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
