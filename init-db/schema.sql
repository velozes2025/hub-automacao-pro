-- ============================================
-- HUB AUTOMACAO PRO - Schema Completo
-- ============================================
-- Executado automaticamente na primeira
-- inicializacao do PostgreSQL
-- ============================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================
-- TABELA: empresas
-- ============================================
CREATE TABLE IF NOT EXISTS empresas (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nome VARCHAR(255) NOT NULL,
    whatsapp_instance VARCHAR(100) UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo')),
    api_key_interna VARCHAR(64) UNIQUE NOT NULL DEFAULT encode(gen_random_bytes(32), 'hex'),
    system_prompt TEXT NOT NULL DEFAULT '',
    model VARCHAR(100) NOT NULL DEFAULT 'claude-3-haiku-20240307',
    max_tokens INTEGER NOT NULL DEFAULT 150,
    greeting_message TEXT DEFAULT NULL,
    persona_name VARCHAR(100) DEFAULT NULL,
    business_hours_start TIME DEFAULT NULL,
    business_hours_end TIME DEFAULT NULL,
    outside_hours_message TEXT DEFAULT NULL,
    typing_delay_ms INTEGER NOT NULL DEFAULT 800,
    max_history_messages INTEGER NOT NULL DEFAULT 10,
    webhook_configured BOOLEAN NOT NULL DEFAULT FALSE,
    client_token VARCHAR(64) UNIQUE DEFAULT encode(gen_random_bytes(32), 'hex'),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_empresas_status ON empresas(status);
CREATE INDEX IF NOT EXISTS idx_empresas_whatsapp ON empresas(whatsapp_instance);
CREATE INDEX IF NOT EXISTS idx_empresas_api_key ON empresas(api_key_interna);
CREATE INDEX IF NOT EXISTS idx_empresas_client_token ON empresas(client_token);

COMMENT ON TABLE empresas IS 'Cadastro de empresas clientes do hub de automacao';
COMMENT ON COLUMN empresas.whatsapp_instance IS 'Nome da instancia na Evolution API';
COMMENT ON COLUMN empresas.api_key_interna IS 'Chave unica para autenticacao da empresa no hub';
COMMENT ON COLUMN empresas.client_token IS 'Token para URL publica do QR code do cliente';

-- ============================================
-- TABELA: conversas
-- ============================================
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

-- ============================================
-- TABELA: logs_consumo
-- ============================================
CREATE TABLE IF NOT EXISTS logs_consumo (
    id BIGSERIAL PRIMARY KEY,
    empresa_id UUID NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    modelo VARCHAR(50) NOT NULL DEFAULT 'claude-3-sonnet',
    tokens_entrada INTEGER NOT NULL DEFAULT 0,
    tokens_saida INTEGER NOT NULL DEFAULT 0,
    tokens_total INTEGER GENERATED ALWAYS AS (tokens_entrada + tokens_saida) STORED,
    custo_estimado DECIMAL(10, 6) DEFAULT 0,
    tipo_operacao VARCHAR(50) NOT NULL DEFAULT 'chat',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_logs_empresa ON logs_consumo(empresa_id);
CREATE INDEX IF NOT EXISTS idx_logs_created ON logs_consumo(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_empresa_data ON logs_consumo(empresa_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_modelo ON logs_consumo(modelo);

COMMENT ON TABLE logs_consumo IS 'Registro de consumo da API Anthropic por empresa';

-- ============================================
-- TABELA: admin_users
-- ============================================
CREATE TABLE IF NOT EXISTS admin_users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- VIEW: consumo_por_empresa
-- ============================================
CREATE OR REPLACE VIEW consumo_por_empresa AS
SELECT
    e.id AS empresa_id,
    e.nome AS empresa_nome,
    e.status,
    COUNT(l.id) AS total_requisicoes,
    COALESCE(SUM(l.tokens_entrada), 0) AS total_tokens_entrada,
    COALESCE(SUM(l.tokens_saida), 0) AS total_tokens_saida,
    COALESCE(SUM(l.tokens_total), 0) AS total_tokens,
    COALESCE(SUM(l.custo_estimado), 0) AS custo_total_estimado,
    MAX(l.created_at) AS ultimo_uso
FROM empresas e
LEFT JOIN logs_consumo l ON e.id = l.empresa_id
GROUP BY e.id, e.nome, e.status;

-- ============================================
-- VIEW: consumo_diario
-- ============================================
CREATE OR REPLACE VIEW consumo_diario AS
SELECT
    DATE(l.created_at) AS data,
    e.id AS empresa_id,
    e.nome AS empresa_nome,
    l.modelo,
    COUNT(*) AS requisicoes,
    SUM(l.tokens_total) AS tokens,
    SUM(l.custo_estimado) AS custo
FROM logs_consumo l
JOIN empresas e ON l.empresa_id = e.id
GROUP BY DATE(l.created_at), e.id, e.nome, l.modelo
ORDER BY data DESC;

-- ============================================
-- FUNCAO: atualizar updated_at
-- ============================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_empresas_updated_at ON empresas;
CREATE TRIGGER update_empresas_updated_at
    BEFORE UPDATE ON empresas
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- DADOS INICIAIS
-- ============================================
INSERT INTO empresas (nome, whatsapp_instance, status, system_prompt, model, max_tokens)
VALUES ('Empresa Teste', 'teste-instance', 'ativo',
        'Voce e um atendente profissional. Responda de forma educada e concisa.',
        'claude-3-haiku-20240307', 150)
ON CONFLICT DO NOTHING;
