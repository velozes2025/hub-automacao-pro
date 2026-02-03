const axios = require('axios');
const config = require('../config');
const logger = require('../utils/logger');
const consumptionLogger = require('../services/consumption-logger');

class TavilyClient {
  constructor() {
    this.apiKey = config.tavily?.apiKey;
    this.baseUrl = 'https://api.tavily.com';
  }

  isConfigured() {
    return !!this.apiKey;
  }

  /**
   * Search the web for real-time information
   */
  async search(query, options = {}) {
    if (!this.isConfigured()) {
      logger.warn('[TAVILY] Not configured');
      return null;
    }

    try {
      logger.info(`[TAVILY] Searching: "${query.substring(0, 50)}..."`);

      const response = await axios.post(
        `${this.baseUrl}/search`,
        {
          api_key: this.apiKey,
          query,
          search_depth: options.depth || 'basic', // 'basic' or 'advanced'
          include_answer: true,
          include_raw_content: false,
          max_results: options.maxResults || 5,
          include_domains: options.includeDomains || [],
          exclude_domains: options.excludeDomains || [],
        },
        {
          timeout: 15000,
        }
      );

      if (response.data) {
        const result = {
          answer: response.data.answer || '',
          results: (response.data.results || []).map(r => ({
            title: r.title,
            url: r.url,
            content: r.content,
            score: r.score,
          })),
          query: response.data.query,
        };

        // Log search cost
        const depth = options.depth || 'basic';
        consumptionLogger.logWebSearch(depth).catch(e =>
          logger.debug('[COSTS] Log failed:', e.message)
        );

        logger.info(`[TAVILY] Found ${result.results.length} results`);
        return result;
      }

      return null;

    } catch (error) {
      logger.error('[TAVILY] Search error:', error.response?.data || error.message);
      return null;
    }
  }

  /**
   * Format search results for AI context
   */
  formatForContext(searchResult) {
    if (!searchResult) return '';

    let context = '';

    if (searchResult.answer) {
      context += `Resposta direta: ${searchResult.answer}\n\n`;
    }

    if (searchResult.results && searchResult.results.length > 0) {
      context += 'Fontes encontradas:\n';
      for (const r of searchResult.results.slice(0, 3)) {
        context += `- ${r.title}: ${r.content?.substring(0, 200)}...\n`;
      }
    }

    return context;
  }
}

module.exports = new TavilyClient();
