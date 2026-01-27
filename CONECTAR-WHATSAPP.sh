#!/bin/bash
# ============================================
# Hub Automação Pro - Conectar WhatsApp
# ============================================
# Execute este script quando tiver um número disponível
# ============================================

cd ~/hub-automacao-pro

# Cores
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Carregar configurações
source .env

echo -e "${BLUE}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║          CONECTAR WHATSAPP - Hub Automação Pro           ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Nome da instância
INSTANCE="minha-instancia"

echo -e "${YELLOW}1. Criando instância WhatsApp...${NC}"
curl -s -X POST "http://localhost:8080/instance/create" \
  -H "apikey: $EVOLUTION_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"instanceName\": \"$INSTANCE\",
    \"qrcode\": true,
    \"integration\": \"WHATSAPP-BAILEYS\"
  }" | python3 -c "import sys,json; print(json.load(sys.stdin).get('instance',{}).get('status','Criado'))" 2>/dev/null

echo ""
echo -e "${YELLOW}2. Gerando QR Code...${NC}"
echo ""
echo -e "${GREEN}Acesse este link para escanear o QR Code:${NC}"
echo -e "${BLUE}http://localhost:8080/instance/connect/$INSTANCE${NC}"
echo ""

# Aguardar conexão
echo -e "${YELLOW}3. Aguardando você escanear o QR Code...${NC}"
echo "   (Pressione Ctrl+C quando terminar de escanear)"
echo ""

while true; do
    STATUS=$(curl -s "http://localhost:8080/instance/connectionState/$INSTANCE" \
      -H "apikey: $EVOLUTION_API_KEY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('instance',{}).get('state',''))" 2>/dev/null)

    if [ "$STATUS" == "open" ]; then
        echo -e "${GREEN}✓ WhatsApp conectado!${NC}"
        break
    fi
    sleep 3
done

echo ""
echo -e "${YELLOW}4. Configurando webhook...${NC}"

# Pegar URL do ngrok
N8N_URL=$(cat tunnel/urls.txt 2>/dev/null | grep N8N_PUBLIC_URL | cut -d= -f2)

if [ -z "$N8N_URL" ]; then
    echo -e "${YELLOW}Túnel não está ativo. Iniciando...${NC}"
    ./tunnel/start-ngrok.sh &
    sleep 8
    N8N_URL=$(cat tunnel/urls.txt 2>/dev/null | grep N8N_PUBLIC_URL | cut -d= -f2)
fi

curl -s -X POST "http://localhost:8080/webhook/set/$INSTANCE" \
  -H "apikey: $EVOLUTION_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"webhook\": {
      \"enabled\": true,
      \"url\": \"$N8N_URL/webhook/whatsapp-ai\",
      \"webhookByEvents\": true,
      \"events\": [\"MESSAGES_UPSERT\"]
    }
  }" > /dev/null

echo -e "${GREEN}✓ Webhook configurado!${NC}"

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ TUDO PRONTO!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Agora envie uma mensagem para o número conectado"
echo "  e o bot com IA irá responder automaticamente!"
echo ""
