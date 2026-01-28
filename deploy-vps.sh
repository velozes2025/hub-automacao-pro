#!/bin/bash
# Deploy Hub Automação Pro em VPS
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

echo "=== 4. Clonando repositório ==="
cd /opt
git clone https://github.com/velozes2025/hub-automacao-pro.git
cd hub-automacao-pro

echo "=== 5. Criando arquivo .env ==="
cat > .env << 'ENVFILE'
# Anthropic
ANTHROPIC_API_KEY=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

# Evolution API
EVOLUTION_API_KEY=c5dd0eb4d0a4780a2816dcfb37c68020

# PostgreSQL
POSTGRES_USER=hub_user
POSTGRES_PASSWORD=hub_secret_2024
POSTGRES_DB=hub_database

# n8n
N8N_USER=admin
N8N_PASSWORD=admin123

# Timezone
TIMEZONE=America/Sao_Paulo
ENVFILE

echo "=== 6. Subindo containers ==="
docker compose up -d

echo "=== 7. Aguardando serviços ==="
sleep 30

echo "=== 8. Criando instância WhatsApp ==="
curl -s -X POST "http://localhost:8080/instance/create" \
  -H "apikey: c5dd0eb4d0a4780a2816dcfb37c68020" \
  -H "Content-Type: application/json" \
  -d '{"instanceName": "eva_bot", "qrcode": true}'

echo ""
echo "=== DEPLOY CONCLUÍDO ==="
echo ""
echo "Acesse:"
echo "  - Evolution API: http://SEU_IP:8080"
echo "  - n8n: http://SEU_IP:5678"
echo "  - Bot webhook: http://SEU_IP:3000/webhook"
echo ""
echo "Próximo passo:"
echo "  1. Acesse http://SEU_IP:8080/manager"
echo "  2. Escaneie QR code para conectar WhatsApp"
echo "  3. Configure webhook da instância para http://eva-bot:3000/webhook"
echo ""
