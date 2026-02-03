-- Memória principal por whatsapp_id
CREATE TABLE IF NOT EXISTS conversation_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    whatsapp_id TEXT NOT NULL,
    business_id TEXT,
    summary_short TEXT,
    summary_detailed TEXT,
    facts JSON DEFAULT '{}',
    lead_stage TEXT DEFAULT 'new',
    lead_temperature TEXT DEFAULT 'cold',
    first_contact_at DATETIME,
    last_contact_at DATETIME,
    total_messages INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(whatsapp_id, business_id)
);

-- Histórico de mensagens
CREATE TABLE IF NOT EXISTS conversation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sentiment TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (memory_id) REFERENCES conversation_memory(id) ON DELETE CASCADE
);

-- Contextos de negócio (multi-tenant)
CREATE TABLE IF NOT EXISTS business_contexts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    industry TEXT,
    system_prompt TEXT,
    tools_enabled JSON DEFAULT '[]',
    active INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Índices para performance
CREATE INDEX IF NOT EXISTS idx_memory_whatsapp ON conversation_memory(whatsapp_id);
CREATE INDEX IF NOT EXISTS idx_memory_business ON conversation_memory(business_id);
CREATE INDEX IF NOT EXISTS idx_history_memory ON conversation_history(memory_id);
CREATE INDEX IF NOT EXISTS idx_history_created ON conversation_history(created_at);
