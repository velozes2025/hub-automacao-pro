# Configuração de Credenciais no n8n

## Credenciais Necessárias

O workflow `whatsapp-ai-assistant-complete.json` precisa de 2 credenciais configuradas:

---

## 1. Evolution API (Header Auth)

**Tipo:** Header Auth

| Campo | Valor |
|-------|-------|
| **Name** | `Evolution API` |
| **Header Name** | `apikey` |
| **Header Value** | Sua `EVOLUTION_API_KEY` do arquivo `.env` |

### Passo a passo:
1. No n8n, vá em **Settings** (engrenagem) → **Credentials**
2. Clique em **Add Credential**
3. Busque por **Header Auth**
4. Configure conforme tabela acima
5. Clique **Save**

---

## 2. Hub PostgreSQL

**Tipo:** Postgres

| Campo | Valor |
|-------|-------|
| **Name** | `Hub PostgreSQL` |
| **Host** | `postgres` (nome do container) |
| **Database** | `hub_database` |
| **User** | `hub_user` |
| **Password** | `hub_secret_2024` (ou o que definiu no .env) |
| **Port** | `5432` |
| **SSL** | Disabled |

### Passo a passo:
1. No n8n, vá em **Settings** → **Credentials**
2. Clique em **Add Credential**
3. Busque por **Postgres**
4. Configure conforme tabela acima
5. Clique **Test Connection** para verificar
6. Clique **Save**

---

## 3. Variável de Ambiente (ANTHROPIC_API_KEY)

A chave da Anthropic é lida via `$env.ANTHROPIC_API_KEY`.

O n8n já está configurado no docker-compose para herdar variáveis do `.env`.

### Verificar no .env:
```env
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx
```

### Adicionar ao docker-compose (se necessário):
Se a variável não estiver sendo lida, adicione no serviço n8n:

```yaml
n8n:
  environment:
    - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
```

---

## Importar o Workflow

### Opção 1: Interface Web
1. Acesse http://localhost:5678
2. Vá em **Workflows** → **Add Workflow**
3. Clique nos **3 pontinhos** (menu) → **Import from File**
4. Selecione `whatsapp-ai-assistant-complete.json`
5. Clique **Save**

### Opção 2: Arrastar e Soltar
1. Acesse http://localhost:5678
2. Crie um novo workflow vazio
3. Arraste o arquivo JSON para dentro da área do workflow

---

## Configurar Webhook na Evolution

Após importar e ativar o workflow, configure o webhook na Evolution:

```bash
# Obter URL do webhook
# Formato: http://n8n:5678/webhook/whatsapp-ai

# Configurar na instância
curl -X POST "http://localhost:8080/webhook/set/NOME-DA-INSTANCIA" \
  -H "apikey: SUA_EVOLUTION_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "webhook": {
      "enabled": true,
      "url": "http://n8n:5678/webhook/whatsapp-ai",
      "webhookByEvents": true,
      "events": [
        "MESSAGES_UPSERT"
      ]
    }
  }'
```

---

## Testar o Fluxo

1. **Verifique se os containers estão rodando:**
   ```bash
   docker-compose ps
   ```

2. **Crie uma empresa de teste no banco:**
   ```bash
   docker-compose exec postgres psql -U hub_user -d hub_database -c "
     INSERT INTO empresas (nome, whatsapp_instance, status)
     VALUES ('Minha Empresa', 'minha-instancia', 'ativo');
   "
   ```

3. **Conecte uma instância WhatsApp:**
   ```bash
   python scripts/evolution_manager.py criar minha-instancia
   python scripts/evolution_manager.py qrcode minha-instancia
   ```

4. **Envie uma mensagem** para o número conectado

5. **Verifique os logs do n8n:**
   ```bash
   docker-compose logs -f n8n
   ```

---

## Troubleshooting

### Webhook não recebe mensagens
- Verifique se o workflow está **ativo** (toggle verde)
- Confirme que o webhook está configurado na Evolution
- Teste manualmente: `curl -X POST http://localhost:5678/webhook/whatsapp-ai -d '{}'`

### Erro de conexão com PostgreSQL
- Verifique se o container postgres está healthy: `docker-compose ps`
- Teste a conexão: `docker-compose exec postgres pg_isready`

### Claude não responde
- Verifique se `ANTHROPIC_API_KEY` está no `.env`
- Teste a chave diretamente:
  ```bash
  curl https://api.anthropic.com/v1/messages \
    -H "x-api-key: $ANTHROPIC_API_KEY" \
    -H "anthropic-version: 2023-06-01" \
    -H "content-type: application/json" \
    -d '{"model":"claude-sonnet-4-20250514","max_tokens":100,"messages":[{"role":"user","content":"Olá"}]}'
  ```
