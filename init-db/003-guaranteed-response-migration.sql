-- ============================================
-- MIGRACAO: Framework de Garantia de Resposta
-- ============================================
-- Rodar manualmente em deploys existentes:
-- docker exec -i hub-postgres psql -U hub_user -d hub_database < init-db/003-guaranteed-response-migration.sql
-- ============================================

-- 1. Tabela de respostas falhadas (retry queue)
CREATE TABLE IF NOT EXISTS failed_responses (
    id SERIAL PRIMARY KEY,
    instance_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    response_text TEXT NOT NULL,
    empresa_id TEXT DEFAULT '',
    push_name TEXT DEFAULT '',
    attempts INTEGER DEFAULT 0,
    delivered BOOLEAN DEFAULT false,
    last_attempt TIMESTAMPTZ DEFAULT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_failed_responses_pending
    ON failed_responses (delivered, attempts, created_at ASC)
    WHERE delivered = false;

-- 2. Colunas de tracking de interacao na tabela leads
ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_client_msg_at TIMESTAMPTZ DEFAULT NULL;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_bot_msg_at TIMESTAMPTZ DEFAULT NULL;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS reengagement_count INTEGER DEFAULT 0;

-- 3. Index para query de reengajamento
CREATE INDEX IF NOT EXISTS idx_leads_reengagement
    ON leads (last_client_msg_at, last_bot_msg_at, reengagement_count)
    WHERE last_client_msg_at IS NOT NULL AND reengagement_count < 2;
