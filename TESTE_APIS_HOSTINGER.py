#!/usr/bin/env python3
"""
TESTE DE APIs - Hub Automacao Pro
Execute este script na Hostinger para verificar se todas as APIs estao funcionando.
"""

import os
import sys
import json
import base64
import requests
from datetime import datetime

# Cores para output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
RESET = '\033[0m'

def ok(msg):
    print(f"{GREEN}[OK]{RESET} {msg}")

def fail(msg):
    print(f"{RED}[FALHA]{RESET} {msg}")

def warn(msg):
    print(f"{YELLOW}[AVISO]{RESET} {msg}")

def test_divider(name):
    print(f"\n{'='*50}")
    print(f"TESTANDO: {name}")
    print('='*50)

# ============================================
# CONFIGURACOES (copie do .env)
# ============================================
CONFIG = {
    "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", "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"),
    "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", "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"),
    "ELEVENLABS_API_KEY": os.getenv("ELEVENLABS_API_KEY", "sk_fb543f367f06c3f30b6e0695ee8e4c1acb8451a89cbb8949"),
    "ELEVENLABS_VOICE_ID": os.getenv("ELEVENLABS_VOICE_ID", "2Z9f0UOViiovFhMVDC7M"),
    "AIRTABLE_API_KEY": os.getenv("AIRTABLE_API_KEY", "pat0uFIrmEjYAELDQ.83d5f560a295377d24a4047014793fce8ff4e1705821b25360fc74e2a0966f60"),
    "AIRTABLE_BASE_ID": os.getenv("AIRTABLE_BASE_ID", "appe52kmG53A4Eh2l"),
    "TAVILY_API_KEY": os.getenv("TAVILY_API_KEY", "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"),
    "EVOLUTION_API_KEY": os.getenv("EVOLUTION_API_KEY", "d0ea32d2a3314539063b931f895d05baf725dabf429fab04"),
    "EVOLUTION_URL": os.getenv("EVOLUTION_SERVER_URL", "http://104.248.180.81:8080"),
    "DATABASE_URL": os.getenv("DATABASE_URL", "postgresql://postgres:JdvdwoDdNrxkIRYhOfTsOEjyBpZodwux@interchange.proxy.rlwy.net:57498/railway"),
}

results = {}

# ============================================
# TESTE 1: OpenAI (Chat + TTS)
# ============================================
def test_openai():
    test_divider("OpenAI API (GPT-4o + TTS)")

    # Teste Chat
    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {CONFIG['OPENAI_API_KEY']}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Diga apenas: teste ok"}],
                "max_tokens": 10
            },
            timeout=30
        )
        if response.status_code == 200:
            ok(f"Chat GPT-4o funcionando")
            results["openai_chat"] = True
        else:
            fail(f"Chat falhou: {response.status_code} - {response.text[:100]}")
            results["openai_chat"] = False
    except Exception as e:
        fail(f"Chat erro: {e}")
        results["openai_chat"] = False

    # Teste TTS
    try:
        response = requests.post(
            "https://api.openai.com/v1/audio/speech",
            headers={
                "Authorization": f"Bearer {CONFIG['OPENAI_API_KEY']}",
                "Content-Type": "application/json"
            },
            json={
                "model": "tts-1",
                "input": "Teste de audio",
                "voice": "nova"
            },
            timeout=30
        )
        if response.status_code == 200:
            ok(f"TTS OpenAI funcionando ({len(response.content)} bytes de audio)")
            results["openai_tts"] = True
        else:
            fail(f"TTS falhou: {response.status_code}")
            results["openai_tts"] = False
    except Exception as e:
        fail(f"TTS erro: {e}")
        results["openai_tts"] = False

# ============================================
# TESTE 2: Anthropic Claude
# ============================================
def test_anthropic():
    test_divider("Anthropic Claude API")

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": CONFIG['ANTHROPIC_API_KEY'],
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "Diga apenas: ok"}]
            },
            timeout=30
        )
        if response.status_code == 200:
            ok("Claude API funcionando")
            results["anthropic"] = True
        else:
            fail(f"Claude falhou: {response.status_code} - {response.text[:100]}")
            results["anthropic"] = False
    except Exception as e:
        fail(f"Claude erro: {e}")
        results["anthropic"] = False

# ============================================
# TESTE 3: ElevenLabs (Voz do Oliver)
# ============================================
def test_elevenlabs():
    test_divider("ElevenLabs TTS (Voz do Oliver)")

    try:
        response = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{CONFIG['ELEVENLABS_VOICE_ID']}",
            headers={
                "xi-api-key": CONFIG['ELEVENLABS_API_KEY'],
                "Content-Type": "application/json"
            },
            json={
                "text": "Ola, eu sou o Oliver",
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
            },
            timeout=30
        )
        if response.status_code == 200:
            ok(f"ElevenLabs funcionando ({len(response.content)} bytes de audio)")
            results["elevenlabs"] = True
        else:
            fail(f"ElevenLabs falhou: {response.status_code} - {response.text[:100]}")
            results["elevenlabs"] = False
    except Exception as e:
        fail(f"ElevenLabs erro: {e}")
        results["elevenlabs"] = False

# ============================================
# TESTE 4: Airtable CRM
# ============================================
def test_airtable():
    test_divider("Airtable CRM")

    try:
        response = requests.get(
            f"https://api.airtable.com/v0/{CONFIG['AIRTABLE_BASE_ID']}/Leads?maxRecords=1",
            headers={
                "Authorization": f"Bearer {CONFIG['AIRTABLE_API_KEY']}"
            },
            timeout=15
        )
        if response.status_code == 200:
            data = response.json()
            records = len(data.get('records', []))
            ok(f"Airtable funcionando ({records} registro(s) encontrado(s))")
            results["airtable"] = True
        else:
            fail(f"Airtable falhou: {response.status_code} - {response.text[:100]}")
            results["airtable"] = False
    except Exception as e:
        fail(f"Airtable erro: {e}")
        results["airtable"] = False

# ============================================
# TESTE 5: Tavily Web Search
# ============================================
def test_tavily():
    test_divider("Tavily Web Search")

    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": CONFIG['TAVILY_API_KEY'],
                "query": "teste",
                "max_results": 1
            },
            timeout=15
        )
        if response.status_code == 200:
            ok("Tavily funcionando")
            results["tavily"] = True
        else:
            fail(f"Tavily falhou: {response.status_code}")
            results["tavily"] = False
    except Exception as e:
        fail(f"Tavily erro: {e}")
        results["tavily"] = False

# ============================================
# TESTE 6: Evolution API (WhatsApp)
# ============================================
def test_evolution():
    test_divider("Evolution API (WhatsApp)")

    try:
        response = requests.get(
            f"{CONFIG['EVOLUTION_URL']}/instance/fetchInstances",
            headers={"apikey": CONFIG['EVOLUTION_API_KEY']},
            timeout=15
        )
        if response.status_code == 200:
            instances = response.json()
            ok(f"Evolution API funcionando ({len(instances)} instancia(s))")
            for inst in instances:
                name = inst.get('instance', {}).get('instanceName', 'unknown')
                state = inst.get('instance', {}).get('state', 'unknown')
                print(f"    -> {name}: {state}")
            results["evolution"] = True
        else:
            fail(f"Evolution falhou: {response.status_code}")
            results["evolution"] = False
    except Exception as e:
        fail(f"Evolution erro: {e}")
        results["evolution"] = False

# ============================================
# TESTE 7: PostgreSQL
# ============================================
def test_postgres():
    test_divider("PostgreSQL Database")

    try:
        import psycopg2
        conn = psycopg2.connect(CONFIG['DATABASE_URL'])
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM conversations")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        ok(f"PostgreSQL funcionando ({count} conversas no banco)")
        results["postgres"] = True
    except ImportError:
        warn("psycopg2 nao instalado. Instale: pip install psycopg2-binary")
        results["postgres"] = None
    except Exception as e:
        fail(f"PostgreSQL erro: {e}")
        results["postgres"] = False

# ============================================
# RESUMO FINAL
# ============================================
def print_summary():
    print("\n" + "="*50)
    print("RESUMO DOS TESTES")
    print("="*50)

    passed = 0
    failed = 0
    skipped = 0

    for name, status in results.items():
        if status is True:
            print(f"{GREEN}[OK]{RESET} {name}")
            passed += 1
        elif status is False:
            print(f"{RED}[FALHA]{RESET} {name}")
            failed += 1
        else:
            print(f"{YELLOW}[PULADO]{RESET} {name}")
            skipped += 1

    print("\n" + "-"*50)
    print(f"Total: {passed} OK | {failed} FALHA | {skipped} PULADO")

    if failed == 0:
        print(f"\n{GREEN}TODAS AS APIs FUNCIONANDO! Pode integrar com OpenClaw.{RESET}")
    else:
        print(f"\n{RED}ATENCAO: {failed} API(s) com problema. Verifique antes de integrar.{RESET}")

# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    print("\n" + "="*50)
    print("HUB AUTOMACAO PRO - TESTE DE APIs")
    print(f"Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*50)

    test_openai()
    test_anthropic()
    test_elevenlabs()
    test_airtable()
    test_tavily()
    test_evolution()
    test_postgres()

    print_summary()
