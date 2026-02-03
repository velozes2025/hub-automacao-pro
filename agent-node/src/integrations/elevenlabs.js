const axios = require('axios');
const config = require('../config');
const logger = require('../utils/logger');
const consumptionLogger = require('../services/consumption-logger');

class ElevenLabsClient {
  constructor() {
    this.apiKey = config.elevenlabs.apiKey;
    this.voiceId = config.elevenlabs.voiceId;
    this.baseUrl = 'https://api.elevenlabs.io/v1';
  }

  isConfigured() {
    return !!this.apiKey;
  }

  getHeaders() {
    return {
      'xi-api-key': this.apiKey,
      'Content-Type': 'application/json',
    };
  }

  async textToSpeech(text, voiceId = null) {
    if (!this.isConfigured()) {
      logger.warn('ElevenLabs not configured');
      return null;
    }

    try {
      const response = await axios.post(
        `${this.baseUrl}/text-to-speech/${voiceId || this.voiceId}`,
        {
          text,
          model_id: 'eleven_multilingual_v2',
          voice_settings: {
            stability: 0.5,
            similarity_boost: 0.6,
            style: 0.3,
            use_speaker_boost: false,
          },
        },
        {
          headers: this.getHeaders(),
          responseType: 'arraybuffer',
        }
      );

      // Log cost
      consumptionLogger.logTTS('eleven_multilingual_v2', text.length).catch(e =>
        logger.debug('[COSTS] Log failed:', e.message)
      );

      logger.debug('Audio generated successfully');
      return Buffer.from(response.data);

    } catch (error) {
      // Handle arraybuffer error response
      let errorMsg = error.message;
      if (error.response?.data) {
        if (Buffer.isBuffer(error.response.data) || error.response.data instanceof ArrayBuffer) {
          try {
            errorMsg = Buffer.from(error.response.data).toString('utf8');
          } catch (e) {
            errorMsg = `Status ${error.response.status}`;
          }
        } else {
          errorMsg = JSON.stringify(error.response.data);
        }
      }
      logger.error('ElevenLabs error:', errorMsg);

      // Fallback to OpenAI TTS if ElevenLabs fails
      logger.info('[TTS] Trying OpenAI TTS fallback...');
      return this.openAITTS(text);
    }
  }

  /**
   * OpenAI TTS fallback
   */
  async openAITTS(text) {
    try {
      const openaiKey = require('../config').openai.apiKey;
      if (!openaiKey) {
        throw new Error('OpenAI not configured');
      }

      const response = await axios.post(
        'https://api.openai.com/v1/audio/speech',
        {
          model: 'tts-1-hd', // HD model for more natural voice
          input: text.substring(0, 4096), // OpenAI limit
          voice: 'echo', // Echo: masculine, warm, friendly
          response_format: 'opus',
          speed: 1.0,
        },
        {
          headers: {
            'Authorization': `Bearer ${openaiKey}`,
            'Content-Type': 'application/json',
          },
          responseType: 'arraybuffer',
        }
      );

      // Log OpenAI TTS-HD cost ($30/1M chars)
      consumptionLogger.log({
        operation: 'tts',
        model: 'tts-1-hd',
        inputTokens: text.length,
        outputTokens: 0,
        cost: text.length * 0.00003,
        metadata: { provider: 'openai', voice: 'echo' },
      }).catch(e => logger.debug('[COSTS] Log failed:', e.message));

      logger.info('[TTS] OpenAI fallback successful');
      return Buffer.from(response.data);

    } catch (fallbackError) {
      logger.error('[TTS] OpenAI fallback failed:', fallbackError.message);
      throw new Error('Both ElevenLabs and OpenAI TTS failed');
    }
  }

  async getVoices() {
    if (!this.isConfigured()) {
      return [];
    }

    try {
      const response = await axios.get(`${this.baseUrl}/voices`, {
        headers: this.getHeaders(),
      });

      return response.data.voices || [];

    } catch (error) {
      logger.error('ElevenLabs voices error:', error.response?.data || error.message);
      return [];
    }
  }

  async getUsage() {
    if (!this.isConfigured()) {
      return null;
    }

    try {
      const response = await axios.get(`${this.baseUrl}/user/subscription`, {
        headers: this.getHeaders(),
      });

      return {
        characterCount: response.data.character_count,
        characterLimit: response.data.character_limit,
        remainingCharacters: response.data.character_limit - response.data.character_count,
      };

    } catch (error) {
      logger.error('ElevenLabs usage error:', error.response?.data || error.message);
      return null;
    }
  }
}

module.exports = new ElevenLabsClient();
