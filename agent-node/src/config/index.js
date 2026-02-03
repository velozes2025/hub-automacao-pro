module.exports = {
  nodeEnv: process.env.NODE_ENV || 'development',
  port: parseInt(process.env.PORT, 10) || 3100,
  timezone: process.env.TIMEZONE || 'America/Sao_Paulo',
  adminNumber: process.env.ADMIN_NUMBER || '',

  sqlite: {
    path: process.env.SQLITE_PATH || './data/agent.db',
  },

  anthropic: {
    apiKey: process.env.ANTHROPIC_API_KEY,
    model: process.env.DEFAULT_MODEL || 'claude-sonnet-4-20250514',
    maxTokens: parseInt(process.env.ANTHROPIC_MAX_TOKENS, 10) || 1024,
  },

  openai: {
    apiKey: process.env.OPENAI_API_KEY,
    model: process.env.OPENAI_MODEL || 'gpt-4o',
  },

  evolution: {
    url: process.env.EVOLUTION_URL || 'http://localhost:8080',
    apiKey: process.env.EVOLUTION_API_KEY,
  },

  google: {
    calendarId: process.env.GOOGLE_CALENDAR_ID || 'primary',
    serviceAccountJson: process.env.GOOGLE_SERVICE_ACCOUNT_JSON,
  },

  airtable: {
    apiKey: process.env.AIRTABLE_API_KEY,
    baseId: process.env.AIRTABLE_BASE_ID,
  },

  gmail: {
    user: process.env.GMAIL_USER,
    appPassword: process.env.GMAIL_APP_PASSWORD,
    displayName: process.env.GMAIL_DISPLAY_NAME || 'Hub Automacao',
  },

  elevenlabs: {
    apiKey: process.env.ELEVENLABS_API_KEY,
    voiceId: process.env.ELEVENLABS_VOICE_ID || 'ASZKXTy56hqkRmqOqckz',
  },

  tavily: {
    apiKey: process.env.TAVILY_API_KEY,
  },

  memory: {
    maxHistoryMessages: 50,
    summaryThreshold: 20,
  },
};
