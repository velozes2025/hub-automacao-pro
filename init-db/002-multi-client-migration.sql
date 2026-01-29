-- ============================================
-- MIGRAÇÃO: Single-client → Multi-client
-- ============================================
-- Rodar manualmente em deploys existentes:
-- docker exec -i hub-postgres psql -U hub_user -d hub_database < init-db/002-multi-client-migration.sql
-- ============================================

-- 1. Expandir tabela empresas com config por cliente
ALTER TABLE empresas
  ADD COLUMN IF NOT EXISTS system_prompt TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS model VARCHAR(100) NOT NULL DEFAULT 'claude-3-haiku-20240307',
  ADD COLUMN IF NOT EXISTS max_tokens INTEGER NOT NULL DEFAULT 150,
  ADD COLUMN IF NOT EXISTS greeting_message TEXT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS persona_name VARCHAR(100) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS business_hours_start TIME DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS business_hours_end TIME DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS outside_hours_message TEXT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS typing_delay_ms INTEGER NOT NULL DEFAULT 800,
  ADD COLUMN IF NOT EXISTS max_history_messages INTEGER NOT NULL DEFAULT 10,
  ADD COLUMN IF NOT EXISTS webhook_configured BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS client_token VARCHAR(64) UNIQUE DEFAULT encode(gen_random_bytes(32), 'hex');

-- 2. Tabela de conversas (historico persistente)
CREATE TABLE IF NOT EXISTS conversas (
    id BIGSERIAL PRIMARY KEY,
    empresa_id UUID NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    phone VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    push_name VARCHAR(255) DEFAULT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conversas_empresa_phone
    ON conversas(empresa_id, phone, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversas_created
    ON conversas(created_at DESC);

COMMENT ON TABLE conversas IS 'Historico de mensagens por empresa e telefone';

-- 3. Tabela de admin (login do painel)
CREATE TABLE IF NOT EXISTS admin_users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Atualizar empresa teste existente
UPDATE empresas
SET system_prompt = 'Voce e um atendente profissional. Responda de forma educada e concisa.',
    model = 'claude-3-haiku-20240307',
    max_tokens = 150
WHERE nome = 'Empresa Teste'
  AND system_prompt = '';
