import os

ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
EVOLUTION_API_KEY = os.getenv('EVOLUTION_API_KEY')
EVOLUTION_URL = os.getenv('EVOLUTION_URL', 'http://evolution:8080')

DB_HOST = os.getenv('DB_HOST', 'postgres')
DB_PORT = int(os.getenv('DB_PORT', '5432'))
DB_NAME = os.getenv('DB_NAME', 'hub_database')
DB_USER = os.getenv('DB_USER', 'hub_user')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
