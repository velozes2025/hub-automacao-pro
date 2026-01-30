import os


class Config:
    # --- Anthropic (AI) ---
    ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
    DEFAULT_MODEL = os.getenv('DEFAULT_MODEL', 'claude-sonnet-4-20250514')

    # --- OpenAI (Whisper + TTS fallback) ---
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')

    # --- ElevenLabs (Primary TTS) ---
    ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY', '')
    ELEVENLABS_VOICE_ID = os.getenv('ELEVENLABS_VOICE_ID', 'ASZKXTy56hqkRmqOqckz')  # "oliver PT-BR" - cloned voice

    # --- Evolution API (WhatsApp) ---
    EVOLUTION_API_KEY = os.getenv('EVOLUTION_API_KEY', '')
    EVOLUTION_URL = os.getenv('EVOLUTION_URL', 'http://evolution:8080')

    # --- PostgreSQL ---
    DB_HOST = os.getenv('DB_HOST', 'postgres')
    DB_PORT = int(os.getenv('DB_PORT', '5432'))
    DB_NAME = os.getenv('DB_NAME', 'hub_database')
    DB_USER = os.getenv('DB_USER', 'hub_user')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')

    # --- Application ---
    BOT_PORT = int(os.getenv('BOT_PORT', '3000'))
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    MAX_WEBHOOK_WORKERS = int(os.getenv('MAX_WEBHOOK_WORKERS', '20'))
    INTERNAL_API_KEY = os.getenv('INTERNAL_API_KEY', '')  # Secures /api/* endpoints

    # --- Retry / Workers ---
    RETRY_MAX_ATTEMPTS = 5
    RETRY_INTERVAL_SECONDS = 30
    REENGAGE_CHECK_MINUTES = 25
    REENGAGE_INTERVAL_SECONDS = 300
    LID_RESOLVE_INTERVAL_SECONDS = 30

    # --- Message ---
    MSG_SPLIT_MAX_CHARS = 800  # WhatsApp handles up to 65K; 800 = ~1 natural paragraph
    TYPING_DELAY_PER_CHAR_MS = 20
    TYPING_MIN_MS = 800
    TYPING_MAX_MS = 3000

    # --- AI Defaults ---
    DEFAULT_MAX_TOKENS = 300
    DEFAULT_MAX_TOKENS_AUDIO = 800  # v5.0: natural speech w/ hesitations, pauses, reformulations
    DEFAULT_MAX_HISTORY = 10
    MAX_TOOL_ITERATIONS = 3

    # --- Redis ---
    REDIS_URL = os.getenv('REDIS_URL', '')
    DEDUP_TTL_SECONDS = int(os.getenv('DEDUP_TTL_SECONDS', '86400'))  # 24h

    # --- Stripe (Metered Billing — structure only, no-op without key) ---
    STRIPE_API_KEY = os.getenv('STRIPE_API_KEY', '')
    STRIPE_PRICE_ID = os.getenv('STRIPE_PRICE_ID', '')
    STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', '')

    # --- Webhook Health ---
    WEBHOOK_BACKUP_URL = os.getenv('WEBHOOK_BACKUP_URL', '')
    WEBHOOK_MAX_FAILURES = int(os.getenv('WEBHOOK_MAX_FAILURES', '3'))

    # --- OLIVER.CORE v5.1 Engine ---
    ENGINE_V51_ENABLED = os.getenv('ENGINE_V51_ENABLED', 'true').lower() == 'true'
    ENGINE_V51_CACHE_ENABLED = os.getenv('ENGINE_V51_CACHE_ENABLED', 'true').lower() == 'true'
    ENGINE_V51_TOKEN_BASELINE = 1800  # avg tokens per v5.0 system prompt (for savings calc)
    ENGINE_V51_MAX_COMPRESSED_HISTORY = 3  # exchanges kept in compressed history
    DEFAULT_OLIVER_TIER = os.getenv('DEFAULT_OLIVER_TIER', 'tenant_free')

    # --- Pricing ---
    PRICING = {
        'claude-3-haiku-20240307': {'input': 0.00000025, 'output': 0.00000125},
        'claude-3-5-haiku-20241022': {'input': 0.0000008, 'output': 0.000004},
        'claude-3-5-sonnet-20241022': {'input': 0.000003, 'output': 0.000015},
        'claude-sonnet-4-20250514': {'input': 0.000003, 'output': 0.000015},
        'claude-opus-4-5-20251101': {'input': 0.000015, 'output': 0.000075},
    }


config = Config()
