#!/bin/bash
# ============================================
# Hub Automação Pro - Cloudflare Tunnel
# ============================================
# Expõe n8n (5678) e Evolution (8080) para internet
# Opção gratuita sem necessidade de domínio próprio
# ============================================

set -e

# Cores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║        HUB AUTOMAÇÃO PRO - CLOUDFLARE TUNNEL             ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Verificar se cloudflared está instalado
if ! command -v cloudflared &> /dev/null; then
    echo -e "${YELLOW}⚠ Cloudflared não encontrado. Instalando...${NC}"

    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        if command -v brew &> /dev/null; then
            brew install cloudflared
        else
            echo "Baixando binário..."
            curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz -o /tmp/cloudflared.tgz
            tar -xzf /tmp/cloudflared.tgz -C /usr/local/bin/
            chmod +x /usr/local/bin/cloudflared
        fi
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Linux
        curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /tmp/cloudflared
        sudo mv /tmp/cloudflared /usr/local/bin/
        sudo chmod +x /usr/local/bin/cloudflared
    else
        echo -e "${RED}Sistema não suportado. Baixe em: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}✓ Cloudflared instalado${NC}"

# Diretório para logs
LOG_DIR=~/hub-automacao-pro/tunnel/logs
mkdir -p "$LOG_DIR"

# Função para iniciar túnel e capturar URL
start_tunnel() {
    local PORT=$1
    local NAME=$2
    local LOG_FILE="$LOG_DIR/${NAME}.log"

    echo -e "${BLUE}Iniciando túnel para $NAME (porta $PORT)...${NC}"

    # Cloudflare Quick Tunnel (trycloudflare.com) - não requer conta!
    cloudflared tunnel --url http://localhost:$PORT > "$LOG_FILE" 2>&1 &
    local PID=$!
    echo $PID > "$LOG_DIR/${NAME}.pid"

    # Aguardar URL ser gerada
    local ATTEMPTS=0
    local URL=""
    while [ -z "$URL" ] && [ $ATTEMPTS -lt 30 ]; do
        sleep 1
        URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG_FILE" 2>/dev/null | head -1)
        ATTEMPTS=$((ATTEMPTS + 1))
    done

    if [ -n "$URL" ]; then
        echo -e "${GREEN}✓ $NAME: $URL${NC}"
        echo "$URL"
    else
        echo -e "${RED}✗ Falha ao obter URL para $NAME${NC}"
        echo ""
    fi
}

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  INICIANDO TÚNEIS CLOUDFLARE (Quick Tunnel)${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Iniciar túneis
N8N_URL=$(start_tunnel 5678 "n8n")
EVOLUTION_URL=$(start_tunnel 8080 "evolution")

echo ""
echo -e "${GREEN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                    URLs PÚBLICAS                         ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

echo -e "  ${BLUE}n8n:${NC}       $N8N_URL"
echo -e "  ${BLUE}Evolution:${NC} $EVOLUTION_URL"
echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}  WEBHOOK URL para Evolution:${NC}"
echo -e "  ${GREEN}${N8N_URL}/webhook/whatsapp-ai${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Salvar URLs
cat > ~/hub-automacao-pro/tunnel/urls.txt << URLS
# URLs Públicas - Hub Automação Pro (Cloudflare)
# Gerado em: $(date)
# NOTA: URLs do Quick Tunnel mudam a cada reinício!

N8N_PUBLIC_URL=$N8N_URL
EVOLUTION_PUBLIC_URL=$EVOLUTION_URL
WEBHOOK_URL=${N8N_URL}/webhook/whatsapp-ai
URLS

echo -e "${GREEN}✓ URLs salvas em: ~/hub-automacao-pro/tunnel/urls.txt${NC}"
echo ""
echo -e "${YELLOW}⚠ IMPORTANTE: URLs do Quick Tunnel mudam a cada reinício!${NC}"
echo -e "${YELLOW}  Para URLs permanentes, configure um túnel com sua conta Cloudflare.${NC}"
echo ""
echo -e "${CYAN}Logs em: $LOG_DIR${NC}"
echo ""
echo -e "${YELLOW}Pressione Ctrl+C para encerrar os túneis${NC}"

# Função de cleanup
cleanup() {
    echo ""
    echo -e "${YELLOW}Encerrando túneis...${NC}"
    for PID_FILE in "$LOG_DIR"/*.pid; do
        if [ -f "$PID_FILE" ]; then
            kill $(cat "$PID_FILE") 2>/dev/null || true
            rm "$PID_FILE"
        fi
    done
    echo -e "${GREEN}✓ Túneis encerrados${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Manter script rodando
while true; do
    sleep 60
    # Verificar se túneis ainda estão ativos
    for PID_FILE in "$LOG_DIR"/*.pid; do
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if ! kill -0 $PID 2>/dev/null; then
                echo -e "${RED}⚠ Túnel caiu! Reinicie o script.${NC}"
            fi
        fi
    done
done
