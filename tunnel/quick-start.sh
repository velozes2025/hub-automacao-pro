#!/bin/bash
# ============================================
# Hub Automação Pro - Quick Start com Túnel
# ============================================
# Script completo: sobe containers + túnel + webhook
# ============================================

set -e

cd ~/hub-automacao-pro

# Cores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

clear
echo -e "${CYAN}${BOLD}"
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║                                                                  ║"
echo "║          🚀 HUB AUTOMAÇÃO PRO - QUICK START                      ║"
echo "║                                                                  ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Menu de opções
echo -e "${YELLOW}Escolha o tipo de túnel:${NC}"
echo ""
echo "  1) Ngrok (requer conta gratuita)"
echo "  2) Cloudflare Quick Tunnel (sem conta)"
echo "  3) Apenas subir containers (sem túnel)"
echo ""
read -p "Opção [1-3]: " OPTION

case $OPTION in
    1) TUNNEL="ngrok" ;;
    2) TUNNEL="cloudflare" ;;
    3) TUNNEL="none" ;;
    *) echo -e "${RED}Opção inválida${NC}"; exit 1 ;;
esac

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  PASSO 1: Verificando containers Docker${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Verificar se Docker está rodando
if ! docker info &> /dev/null; then
    echo -e "${RED}✗ Docker não está rodando!${NC}"
    echo "  Inicie o Docker Desktop e tente novamente."
    exit 1
fi
echo -e "${GREEN}✓ Docker está rodando${NC}"

# Subir containers
echo ""
echo -e "${BLUE}Subindo containers...${NC}"
docker-compose up -d

# Aguardar containers ficarem healthy
echo ""
echo -e "${YELLOW}Aguardando serviços ficarem prontos...${NC}"
sleep 10

# Verificar status
echo ""
docker-compose ps

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  PASSO 2: Verificando serviços${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Testar n8n
if curl -s -o /dev/null -w "%{http_code}" http://localhost:5678 | grep -q "200\|401"; then
    echo -e "${GREEN}✓ n8n está rodando em http://localhost:5678${NC}"
else
    echo -e "${YELLOW}⚠ n8n ainda iniciando...${NC}"
fi

# Testar Evolution
if curl -s http://localhost:8080 | grep -q "Evolution"; then
    echo -e "${GREEN}✓ Evolution API está rodando em http://localhost:8080${NC}"
else
    echo -e "${YELLOW}⚠ Evolution ainda iniciando...${NC}"
fi

# Se não quer túnel, encerrar aqui
if [ "$TUNNEL" == "none" ]; then
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}  ✓ CONTAINERS RODANDO${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "  n8n:       http://localhost:5678  (admin/admin123)"
    echo "  Evolution: http://localhost:8080"
    echo ""
    exit 0
fi

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  PASSO 3: Iniciando túnel ($TUNNEL)${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if [ "$TUNNEL" == "ngrok" ]; then
    exec ./tunnel/start-ngrok.sh
else
    exec ./tunnel/start-cloudflare.sh
fi
