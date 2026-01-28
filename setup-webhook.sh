#!/bin/bash
# Configura webhook após conectar WhatsApp

curl -s -X POST "http://localhost:8080/webhook/set/eva_bot" \
  -H "apikey: c5dd0eb4d0a4780a2816dcfb37c68020" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "http://eva-bot:3000/webhook",
    "enabled": true,
    "events": ["MESSAGES_UPSERT"]
  }'

echo ""
echo "Webhook configurado!"
