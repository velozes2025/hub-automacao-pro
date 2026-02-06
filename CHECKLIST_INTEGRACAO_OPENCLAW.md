# CHECKLIST: Integrar Hub Automacao Pro com OpenClaw

## ANTES DE COMECAR

- [ ] Baixar ZIP do GitHub: https://github.com/velozes2025/hub-automacao-pro
- [ ] Ter acesso SSH a Hostinger VPS
- [ ] Desconectar WhatsApp DESTA maquina (fazer por ultimo!)

---

## FASE 1: Upload e Teste das APIs

### 1.1 Upload dos arquivos
```bash
# Na Hostinger
cd /seu/diretorio
unzip hub-automacao-pro-main.zip
cd hub-automacao-pro-main
```

### 1.2 Criar .env
```bash
# Copiar o conteudo do arquivo PROMPT_PARA_CLAUDE_HOSTINGER.md
# secao "TODAS AS APIs"
nano .env
```

### 1.3 Testar APIs
```bash
pip install requests psycopg2-binary
python TESTE_APIS_HOSTINGER.py
```

**Esperado:** Todas as APIs com [OK]

---

## FASE 2: Integrar com OpenClaw

### 2.1 Endpoints da Evolution API para OpenClaw usar:

```python
# Base URL
EVOLUTION_URL = "http://104.248.180.81:8080"
API_KEY = "d0ea32d2a3314539063b931f895d05baf725dabf429fab04"

# Headers para todas as requests
headers = {"apikey": API_KEY, "Content-Type": "application/json"}
```

### 2.2 Enviar mensagem de texto
```python
POST {EVOLUTION_URL}/message/sendText/{instanceName}
{
    "number": "5521999999999",
    "text": "Sua mensagem aqui"
}
```

### 2.3 Enviar audio (TTS)
```python
POST {EVOLUTION_URL}/message/sendWhatsAppAudio/{instanceName}
{
    "number": "5521999999999",
    "audio": "BASE64_DO_AUDIO"
}
```

### 2.4 Receber mensagens (Webhook)
```
Configure na Evolution:
- URL: https://SEU_DOMINIO/webhook/whatsapp
- Events: messages.upsert, contacts.upsert
```

### 2.5 Gerar audio com ElevenLabs
```python
import requests

def gerar_audio_oliver(texto):
    response = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/2Z9f0UOViiovFhMVDC7M",
        headers={
            "xi-api-key": "sk_fb543f367f06c3f30b6e0695ee8e4c1acb8451a89cbb8949",
            "Content-Type": "application/json"
        },
        json={
            "text": texto,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
        }
    )
    if response.status_code == 200:
        return base64.b64encode(response.content).decode()
    return None
```

---

## FASE 3: Copiar Logica do Oliver

### Arquivos essenciais para copiar:

1. **Personalidade do Oliver**
   - `app/ai/oliver_core/sistema_v51.py`
   - Contem o prompt completo do agente

2. **Deteccao de intencao**
   - `app/ai/oliver_core/intent_detector.py`

3. **Memoria persistente**
   - `app/ai/oliver_core/memory_service.py`

4. **Engine principal**
   - `app/ai/oliver_core/engine.py`

### Fluxo simplificado para OpenClaw:

```python
# 1. Recebe mensagem do WhatsApp
# 2. Carrega memoria do cliente
# 3. Detecta intencao
# 4. Gera resposta com GPT-4o
# 5. Se cliente mandou audio OU e novo lead -> responde com audio
# 6. Salva na memoria
# 7. Sincroniza com Airtable
```

---

## FASE 4: Painel Admin

### Arquivos do painel:
```
admin/
├── app.py          # Flask routes
├── db.py           # Database queries
├── templates/      # HTML templates
└── static/         # CSS/JS
```

### Para rodar:
```bash
cd admin
pip install flask
python app.py
# Acessa em http://localhost:5001
```

---

## FASE 5: Conectar WhatsApp

### 5.1 DESCONECTAR desta maquina primeiro!
```
Acesse: http://104.248.180.81:8080
-> Sua instancia -> Logout/Disconnect
```

### 5.2 Criar nova instancia na Hostinger (se Evolution local)
```bash
# Se instalar Evolution local:
POST http://localhost:8080/instance/create
{
    "instanceName": "oliver-hostinger",
    "qrcode": true
}
```

### 5.3 Escanear QR Code
- Abra WhatsApp no celular
- Configuracoes > Dispositivos conectados
- Escanear QR

---

## TESTES FINAIS

- [ ] Enviar mensagem de texto -> Recebe resposta
- [ ] Enviar audio -> Recebe audio de volta
- [ ] Novo lead -> Recebe audio de boas-vindas
- [ ] Verificar Airtable -> Lead aparece
- [ ] Telegram continua funcionando
- [ ] Painel admin acessivel

---

## TROUBLESHOOTING

### Webhook nao chega
```bash
# Verificar se Evolution esta configurada
GET {EVOLUTION_URL}/webhook/find/{instanceName}
```

### Audio nao toca
```
- Verificar se ElevenLabs retorna 200
- Audio deve estar em formato OGG/OPUS
- Base64 deve estar correto
```

### LID nao resolve (erro 400)
```
- Usar lid-resolver antes de enviar
- Verificar tabela lid_mappings no PostgreSQL
```

---

## CONTATOS DE API

| API | Dashboard |
|-----|-----------|
| OpenAI | https://platform.openai.com |
| Anthropic | https://console.anthropic.com |
| ElevenLabs | https://elevenlabs.io |
| Airtable | https://airtable.com |
| Tavily | https://tavily.com |

---

**SUCESSO!** Com esse checklist, voce consegue integrar tudo no OpenClaw.
