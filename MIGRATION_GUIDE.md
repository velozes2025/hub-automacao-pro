# GUIA DE MIGRACAO: Hub Automacao Pro -> Hostinger VPS

## ARQUITETURA ATUAL (Esta maquina)

```
Hub Automacao Pro
├── app/                    # Backend Python (Flask)
│   ├── ai/                 # OLIVER.CORE v6.0 (IA principal)
│   │   └── oliver_core/    # State machine, memoria, reflexao
│   ├── channels/           # WhatsApp, transcricao, TTS
│   ├── services/           # Message handler, leads, etc.
│   └── db/                 # PostgreSQL + Redis
├── agent-node/             # Backend Node.js (alternativo)
│   ├── src/integrations/   # Evolution, ElevenLabs, OpenAI
│   └── src/services/       # Message handler, memoria
├── admin/                  # Painel administrativo (Flask)
│   ├── app.py              # Rotas do painel
│   ├── db.py               # Queries do painel
│   └── templates/          # HTML do painel
└── docker-compose.yml      # Orquestracao
```

## APIS CONECTADAS (TODAS DEVEM IR JUNTO)

### 1. Evolution API (WhatsApp Gateway)
```
URL: http://104.248.180.81:8080
API_KEY: d0ea32d2a3314539063b931f895d05baf725dabf429fab04
```

### 2. OpenAI (GPT-4o + Whisper + TTS)
```
API_KEY: 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
Usos: Chat (GPT-4o), Transcricao (Whisper), TTS (gpt-4o-mini-tts)
```

### 3. Anthropic (Claude - backup)
```
API_KEY: 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
Uso: Fallback se OpenAI falhar
```

### 4. ElevenLabs (Voz do Oliver)
```
API_KEY: sk_fb543f367f06c3f30b6e0695ee8e4c1acb8451a89cbb8949
VOICE_ID: 2Z9f0UOViiovFhMVDC7M
Uso: TTS principal (voz mais natural)
```

### 5. Airtable (CRM de Leads)
```
API_KEY: pat0uFIrmEjYAELDQ.83d5f560a295377d24a4047014793fce8ff4e1705821b25360fc74e2a0966f60
BASE_ID: appe52kmG53A4Eh2l
Uso: Sincronizar leads automaticamente
```

### 6. Tavily (Web Search)
```
API_KEY: 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
Uso: Busca na web em tempo real
```

### 7. PostgreSQL (Database principal)
```
URL: postgresql://postgres:JdvdwoDdNrxkIRYhOfTsOEjyBpZodwux@interchange.proxy.rlwy.net:57498/railway
Uso: Conversas, leads, tenants, consumo
```

### 8. Google Calendar
```
CALENDAR_ID: 54f07e169f3bc36a97da8a1e46780790566dcd1ee5f58ae76c0dbb829db28b82@group.calendar.google.com
Uso: Agendamento de reunioes
```

### 9. Gmail SMTP
```
EMAIL: quantrexllc@gmail.com
Uso: Envio de emails
```

## ADMIN PANEL
```
SECRET_KEY: hub-admin-secret-2024-prod
DEFAULT_PASSWORD: ocXMFt4MGcuXyN5p3ZuCRg
ADMIN_NUMBER: 12398215146
```

---

## PLANO DE MIGRACAO

### FASE 1: Preparacao na Hostinger
1. Instalar Evolution API (Docker)
2. Configurar PostgreSQL (ou usar o mesmo do Railway)
3. Instalar dependencias (Node.js, Python se necessario)

### FASE 2: Transferencia de Codigo
1. Clonar este repositorio: https://github.com/velozes2025/hub-automacao-pro
2. Copiar .env com todas as APIs
3. Adaptar para OpenClaw se necessario

### FASE 3: Integracao com OpenClaw
- Evolution API expoe REST endpoints
- OpenClaw pode chamar via HTTP:
  - POST /message/sendText/{instance}
  - POST /message/sendMedia/{instance}
  - GET /chat/findContacts/{instance}

### FASE 4: Desconectar WhatsApp daqui
1. Ir no painel Evolution: http://104.248.180.81:8080
2. Desconectar instancia atual
3. Conectar na nova maquina (escanear QR)

### FASE 5: Testes
1. Enviar mensagem de teste
2. Verificar TTS (audio)
3. Verificar Airtable sync
4. Verificar Telegram + WhatsApp juntos

---

## RESTRICOES MINIMAS PARA OPENCLAW

```
1. NUNCA expor API keys em logs ou respostas
2. Rate limiting: max 60 msgs/minuto por numero
3. Validar webhooks (verificar origem)
4. Nao permitir comandos destrutivos (rm -rf, drop table, etc)
5. Logging de todas as acoes para auditoria
```

---

## REPOSITORIO GITHUB
```
https://github.com/velozes2025/hub-automacao-pro
```

Clone e use como base!
