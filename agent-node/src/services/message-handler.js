const memoryManager = require('./memory-manager');
const aiProcessor = require('./ai-processor');
const adminController = require('./admin-controller');
const evolution = require('../integrations/evolution');
const elevenlabs = require('../integrations/elevenlabs');
const openai = require('../integrations/openai');
const airtable = require('../integrations/airtable');
const logger = require('../utils/logger');

/**
 * Main message processing pipeline
 */
async function handleMessage({ whatsappId, text, isGroup, instance, remoteJid, pushName, rawData, isForwarded, forwardedInfo }) {
  const startTime = Date.now();

  try {
    logger.info(`[MSG IN] From: ${whatsappId} (${pushName || 'Unknown'})`);
    logger.info(`[MSG IN] Text: ${text.substring(0, 100)}${text.length > 100 ? '...' : ''}`);

    // Handle forwarded messages - add context
    let messageText = text;
    if (isForwarded) {
      logger.info(`[FORWARDED] Processing forwarded message`);
      messageText = `[Mensagem encaminhada pelo cliente]\n${text}`;
    }

    // Step 1: Set typing indicator
    await evolution.setTyping(instance, remoteJid, true);

    // Step 2: Get or create memory
    const businessId = instance || 'default';
    const memory = memoryManager.getOrCreateMemory(whatsappId, businessId);
    logger.info(`[OK] Memory loaded (ID: ${memory.id}, msgs: ${memory.total_messages})`);

    // Step 3: Save incoming message to history
    memoryManager.addToHistory(memory.id, 'user', messageText);

    // Step 4: Get conversation history and facts
    const history = memoryManager.getHistory(memory.id);
    const facts = memoryManager.getFacts(memory.id);
    logger.info(`[OK] History: ${history.length} msgs, Facts: ${Object.keys(facts).length}`);

    // Step 5: Get business context
    const businessContext = memoryManager.getBusinessContext(businessId);

    // Step 6: Build context for AI
    const { systemPrompt, messages } = aiProcessor.buildContext(
      memory,
      history,
      facts,
      businessContext
    );

    // Step 7: Generate AI response
    logger.info(`[AI] Generating response with ${messages.length} context messages...`);
    const response = await aiProcessor.generateResponse(systemPrompt, messages, messageText);
    logger.info(`[OK] AI response generated (${response.length} chars)`);

    // Step 8: Save assistant response to history
    memoryManager.addToHistory(memory.id, 'assistant', response);

    // Step 9: Send response via Evolution API
    await evolution.setTyping(instance, remoteJid, false);

    // Check if admin wants audio responses
    if (adminController.shouldRespondWithAudio(false)) {
      try {
        logger.info('[TTS] Admin mode: generating audio response...');
        const audioResponse = await elevenlabs.textToSpeech(response);
        if (audioResponse) {
          const audioBase64Response = audioResponse.toString('base64');
          await evolution.sendAudio(instance, remoteJid, audioBase64Response);
          logger.info('[OK] Audio response sent (admin mode)');
        } else {
          await evolution.sendMessage(instance, remoteJid, response);
        }
      } catch (ttsError) {
        logger.warn('[TTS] Audio failed, sending text:', ttsError.message);
        await evolution.sendMessage(instance, remoteJid, response);
      }
    } else {
      await evolution.sendMessage(instance, remoteJid, response);
    }

    const duration = Date.now() - startTime;
    logger.info(`[OK] Response sent to ${whatsappId} in ${duration}ms`);

    // Step 10: Background tasks (non-blocking)
    processBackgroundTasks(memory.id, whatsappId, history, facts, text, response, pushName).catch(err => {
      logger.error('[BG] Background task error:', err.message);
    });

    return { success: true, response, duration };

  } catch (error) {
    const duration = Date.now() - startTime;
    logger.error(`[FAIL] Message handling failed after ${duration}ms: ${error.message}`);

    try {
      await evolution.setTyping(instance, remoteJid, false);
    } catch (e) {}

    throw error;
  }
}

/**
 * Process audio messages - transcribe and respond with audio
 * Handles both direct and forwarded audio messages
 */
async function handleAudioMessage({ whatsappId, instance, remoteJid, pushName, audioBase64, messageKey, isForwarded }) {
  const startTime = Date.now();

  try {
    const forwardedLabel = isForwarded ? '[ENCAMINHADO] ' : '';
    logger.info(`[AUDIO IN] ${forwardedLabel}From: ${whatsappId} (${pushName || 'Unknown'})`);

    // Set typing indicator
    await evolution.setTyping(instance, remoteJid, true);

    // Get audio from Evolution if not provided
    let audio = audioBase64;
    if (!audio && messageKey) {
      logger.info('[AUDIO] Downloading audio from Evolution...');
      audio = await evolution.getBase64Media(instance, messageKey);
    }

    if (!audio) {
      logger.error('[FAIL] Could not get audio data');
      await evolution.sendMessage(instance, remoteJid, 'Desculpe, não consegui processar seu áudio. Pode enviar novamente?');
      return { success: false, error: 'No audio data' };
    }

    // Transcribe audio with OpenAI Whisper
    logger.info('[AUDIO] Transcribing with Whisper...');
    let transcription;
    try {
      transcription = await openai.transcribeAudio(Buffer.from(audio, 'base64'));
      logger.info(`[OK] Transcribed: "${transcription.substring(0, 50)}..."`);
    } catch (transcribeError) {
      logger.error('[FAIL] Transcription failed:', transcribeError.message);
      await evolution.sendMessage(instance, remoteJid, 'Não consegui entender o áudio. Pode digitar sua mensagem?');
      return { success: false, error: 'Transcription failed' };
    }

    // Get memory and history
    const businessId = instance || 'default';
    const memory = memoryManager.getOrCreateMemory(whatsappId, businessId);

    // Add context if audio was forwarded
    let messageText;
    if (isForwarded) {
      messageText = `[Áudio encaminhado pelo cliente - outra pessoa falando]\n${transcription}`;
    } else {
      messageText = `[Áudio do cliente] ${transcription}`;
    }
    memoryManager.addToHistory(memory.id, 'user', messageText);

    const history = memoryManager.getHistory(memory.id);
    const facts = memoryManager.getFacts(memory.id);
    const businessContext = memoryManager.getBusinessContext(businessId);

    // Generate AI response
    const { systemPrompt, messages } = aiProcessor.buildContext(memory, history, facts, businessContext);
    logger.info('[AI] Generating response...');
    const response = await aiProcessor.generateResponse(systemPrompt, messages, transcription);
    logger.info(`[OK] AI response generated (${response.length} chars)`);

    // Save to history
    memoryManager.addToHistory(memory.id, 'assistant', response);

    // Stop typing
    await evolution.setTyping(instance, remoteJid, false);

    // For audio messages, respond with audio ONLY (not text)
    try {
      logger.info('[TTS] Generating audio response...');
      const audioResponse = await elevenlabs.textToSpeech(response);

      if (audioResponse) {
        const audioBase64Response = audioResponse.toString('base64');
        await evolution.sendAudio(instance, remoteJid, audioBase64Response);
        logger.info('[OK] Audio response sent');
      } else {
        // Fallback to text if audio generation fails completely
        await evolution.sendMessage(instance, remoteJid, response);
        logger.info('[OK] Fallback text response sent');
      }
    } catch (ttsError) {
      logger.warn('[TTS] Audio generation failed:', ttsError.message);
      // Fallback to text only if audio fails
      await evolution.sendMessage(instance, remoteJid, response);
      logger.info('[OK] Fallback text response sent');
    }

    const duration = Date.now() - startTime;
    logger.info(`[OK] Audio message processed in ${duration}ms`);

    return { success: true, transcription, response, duration };

  } catch (error) {
    logger.error(`[FAIL] Audio handling failed: ${error.message}`);

    try {
      await evolution.setTyping(instance, remoteJid, false);
      await evolution.sendMessage(instance, remoteJid, 'Ocorreu um erro ao processar seu áudio. Tente novamente.');
    } catch (e) {}

    throw error;
  }
}

/**
 * Background tasks (facts extraction, summarization, lead classification)
 */
async function processBackgroundTasks(memoryId, whatsappId, history, currentFacts, userMessage, assistantResponse, pushName) {
  try {
    // Extract new facts from conversation
    const conversationSnippet = `user: ${userMessage}\nassistant: ${assistantResponse}`;
    const newFacts = await aiProcessor.extractFacts(conversationSnippet);

    // Add pushName as fact if we don't have a name
    if (pushName && pushName !== 'Unknown' && !currentFacts.nome) {
      newFacts.nome = pushName;
    }

    if (Object.keys(newFacts).length > 0) {
      memoryManager.updateFacts(memoryId, newFacts);
      logger.info(`[BG] Facts updated: ${JSON.stringify(newFacts)}`);

      // Sync to Airtable if configured
      if (airtable.isConfigured()) {
        try {
          await airtable.upsertLead(whatsappId, {
            Nome: newFacts.nome || pushName,
            Empresa: newFacts.empresa,
            Interesse: newFacts.interesse,
            Ultimo_Contato: new Date().toISOString(),
          });
          logger.info(`[BG] Airtable synced for ${whatsappId}`);
        } catch (e) {
          logger.error(`[BG] Airtable sync failed: ${e.message}`);
        }
      }
    }

    // Generate summary if needed (every 20 messages)
    if (memoryManager.needsSummary(memoryId)) {
      const fullHistory = memoryManager.getHistory(memoryId, 50);
      const memory = require('../db/sqlite').getDatabase()
        .prepare('SELECT summary_detailed FROM conversation_memory WHERE id = ?')
        .get(memoryId);

      const summaries = await aiProcessor.generateSummary(fullHistory, memory?.summary_detailed);

      if (summaries.short || summaries.detailed) {
        memoryManager.updateMemory(memoryId, {
          summary_short: summaries.short,
          summary_detailed: summaries.detailed,
        });
        logger.info(`[BG] Summary updated`);
      }
    }

    // Classify lead periodically (every 5 messages)
    const updatedHistory = memoryManager.getHistory(memoryId);
    if (updatedHistory.length % 5 === 0) {
      const updatedFacts = memoryManager.getFacts(memoryId);
      const classification = await aiProcessor.classifyLead(updatedHistory, updatedFacts);

      memoryManager.updateMemory(memoryId, {
        lead_stage: classification.stage,
        lead_temperature: classification.temperature,
      });
      logger.info(`[BG] Lead classified: ${classification.stage} / ${classification.temperature}`);
    }

  } catch (error) {
    logger.error(`[BG] Background processing error: ${error.message}`);
  }
}

/**
 * Handle admin commands via WhatsApp (natural language or /commands)
 */
async function handleAdminMessage({ text, instance, remoteJid, isCommand }) {
  try {
    logger.info(`[ADMIN] Processing: ${text.substring(0, 50)}...`);

    // For now, process as natural language command via AI
    const systemPrompt = `Voce e o assistente pessoal do Thiago, dono do Hub Automacao Pro.
Thiago esta te mandando mensagem pelo WhatsApp para controlar o bot.
Responda de forma natural, curta e direta, como um assistente pessoal.

COMANDOS DISPONIVEIS:
/status - Ver status do sistema
/pause - Pausar bot
/resume - Retomar bot
/chats - Listar chats ativos

Se for uma pergunta simples, responda diretamente.
Se for um comando, execute e confirme.`;

    const response = await aiProcessor.chat(
      [{ role: 'user', content: text }],
      systemPrompt
    );

    await evolution.sendMessage(instance, remoteJid, response);
    logger.info(`[ADMIN] Response sent`);

    return { success: true, response };

  } catch (error) {
    logger.error(`[ADMIN] Error: ${error.message}`);
    throw error;
  }
}

module.exports = { handleMessage, handleAudioMessage, handleAdminMessage };
