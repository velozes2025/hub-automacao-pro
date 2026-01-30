import os


class Config:
    # --- Anthropic (AI) ---
    ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
    DEFAULT_MODEL = os.getenv('DEFAULT_MODEL', 'claude-sonnet-4-20250514')

    # --- OpenAI (Whisper) ---
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')

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
    MSG_SPLIT_MAX_CHARS = 200
    TYPING_DELAY_PER_CHAR_MS = 20
    TYPING_MIN_MS = 800
    TYPING_MAX_MS = 3000

    # --- AI Defaults ---
    DEFAULT_MAX_TOKENS = 150
    DEFAULT_MAX_HISTORY = 10
    MAX_TOOL_ITERATIONS = 3

    # --- Pricing ---
    PRICING = {
        'claude-3-haiku-20240307': {'input': 0.00000025, 'output': 0.00000125},
        'claude-3-5-haiku-20241022': {'input': 0.0000008, 'output': 0.000004},
        'claude-3-5-sonnet-20241022': {'input': 0.000003, 'output': 0.000015},
        'claude-sonnet-4-20250514': {'input': 0.000003, 'output': 0.000015},
        'claude-opus-4-5-20251101': {'input': 0.000015, 'output': 0.000075},
    }


config = Config()
