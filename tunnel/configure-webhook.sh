#!/bin/bash
# ============================================
# Configura Webhook na Evolution API
# ============================================

set -e

# Cores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

# Carregar variáveis
source ~/hub-automacao-pro/.env 2>/dev/null || true

EVOLUTION_LOCAL="http://localhost:8080"
API_KEY="${EVOLUTION_API_KEY:-sua-chave-global-evolution-aqui}"

echo -e "${BLUE}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║          CONFIGURAR WEBHOOK NA EVOLUTION API             ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Verificar se arquivo de URLs existe
if [ -f ~/hub-automacao-pro/tunnel/urls.txt ]; then
    source ~/hub-automacao-pro/tunnel/urls.txt
    echo -e "${GREEN}✓ URLs carregadas do arquivo${NC}"
else
    echo -e "${YELLOW}Arquivo urls.txt não encontrado.${NC}"
    echo -e "Execute primeiro: ${BLUE}./start-ngrok.sh${NC} ou ${BLUE}./start-cloudflare.sh${NC}"
    echo ""
    read -p "Ou digite a URL pública do n8n manualmente: " N8N_PUBLIC_URL
    WEBHOOK_URL="${N8N_PUBLIC_URL}/webhook/whatsapp-ai"
fi

echo ""
echo -e "Webhook URL: ${GREEN}$WEBHOOK_URL${NC}"
echo ""

# Listar instâncias disponíveis
echo -e "${BLUE}Buscando instâncias disponíveis...${NC}"
echo ""

INSTANCES=$(curl -s -X GET "$EVOLUTION_LOCAL/instance/fetchInstances" \
    -H "apikey: $API_KEY" \
    -H "Content-Type: application/json")

if [ -z "$INSTANCES" ] || [ "$INSTANCES" == "[]" ]; then
    echo -e "${RED}Nenhuma instância encontrada.${NC}"
    echo -e "Crie uma instância primeiro: ${BLUE}python scripts/evolution_manager.py criar <nome>${NC}"
    exit 1
fi

# Extrair nomes das instâncias
echo -e "${YELLOW}Instâncias disponíveis:${NC}"
echo ""

# Parse simples com grep/sed
INSTANCE_NAMES=$(echo "$INSTANCES" | grep -o '"instanceName":"[^"]*"' | cut -d'"' -f4)

i=1
for NAME in $INSTANCE_NAMES; do
    echo "  $i) $NAME"
    i=$((i + 1))
done

echo ""
read -p "Digite o NOME da instância para configurar: " INSTANCE_NAME

if [ -z "$INSTANCE_NAME" ]; then
    echo -e "${RED}Nome da instância é obrigatório${NC}"
    exit 1
fi

echo ""
echo -e "${BLUE}Configurando webhook para: $INSTANCE_NAME${NC}"

# Configurar webhook
RESPONSE=$(curl -s -X POST "$EVOLUTION_LOCAL/webhook/set/$INSTANCE_NAME" \
    -H "apikey: $API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
        "webhook": {
            "enabled": true,
            "url": "'"$WEBHOOK_URL"'",
            "webhookByEvents": true,
            "webhookBase64": false,
            "events": [
                "MESSAGES_UPSERT",
                "MESSAGES_UPDATE",
                "SEND_MESSAGE",
                "CONNECTION_UPDATE"
            ]
        }
    }')

echo ""

if echo "$RESPONSE" | grep -q "error"; then
    echo -e "${RED}✗ Erro ao configurar webhook:${NC}"
    echo "$RESPONSE"
else
    echo -e "${GREEN}✓ Webhook configurado com sucesso!${NC}"
    echo ""
    echo -e "${YELLOW}Configuração aplicada:${NC}"
    echo "  Instância: $INSTANCE_NAME"
    echo "  URL: $WEBHOOK_URL"
    echo "  Eventos: MESSAGES_UPSERT, MESSAGES_UPDATE, SEND_MESSAGE, CONNECTION_UPDATE"
fi

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  PRÓXIMOS PASSOS${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "1. Verifique se o workflow está ATIVO no n8n:"
echo "   ${GREEN}${N8N_PUBLIC_URL}${NC}"
echo ""
echo "2. Certifique-se que a instância está CONECTADA:"
echo "   ${BLUE}python scripts/evolution_manager.py status $INSTANCE_NAME${NC}"
echo ""
echo "3. Verifique se a empresa está cadastrada no banco:"
echo "   ${BLUE}docker-compose exec postgres psql -U hub_user -d hub_database \\${NC}"
echo "   ${BLUE}  -c \"SELECT * FROM empresas WHERE whatsapp_instance='$INSTANCE_NAME';\"${NC}"
echo ""
echo "4. Envie uma mensagem de teste para o número conectado!"
echo ""
