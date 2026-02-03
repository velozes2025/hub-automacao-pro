const axios = require('axios');
const config = require('../config');
const logger = require('../utils/logger');
const lidResolver = require('../services/lid-resolver');

class EvolutionClient {
  constructor() {
    this.baseUrl = config.evolution.url;
    this.apiKey = config.evolution.apiKey;
  }

  getHeaders() {
    return {
      'Content-Type': 'application/json',
      'apikey': this.apiKey,
    };
  }

  /**
   * Send a text message with LID resolution
   */
  async sendMessage(instance, remoteJid, text) {
    try {
      // Resolve LID to phone number if needed
      const destinationJid = await lidResolver.getDestinationJid(instance, remoteJid);

      logger.info(`[SEND] Instance: ${instance}, To: ${destinationJid}`);

      const url = `${this.baseUrl}/message/sendText/${instance}`;

      const response = await axios.post(url, {
        number: destinationJid,
        text: text,
      }, {
        headers: this.getHeaders(),
        timeout: 15000,
      });

      if (response.status === 200 || response.status === 201) {
        logger.info(`[OK] Message sent to ${destinationJid}`);
        return response.data;
      }

      // Fallback: try with textMessage wrapper
      logger.warn(`First attempt failed, trying textMessage wrapper...`);
      const fallbackResponse = await axios.post(url, {
        number: destinationJid,
        textMessage: { text: text },
      }, {
        headers: this.getHeaders(),
        timeout: 15000,
      });

      if (fallbackResponse.status === 200 || fallbackResponse.status === 201) {
        logger.info(`[OK] Message sent via fallback to ${destinationJid}`);
        return fallbackResponse.data;
      }

      throw new Error(`Unexpected status: ${fallbackResponse.status}`);

    } catch (error) {
      const errorMsg = error.response?.data?.message || error.response?.data || error.message;
      logger.error(`[FAIL] Send message error: ${JSON.stringify(errorMsg)}`);
      throw new Error(`Failed to send message: ${JSON.stringify(errorMsg)}`);
    }
  }

  /**
   * Send an audio message (voice note)
   */
  async sendAudio(instance, remoteJid, base64Audio) {
    try {
      const destinationJid = await lidResolver.getDestinationJid(instance, remoteJid);

      logger.info(`[SEND AUDIO] Instance: ${instance}, To: ${destinationJid}`);

      const url = `${this.baseUrl}/message/sendWhatsAppAudio/${instance}`;

      const response = await axios.post(url, {
        number: destinationJid,
        audio: base64Audio,
      }, {
        headers: this.getHeaders(),
        timeout: 30000,
      });

      if (response.status === 200 || response.status === 201) {
        logger.info(`[OK] Audio sent to ${destinationJid}`);
        return response.data;
      }

      throw new Error(`Unexpected status: ${response.status}`);

    } catch (error) {
      const errorMsg = error.response?.data?.message || error.response?.data || error.message;
      logger.error(`[FAIL] Send audio error: ${JSON.stringify(errorMsg)}`);
      throw new Error(`Failed to send audio: ${JSON.stringify(errorMsg)}`);
    }
  }

  /**
   * Send media (image, video, document)
   */
  async sendMedia(instance, remoteJid, mediaUrl, caption = '', mediaType = 'image') {
    try {
      const destinationJid = await lidResolver.getDestinationJid(instance, remoteJid);

      logger.info(`[SEND MEDIA] Instance: ${instance}, To: ${destinationJid}, Type: ${mediaType}`);

      const url = `${this.baseUrl}/message/sendMedia/${instance}`;

      const response = await axios.post(url, {
        number: destinationJid,
        mediatype: mediaType,
        media: mediaUrl,
        caption: caption,
      }, {
        headers: this.getHeaders(),
        timeout: 30000,
      });

      if (response.status === 200 || response.status === 201) {
        logger.info(`[OK] Media sent to ${destinationJid}`);
        return response.data;
      }

      throw new Error(`Unexpected status: ${response.status}`);

    } catch (error) {
      const errorMsg = error.response?.data?.message || error.response?.data || error.message;
      logger.error(`[FAIL] Send media error: ${JSON.stringify(errorMsg)}`);
      throw new Error(`Failed to send media: ${JSON.stringify(errorMsg)}`);
    }
  }

  /**
   * Set typing indicator
   */
  async setTyping(instance, remoteJid, isTyping = true) {
    try {
      const destinationJid = await lidResolver.getDestinationJid(instance, remoteJid);

      await axios.post(
        `${this.baseUrl}/chat/updatePresence/${instance}`,
        {
          number: destinationJid,
          presence: isTyping ? 'composing' : 'paused',
        },
        {
          headers: this.getHeaders(),
          timeout: 5000,
        }
      );

      logger.debug(`Typing ${isTyping ? 'started' : 'stopped'} for ${destinationJid}`);
    } catch (error) {
      // Non-critical, just log
      logger.debug(`Typing indicator failed: ${error.message}`);
    }
  }

  /**
   * Download media as base64
   */
  async getBase64Media(instance, messageKey) {
    try {
      const response = await axios.post(
        `${this.baseUrl}/chat/getBase64FromMediaMessage/${instance}`,
        { message: { key: messageKey } },
        {
          headers: this.getHeaders(),
          timeout: 30000,
        }
      );

      if (response.status === 200 || response.status === 201) {
        logger.info(`[OK] Media downloaded`);
        return response.data.base64 || '';
      }

      return '';
    } catch (error) {
      logger.error(`[FAIL] Media download: ${error.message}`);
      return '';
    }
  }

  /**
   * Get instance connection status
   */
  async getInstanceStatus(instance) {
    try {
      const response = await axios.get(
        `${this.baseUrl}/instance/connectionState/${instance}`,
        { headers: this.getHeaders(), timeout: 5000 }
      );

      const state = response.data?.instance?.state || 'unknown';
      logger.debug(`Instance ${instance} state: ${state}`);
      return state;

    } catch (error) {
      logger.error(`Instance status error: ${error.message}`);
      return 'error';
    }
  }

  /**
   * Fetch all contacts for LID resolution
   */
  async fetchContacts(instance) {
    try {
      const response = await axios.post(
        `${this.baseUrl}/chat/findContacts/${instance}`,
        {},
        { headers: this.getHeaders(), timeout: 10000 }
      );

      return response.data || [];
    } catch (error) {
      logger.error(`Fetch contacts error: ${error.message}`);
      return [];
    }
  }
}

module.exports = new EvolutionClient();
