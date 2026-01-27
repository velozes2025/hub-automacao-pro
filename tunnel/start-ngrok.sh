#!/bin/bash
# ============================================
# Hub Automação Pro - Ngrok Tunnel
# ============================================
# Expõe n8n (5678) e Evolution (8080) para internet
# ============================================

set -e

# Cores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║           HUB AUTOMAÇÃO PRO - NGROK TUNNEL               ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Verificar se ngrok está instalado
if ! command -v ngrok &> /dev/null; then
    echo -e "${YELLOW}⚠ Ngrok não encontrado. Instalando...${NC}"

    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        if command -v brew &> /dev/null; then
            brew install ngrok/ngrok/ngrok
        else
            echo -e "${RED}Instale o Homebrew primeiro: https://brew.sh${NC}"
            echo "Ou baixe manualmente: https://ngrok.com/download"
            exit 1
        fi
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Linux
        curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
        echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | sudo tee /etc/apt/sources.list.d/ngrok.list
        sudo apt update && sudo apt install ngrok
    else
        echo -e "${RED}Sistema não suportado. Baixe manualmente: https://ngrok.com/download${NC}"
        exit 1
    fi
fi

# Verificar autenticação
if ! ngrok config check &> /dev/null; then
    echo -e "${YELLOW}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  CONFIGURAÇÃO NECESSÁRIA"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${NC}"
    echo "1. Crie uma conta gratuita em: https://dashboard.ngrok.com/signup"
    echo "2. Copie seu authtoken em: https://dashboard.ngrok.com/get-started/your-authtoken"
    echo "3. Execute: ngrok config add-authtoken SEU_TOKEN"
    echo ""
    read -p "Pressione ENTER após configurar o authtoken..."
fi

# Criar arquivo de configuração do ngrok
NGROK_CONFIG="$HOME/.ngrok2/hub-automacao.yml"
mkdir -p "$HOME/.ngrok2"

cat > "$NGROK_CONFIG" << 'EOF'
version: "2"
tunnels:
  n8n:
    addr: 5678
    proto: http
    inspect: true
  evolution:
    addr: 8080
    proto: http
    inspect: true
EOF

echo -e "${GREEN}✓ Configuração criada em: $NGROK_CONFIG${NC}"

# Iniciar túneis
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  INICIANDO TÚNEIS...${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Iniciar ngrok em background
ngrok start --all --config "$NGROK_CONFIG" &
NGROK_PID=$!

# Aguardar inicialização
sleep 3

# Obter URLs públicas via API local do ngrok
echo -e "${GREEN}✓ Túneis iniciados!${NC}"
echo ""

# Buscar URLs
TUNNELS=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null)

if [ -z "$TUNNELS" ]; then
    echo -e "${YELLOW}Aguardando túneis ficarem prontos...${NC}"
    sleep 3
    TUNNELS=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null)
fi

if [ -n "$TUNNELS" ]; then
    echo -e "${GREEN}"
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║                    URLs PÚBLICAS                         ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    # Extrair URLs usando grep/sed (compatível sem jq)
    N8N_URL=$(echo "$TUNNELS" | grep -o '"public_url":"[^"]*' | grep -v '8080' | head -1 | cut -d'"' -f4)
    EVOLUTION_URL=$(echo "$TUNNELS" | grep -o '"public_url":"[^"]*' | grep '8080\|evolution' | head -1 | cut -d'"' -f4)

    # Se não encontrou, tenta de outra forma
    if [ -z "$N8N_URL" ]; then
        N8N_URL=$(curl -s http://127.0.0.1:4040/api/tunnels | python3 -c "import sys,json; tunnels=json.load(sys.stdin)['tunnels']; print([t['public_url'] for t in tunnels if '5678' in t['config']['addr']][0])" 2>/dev/null || echo "Verificar em http://127.0.0.1:4040")
    fi
    if [ -z "$EVOLUTION_URL" ]; then
        EVOLUTION_URL=$(curl -s http://127.0.0.1:4040/api/tunnels | python3 -c "import sys,json; tunnels=json.load(sys.stdin)['tunnels']; print([t['public_url'] for t in tunnels if '8080' in t['config']['addr']][0])" 2>/dev/null || echo "Verificar em http://127.0.0.1:4040")
    fi

    echo -e "  ${BLUE}n8n:${NC}       $N8N_URL"
    echo -e "  ${BLUE}Evolution:${NC} $EVOLUTION_URL"
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  WEBHOOK URL para Evolution:${NC}"
    echo -e "  ${GREEN}${N8N_URL}/webhook/whatsapp-ai${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "  Dashboard Ngrok: ${BLUE}http://127.0.0.1:4040${NC}"
    echo ""

    # Salvar URLs em arquivo
    cat > ~/hub-automacao-pro/tunnel/urls.txt << URLS
# URLs Públicas - Hub Automação Pro
# Gerado em: $(date)

N8N_PUBLIC_URL=$N8N_URL
EVOLUTION_PUBLIC_URL=$EVOLUTION_URL
WEBHOOK_URL=${N8N_URL}/webhook/whatsapp-ai
URLS

    echo -e "${GREEN}✓ URLs salvas em: ~/hub-automacao-pro/tunnel/urls.txt${NC}"
fi

echo ""
echo -e "${YELLOW}Pressione Ctrl+C para encerrar os túneis${NC}"
echo ""

# Manter script rodando
wait $NGROK_PID
