const axios = require('axios');
const config = require('../config');
const logger = require('../utils/logger');
const consumptionLogger = require('../services/consumption-logger');

class OpenAIClient {
  constructor() {
    this.apiKey = config.openai.apiKey;
    this.model = config.openai.model;
    this.baseUrl = 'https://api.openai.com/v1';
  }

  isConfigured() {
    return !!this.apiKey;
  }

  getHeaders() {
    return {
      'Authorization': `Bearer ${this.apiKey}`,
      'Content-Type': 'application/json',
    };
  }

  async chat(messages, systemPrompt = null) {
    if (!this.isConfigured()) {
      throw new Error('OpenAI not configured');
    }

    try {
      const formattedMessages = [];

      if (systemPrompt) {
        formattedMessages.push({ role: 'system', content: systemPrompt });
      }

      formattedMessages.push(...messages.map(m => ({
        role: m.role,
        content: m.content,
      })));

      const response = await axios.post(`${this.baseUrl}/chat/completions`, {
        model: this.model,
        messages: formattedMessages,
        max_tokens: 1024,
      }, {
        headers: this.getHeaders(),
      });

      // Log token usage for cost tracking
      const usage = response.data.usage;
      if (usage) {
        consumptionLogger.logChat(
          this.model,
          usage.prompt_tokens || 0,
          usage.completion_tokens || 0
        ).catch(e => logger.debug('[COSTS] Log failed:', e.message));
      }

      return response.data.choices[0]?.message?.content || '';

    } catch (error) {
      logger.error('OpenAI API error:', error.response?.data || error.message);
      throw new Error('Failed to generate OpenAI response');
    }
  }

  async createEmbedding(text) {
    if (!this.isConfigured()) {
      throw new Error('OpenAI not configured');
    }

    try {
      const response = await axios.post(`${this.baseUrl}/embeddings`, {
        model: 'text-embedding-3-small',
        input: text,
      }, {
        headers: this.getHeaders(),
      });

      return response.data.data[0]?.embedding || [];

    } catch (error) {
      logger.error('OpenAI embedding error:', error.response?.data || error.message);
      throw new Error('Failed to create embedding');
    }
  }

  async transcribeAudio(audioBuffer, filename = 'audio.ogg') {
    if (!this.isConfigured()) {
      throw new Error('OpenAI not configured');
    }

    try {
      const FormData = require('form-data');
      const form = new FormData();
      form.append('file', audioBuffer, { filename });
      form.append('model', 'whisper-1');
      form.append('language', 'pt');

      const response = await axios.post(`${this.baseUrl}/audio/transcriptions`, form, {
        headers: {
          ...form.getHeaders(),
          'Authorization': `Bearer ${this.apiKey}`,
        },
      });

      // Estimate audio duration from buffer size (OGG Opus ~16kbps = 2KB/second)
      const estimatedSeconds = Math.max(audioBuffer.length / 2000, 1);
      consumptionLogger.logTranscription(estimatedSeconds).catch(e =>
        logger.debug('[COSTS] Log failed:', e.message)
      );

      return response.data.text || '';

    } catch (error) {
      logger.error('OpenAI transcription error:', error.response?.data || error.message);
      throw new Error('Failed to transcribe audio');
    }
  }
}

module.exports = new OpenAIClient();
