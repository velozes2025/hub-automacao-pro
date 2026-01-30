-- ============================================
-- Migration 004: SaaS Enhancements
-- Conversation summaries + Stripe billing columns
-- ============================================

-- 1. Conversation summaries (generated every 6 messages by AI)
CREATE TABLE IF NOT EXISTS conversation_summaries (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    summary_json JSONB NOT NULL DEFAULT '{}',
    message_count_at_summary INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conv_summaries_conversation
    ON conversation_summaries(conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conv_summaries_tenant
    ON conversation_summaries(tenant_id);

-- 2. Stripe billing columns on tenants
ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(255) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS billing_status VARCHAR(30) DEFAULT 'active'
        CHECK (billing_status IN ('active', 'trial', 'past_due', 'suspended', 'cancelled'));
