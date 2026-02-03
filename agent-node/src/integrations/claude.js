const Anthropic = require('@anthropic-ai/sdk');
const config = require('../config');
const logger = require('../utils/logger');

class ClaudeClient {
  constructor() {
    this.client = new Anthropic({
      apiKey: config.anthropic.apiKey,
    });
  }

  async chat(messages, systemPrompt = null) {
    try {
      const response = await this.client.messages.create({
        model: config.anthropic.model,
        max_tokens: config.anthropic.maxTokens,
        system: systemPrompt || undefined,
        messages: messages.map(m => ({
          role: m.role,
          content: m.content,
        })),
      });

      const textContent = response.content.find(c => c.type === 'text');
      return textContent?.text || '';

    } catch (error) {
      logger.error('Claude API error:', error);
      throw new Error('Failed to generate AI response');
    }
  }
}

module.exports = new ClaudeClient();
