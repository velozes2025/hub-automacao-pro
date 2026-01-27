-- ============================================
-- HUB AUTOMACAO PRO - Schema Inicial
-- ============================================
-- Este script é executado automaticamente
-- na primeira inicialização do PostgreSQL
-- ============================================

-- Extensão para gerar UUIDs
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- TABELA: empresas
-- ============================================
-- Cadastro das empresas clientes que usam o hub

CREATE TABLE IF NOT EXISTS empresas (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nome VARCHAR(255) NOT NULL,
    whatsapp_instance VARCHAR(100) UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo')),
    api_key_interna VARCHAR(64) UNIQUE NOT NULL DEFAULT encode(gen_random_bytes(32), 'hex'),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Índices para buscas frequentes
CREATE INDEX IF NOT EXISTS idx_empresas_status ON empresas(status);
CREATE INDEX IF NOT EXISTS idx_empresas_whatsapp ON empresas(whatsapp_instance);
CREATE INDEX IF NOT EXISTS idx_empresas_api_key ON empresas(api_key_interna);

-- Comentários descritivos
COMMENT ON TABLE empresas IS 'Cadastro de empresas clientes do hub de automação';
COMMENT ON COLUMN empresas.whatsapp_instance IS 'Nome da instância na Evolution API';
COMMENT ON COLUMN empresas.api_key_interna IS 'Chave única para autenticação da empresa no hub';

-- ============================================
-- TABELA: logs_consumo
-- ============================================
-- Registro de consumo de IA (Anthropic) por empresa

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

-- Índices para relatórios e análises
CREATE INDEX IF NOT EXISTS idx_logs_empresa ON logs_consumo(empresa_id);
CREATE INDEX IF NOT EXISTS idx_logs_created ON logs_consumo(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_empresa_data ON logs_consumo(empresa_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_modelo ON logs_consumo(modelo);

-- Comentários descritivos
COMMENT ON TABLE logs_consumo IS 'Registro de consumo da API Anthropic por empresa';
COMMENT ON COLUMN logs_consumo.tipo_operacao IS 'Tipo: chat, summarize, extract, classify, etc';
COMMENT ON COLUMN logs_consumo.metadata IS 'Dados extras em JSON (session_id, workflow_id, etc)';

-- ============================================
-- VIEW: consumo_por_empresa
-- ============================================
-- Resumo de consumo agregado por empresa

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
-- Consumo agregado por dia (para dashboards)

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
-- FUNÇÃO: atualizar updated_at
-- ============================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger para empresas
DROP TRIGGER IF EXISTS update_empresas_updated_at ON empresas;
CREATE TRIGGER update_empresas_updated_at
    BEFORE UPDATE ON empresas
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- DADOS INICIAIS (empresa de teste)
-- ============================================
INSERT INTO empresas (nome, whatsapp_instance, status)
VALUES ('Empresa Teste', 'teste-instance', 'ativo')
ON CONFLICT DO NOTHING;

-- ============================================
-- FIM DO SCHEMA
-- ============================================
