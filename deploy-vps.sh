#!/bin/bash
# Deploy Hub Automacao Pro em VPS
# Testado em Ubuntu 22.04 / Debian 12

set -e

echo "=== 1. Atualizando sistema ==="
apt update && apt upgrade -y

echo "=== 2. Instalando Docker ==="
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker

echo "=== 3. Instalando Docker Compose ==="
apt install -y docker-compose-plugin

echo "=== 4. Clonando repositorio ==="
cd /opt
if [ -d "hub-automacao-pro" ]; then
    echo "Repositorio ja existe, atualizando..."
    cd hub-automacao-pro
    git pull
else
    git clone https://github.com/velozes2025/hub-automacao-pro.git
    cd hub-automacao-pro
fi

echo "=== 5. Configurando .env ==="
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "ATENCAO: Edite o arquivo .env com suas chaves de API!"
    echo "  nano /opt/hub-automacao-pro/.env"
    echo ""
    echo "Variaveis obrigatorias:"
    echo "  - ANTHROPIC_API_KEY (sua chave da Anthropic)"
    echo "  - EVOLUTION_API_KEY (chave para Evolution API)"
    echo "  - EVOLUTION_SERVER_URL (http://SEU_IP_PUBLICO:8080)"
    echo "  - POSTGRES_PASSWORD (senha do banco)"
    echo ""
    read -p "Edite o .env e pressione ENTER para continuar..."
else
    echo ".env ja existe, mantendo configuracao atual."
fi

echo "=== 6. Subindo containers ==="
docker compose up -d --build

echo "=== 7. Aguardando servicos ==="
sleep 30

echo "=== 8. Criando instancia WhatsApp ==="
# Le a chave do .env
EVOLUTION_KEY=$(grep EVOLUTION_API_KEY .env | head -1 | cut -d'=' -f2)
curl -s -X POST "http://localhost:8080/instance/create" \
  -H "apikey: ${EVOLUTION_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"instanceName": "eva_bot", "qrcode": true}'

SERVER_IP=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')

echo ""
echo "=== DEPLOY CONCLUIDO ==="
echo ""
echo "Acesse:"
echo "  - Evolution API: http://${SERVER_IP}:8080"
echo "  - Hub Bot:       http://${SERVER_IP}:3000/webhook"
echo "  - Admin Panel:   http://${SERVER_IP}:9615"
echo ""
echo "Proximo passo:"
echo "  1. Acesse http://${SERVER_IP}:8080/manager"
echo "  2. Escaneie QR code para conectar WhatsApp"
echo "  3. Configure webhook da instancia para http://hub-bot:3000/webhook"
echo ""
