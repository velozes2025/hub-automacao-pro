# PROMPT PARA CLAUDE NA HOSTINGER VPS

Copie e cole isso no Claude Code da outra maquina:

---

## CONTEXTO DA MIGRACAO

Estou migrando o **Hub Automacao Pro** de outra maquina para ca. O sistema atual tem:

1. **WhatsApp Bot** (Evolution API) - responde mensagens com IA
2. **OLIVER** - agente de vendas consultivas com voz (ElevenLabs/OpenAI TTS)
3. **Painel Admin** - gerenciar tenants, leads, conversas
4. **Integrações**: Airtable CRM, Google Calendar, Web Search, Email

Aqui ja tenho **OpenClaw framework** + **Telegram bot** rodando. Quero:
- Adicionar WhatsApp (Evolution API)
- Integrar a logica do OLIVER
- Manter Telegram funcionando
- Ter um unico sistema unificado

## REPOSITORIO BASE

```bash
git clone https://github.com/velozes2025/hub-automacao-pro.git
```

## TODAS AS APIs (JA CONFIGURADAS - SO USAR)

Crie um arquivo `.env` com:

```env
# ============================================
# APIS - COPIAR EXATAMENTE
# ============================================

# PostgreSQL (Railway - manter este ou migrar)
DATABASE_URL=postgresql://postgres:JdvdwoDdNrxkIRYhOfTsOEjyBpZodwux@interchange.proxy.rlwy.net:57498/railway

# Evolution API (WhatsApp)
EVOLUTION_API_KEY=d0ea32d2a3314539063b931f895d05baf725dabf429fab04
EVOLUTION_SERVER_URL=http://104.248.180.81:8080

# OpenAI (GPT-4o, Whisper, TTS)
OPENAI_API_KEY=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

# Anthropic Claude (backup)
ANTHROPIC_API_KEY=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

# ElevenLabs (Voz)
ELEVENLABS_API_KEY=sk_fb543f367f06c3f30b6e0695ee8e4c1acb8451a89cbb8949
ELEVENLABS_VOICE_ID=2Z9f0UOViiovFhMVDC7M

# Airtable CRM
AIRTABLE_API_KEY=pat0uFIrmEjYAELDQ.83d5f560a295377d24a4047014793fce8ff4e1705821b25360fc74e2a0966f60
AIRTABLE_BASE_ID=appe52kmG53A4Eh2l

# Tavily Web Search
TAVILY_API_KEY=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

# Google Calendar
GOOGLE_CALENDAR_ID=54f07e169f3bc36a97da8a1e46780790566dcd1ee5f58ae76c0dbb829db28b82@group.calendar.google.com

# Gmail
GMAIL_ADDRESS=quantrexllc@gmail.com

# Admin
ADMIN_SECRET_KEY=hub-admin-secret-2024-prod
ADMIN_DEFAULT_PASSWORD=ocXMFt4MGcuXyN5p3ZuCRg
ADMIN_NUMBER=12398215146

# Engine
ENGINE_V60_ENABLED=true
ENGINE_V60_MEMORY_ENABLED=true
ENGINE_V60_REFLECTION_ENABLED=true
DEFAULT_MODEL=claude-sonnet-4-20250514
TIMEZONE=America/Sao_Paulo
```

## O QUE VOCE PRECISA FAZER

### 1. Instalar Evolution API (se ainda nao tem)

```bash
docker run -d \
  --name evolution-api \
  -p 8080:8080 \
  -e AUTHENTICATION_API_KEY=d0ea32d2a3314539063b931f895d05baf725dabf429fab04 \
  atendai/evolution-api:latest
```

### 2. Clonar o repositorio base

```bash
git clone https://github.com/velozes2025/hub-automacao-pro.git
cd hub-automacao-pro
```

### 3. Integrar com OpenClaw

O OpenClaw pode chamar a Evolution API via HTTP:

```python
# Enviar mensagem WhatsApp
import requests

def send_whatsapp(phone, message):
    url = f"{EVOLUTION_URL}/message/sendText/{INSTANCE_NAME}"
    headers = {"apikey": EVOLUTION_API_KEY}
    data = {"number": phone, "text": message}
    return requests.post(url, json=data, headers=headers)

# Receber mensagens (webhook)
# Configure Evolution para enviar webhooks para seu endpoint
```

### 4. Logica do OLIVER (copiar de app/ai/oliver_core/)

Arquivos principais:
- `sistema_v51.py` - Prompt do agente Oliver
- `engine.py` - Motor v6.0 com state machine
- `memory_service.py` - Memoria persistente
- `intent_detector.py` - Deteccao de intencao

### 5. Conectar WhatsApp

**IMPORTANTE**: So fazer isso DEPOIS de desconectar na outra maquina!

1. Acessar: http://SEU_IP:8080
2. Criar instancia
3. Escanear QR code
4. Configurar webhook para receber mensagens

## RESTRICOES DE SEGURANCA (OBRIGATORIAS)

```python
# 1. Nunca logar API keys
SENSITIVE_KEYS = ['API_KEY', 'PASSWORD', 'SECRET', 'TOKEN']

# 2. Rate limiting
MAX_MESSAGES_PER_MINUTE = 60

# 3. Comandos proibidos
BLOCKED_COMMANDS = [
    'rm -rf', 'drop table', 'delete from',
    'shutdown', 'reboot', 'format'
]

# 4. Validar origem de webhooks
ALLOWED_WEBHOOK_IPS = ['IP_DA_EVOLUTION']
```

## ESTRUTURA SUGERIDA PARA UNIFICAR

```
/seu-projeto/
├── openclaw/              # Seu framework atual
├── telegram/              # Bot Telegram atual
├── whatsapp/              # NOVO - Integracao WhatsApp
│   ├── evolution.py       # Wrapper Evolution API
│   ├── handler.py         # Message handler
│   └── oliver/            # Copiar de hub-automacao-pro
├── shared/                # Codigo compartilhado
│   ├── ai/               # OpenAI/Claude calls
│   ├── tts/              # ElevenLabs/OpenAI TTS
│   └── db/               # PostgreSQL/Airtable
├── admin/                 # Copiar painel admin
└── .env                   # APIs (copiar acima)
```

## TESTE RAPIDO

Apos configurar, teste:

```python
# Teste Evolution API
import requests

url = "http://104.248.180.81:8080/instance/connectionState/SUA_INSTANCIA"
headers = {"apikey": "d0ea32d2a3314539063b931f895d05baf725dabf429fab04"}
r = requests.get(url, headers=headers)
print(r.json())  # Deve mostrar status da conexao
```

## DUVIDAS?

O codigo completo esta em: https://github.com/velozes2025/hub-automacao-pro

Arquivos mais importantes:
- `app/services/message_handler.py` - Pipeline principal
- `app/ai/oliver_core/sistema_v51.py` - Personalidade do Oliver
- `app/channels/sender.py` - Envio de mensagens/audio
- `admin/app.py` - Painel administrativo

---

**LEMBRE-SE**:
1. Desconectar WhatsApp na maquina antiga ANTES de conectar aqui
2. O mesmo numero de telefone so pode estar conectado em UMA instancia
3. Mantenha backup do .env em lugar seguro
