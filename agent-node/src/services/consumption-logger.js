/**
 * Consumption Logger Service
 * Logs API costs to PostgreSQL for dashboard tracking
 */
const { Pool } = require('pg');
const logger = require('../utils/logger');

// Cost pricing (as of 2024)
const PRICING = {
  // OpenAI GPT-4o
  'gpt-4o': { input: 5.00 / 1000000, output: 15.00 / 1000000 },
  'gpt-4o-mini': { input: 0.15 / 1000000, output: 0.60 / 1000000 },

  // Whisper (per minute of audio)
  'whisper-1': { per_minute: 0.006 },

  // ElevenLabs TTS (per character)
  'eleven_multilingual_v2': { per_char: 0.00003 },

  // Tavily Search
  'tavily-basic': { per_search: 0.001 },
  'tavily-advanced': { per_search: 0.002 },
};

class ConsumptionLogger {
  constructor() {
    this.pool = null;
    this.defaultTenantId = process.env.DEFAULT_TENANT_ID || '00000000-0000-0000-0000-000000000001';
    this.enabled = !!process.env.DATABASE_URL;
  }

  async init() {
    if (!process.env.DATABASE_URL) {
      logger.warn('[COSTS] No DATABASE_URL - cost logging disabled');
      return;
    }

    try {
      this.pool = new Pool({
        connectionString: process.env.DATABASE_URL,
        ssl: process.env.DATABASE_URL.includes('railway') ? { rejectUnauthorized: false } : false,
        max: 3,
        idleTimeoutMillis: 30000,
        connectionTimeoutMillis: 5000,
      });

      // Test connection
      const client = await this.pool.connect();
      await client.query('SELECT 1');
      client.release();

      logger.info('[COSTS] PostgreSQL connection established');
      this.enabled = true;
    } catch (error) {
      logger.warn('[COSTS] PostgreSQL connection failed:', error.message);
      this.enabled = false;
    }
  }

  /**
   * Log AI chat usage (OpenAI)
   */
  async logChat(model, inputTokens, outputTokens, conversationId = null) {
    const pricing = PRICING[model] || PRICING['gpt-4o'];
    const cost = (inputTokens * pricing.input) + (outputTokens * pricing.output);

    return this.log({
      operation: 'chat',
      model,
      inputTokens,
      outputTokens,
      cost,
      conversationId,
      metadata: { provider: 'openai' },
    });
  }

  /**
   * Log TTS usage (ElevenLabs)
   */
  async logTTS(model, characters, conversationId = null) {
    const pricing = PRICING[model] || PRICING['eleven_multilingual_v2'];
    const cost = characters * pricing.per_char;

    return this.log({
      operation: 'tts',
      model,
      inputTokens: characters,
      outputTokens: 0,
      cost,
      conversationId,
      metadata: { provider: 'elevenlabs', chars: characters },
    });
  }

  /**
   * Log transcription usage (Whisper)
   */
  async logTranscription(audioLengthSeconds, conversationId = null) {
    const minutes = audioLengthSeconds / 60;
    const cost = minutes * PRICING['whisper-1'].per_minute;

    return this.log({
      operation: 'transcription',
      model: 'whisper-1',
      inputTokens: Math.round(audioLengthSeconds),
      outputTokens: 0,
      cost,
      conversationId,
      metadata: { provider: 'openai', duration_seconds: audioLengthSeconds },
    });
  }

  /**
   * Log web search usage (Tavily)
   */
  async logWebSearch(depth = 'basic', conversationId = null) {
    const model = `tavily-${depth}`;
    const pricing = PRICING[model] || PRICING['tavily-basic'];
    const cost = pricing.per_search;

    return this.log({
      operation: 'web_search',
      model,
      inputTokens: 1,
      outputTokens: 0,
      cost,
      conversationId,
      metadata: { provider: 'tavily', depth },
    });
  }

  /**
   * Base logging function
   */
  async log({ operation, model, inputTokens, outputTokens, cost, conversationId, metadata }) {
    if (!this.enabled || !this.pool) {
      return false;
    }

    try {
      const metaJson = JSON.stringify(metadata || {});

      await this.pool.query(
        `INSERT INTO consumption_logs
         (tenant_id, conversation_id, model, input_tokens, output_tokens, cost, operation, metadata)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
        [this.defaultTenantId, conversationId, model, inputTokens, outputTokens, cost, operation, metaJson]
      );

      logger.debug(`[COSTS] Logged ${operation}: $${cost.toFixed(6)} (${model})`);
      return true;
    } catch (error) {
      logger.error('[COSTS] Logging failed:', error.message);
      return false;
    }
  }

  async close() {
    if (this.pool) {
      await this.pool.end();
      this.pool = null;
    }
  }
}

// Singleton instance
const consumptionLogger = new ConsumptionLogger();

module.exports = consumptionLogger;
