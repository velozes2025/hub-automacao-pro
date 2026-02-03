const express = require('express');
const router = express.Router();
const { handleMessage, handleAudioMessage, handleAdminMessage } = require('../../services/message-handler');
const lidResolver = require('../../services/lid-resolver');
const logger = require('../../utils/logger');
const config = require('../../config');

router.post('/', async (req, res) => {
  try {
    const { event, data, instance, sender } = req.body;

    // Evolution API v2 sends instance name in different fields
    const instanceName = instance || sender || req.body.instanceName || 'teste-instance';

    // Handle different event types
    if (event === 'contacts.upsert' || event === 'contacts.update') {
      // Learn LID mappings from contact events
      const contacts = Array.isArray(data) ? data : [data];
      for (const contact of contacts) {
        lidResolver.learnFromContact(contact);
      }
      return res.json({ status: 'contacts processed' });
    }

    // Only process incoming messages
    if (event !== 'messages.upsert') {
      return res.json({ status: 'ignored', reason: 'not a message event' });
    }

    // Extract message data
    const messageData = data?.message || data;
    const key = data?.key || messageData?.key;

    if (!key?.remoteJid) {
      return res.status(400).json({ error: 'Missing remoteJid' });
    }

    // Check for admin commands (fromMe messages)
    if (key.fromMe && config.adminNumber) {
      const msgContent = messageData?.message || messageData;
      const text = msgContent?.conversation || msgContent?.extendedTextMessage?.text || '';
      const remotePhone = key.remoteJid.split('@')[0];

      // Admin slash commands or natural language in self-chat
      if (text && (text.startsWith('/') || remotePhone === config.adminNumber)) {
        logger.info(`[ADMIN] Command from admin: ${text.substring(0, 50)}...`);
        res.json({ status: 'processing admin' });

        handleAdminMessage({
          text,
          instance: instanceName,
          remoteJid: key.remoteJid,
          isCommand: text.startsWith('/'),
        }).catch(err => {
          logger.error(`[FAIL] Admin command: ${err.message}`);
        });
        return;
      }

      return res.json({ status: 'ignored', reason: 'own message' });
    }

    // Skip other self messages
    if (key.fromMe) {
      return res.json({ status: 'ignored', reason: 'own message' });
    }

    // Extract WhatsApp ID
    const whatsappId = key.remoteJid.replace('@s.whatsapp.net', '').replace('@g.us', '').replace('@lid', '@lid');
    const isGroup = key.remoteJid.includes('@g.us');
    const pushName = data?.pushName || 'Unknown';

    // Check message type
    const msgContent = messageData?.message || messageData;
    const messageType = data?.messageType || Object.keys(msgContent || {})[0];

    // Handle audio messages (including forwarded)
    if (messageType === 'audioMessage' || msgContent?.audioMessage) {
      // Check if audio is forwarded
      const audioContextInfo = msgContent?.audioMessage?.contextInfo || data?.contextInfo;
      const isForwardedAudio = !!(audioContextInfo?.isForwarded);

      logger.info(`[AUDIO] ${isForwardedAudio ? '[ENCAMINHADO] ' : ''}Received from ${whatsappId} (${pushName})`);

      res.json({ status: 'processing audio' });

      handleAudioMessage({
        whatsappId,
        instance: instanceName,
        remoteJid: key.remoteJid,
        pushName,
        messageKey: key,
        audioBase64: null,
        isForwarded: isForwardedAudio,
      }).catch(err => {
        logger.error(`[FAIL] Audio processing: ${err.message}`);
      });

      return;
    }

    // Get text content
    const text =
      msgContent?.conversation ||
      msgContent?.extendedTextMessage?.text ||
      msgContent?.imageMessage?.caption ||
      msgContent?.videoMessage?.caption ||
      data?.message?.conversation ||
      data?.message?.extendedTextMessage?.text ||
      '';

    // Check for forwarded message
    const isForwarded = !!(
      msgContent?.extendedTextMessage?.contextInfo?.isForwarded ||
      msgContent?.imageMessage?.contextInfo?.isForwarded ||
      msgContent?.videoMessage?.contextInfo?.isForwarded ||
      data?.contextInfo?.isForwarded
    );

    // Get forwarded content info
    let forwardedInfo = null;
    if (isForwarded) {
      const contextInfo = msgContent?.extendedTextMessage?.contextInfo ||
                          msgContent?.imageMessage?.contextInfo ||
                          msgContent?.videoMessage?.contextInfo ||
                          data?.contextInfo;
      forwardedInfo = {
        forwardingScore: contextInfo?.forwardingScore || 1,
        quotedMessage: contextInfo?.quotedMessage,
      };
      logger.info(`[FORWARDED] Message from ${whatsappId}`);
    }

    if (!text) {
      logger.debug(`No text in message type: ${messageType}`);
      return res.json({ status: 'ignored', reason: 'no text content' });
    }

    logger.info(`[MSG] From: ${whatsappId} (${pushName}): ${text.substring(0, 50)}...`);

    // Respond immediately, process asynchronously
    res.json({ status: 'processing' });

    // Process message in background
    handleMessage({
      whatsappId,
      text,
      isGroup,
      instance: instanceName,
      remoteJid: key.remoteJid,
      pushName,
      rawData: data,
      isForwarded,
      forwardedInfo,
    }).catch(err => {
      logger.error(`[FAIL] Message processing: ${err.message}`);
    });

  } catch (error) {
    logger.error('Webhook error:', error);
    if (!res.headersSent) {
      res.status(500).json({ error: 'Internal server error' });
    }
  }
});

// Webhook verification
router.get('/', (req, res) => {
  res.json({ status: 'webhook active', service: 'agent-node' });
});

module.exports = router;
