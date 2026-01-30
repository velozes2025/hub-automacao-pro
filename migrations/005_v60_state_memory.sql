-- ============================================
-- Migration 005: OLIVER.CORE v6.0
-- State Machine + Client Memory + Reflection Logs
-- ============================================

-- 1. conversation_states: state machine per conversation
CREATE TABLE IF NOT EXISTS conversation_states (
    id BIGSERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    current_node VARCHAR(30) NOT NULL DEFAULT 'ABERTURA',
    previous_node VARCHAR(30) DEFAULT NULL,
    active_agent VARCHAR(30) NOT NULL DEFAULT 'oliver',
    guard_data JSONB NOT NULL DEFAULT '{}',
    transition_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_conv_states_tenant
    ON conversation_states(tenant_id);

-- 2. client_memory: key-value facts per lead
CREATE TABLE IF NOT EXISTS client_memory (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    lead_id UUID NOT NULL REFERENCES leads_v2(id) ON DELETE CASCADE,
    fact_key VARCHAR(50) NOT NULL,
    fact_value TEXT NOT NULL,
    source VARCHAR(30) NOT NULL DEFAULT 'extraction',
    confidence REAL NOT NULL DEFAULT 0.8,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(lead_id, fact_key)
);

CREATE INDEX IF NOT EXISTS idx_client_memory_lead
    ON client_memory(lead_id);
CREATE INDEX IF NOT EXISTS idx_client_memory_tenant
    ON client_memory(tenant_id);

-- 3. reflection_logs: validation and retry audit trail
CREATE TABLE IF NOT EXISTS reflection_logs (
    id BIGSERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    original_response TEXT NOT NULL,
    issues_found JSONB NOT NULL DEFAULT '[]',
    was_retried BOOLEAN NOT NULL DEFAULT FALSE,
    final_response TEXT DEFAULT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reflection_logs_conversation
    ON reflection_logs(conversation_id, created_at DESC);
