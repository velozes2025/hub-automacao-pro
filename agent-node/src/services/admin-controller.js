const config = require('../config');
const logger = require('../utils/logger');

/**
 * Admin Controller - Manages admin preferences and commands
 */
class AdminController {
  constructor() {
    // Admin preferences stored in memory
    this.preferences = {
      responseMode: 'auto', // 'audio', 'text', or 'auto'
      botPaused: false,
      debugMode: false,
    };
  }

  /**
   * Check if a phone number is the admin
   */
  isAdmin(phoneNumber) {
    const cleanPhone = phoneNumber?.replace(/\D/g, '');
    const adminPhone = config.adminNumber?.replace(/\D/g, '');
    return adminPhone && cleanPhone === adminPhone;
  }

  /**
   * Parse admin command from natural language
   * Returns: { command: string, params: object } or null if not a command
   */
  parseCommand(text) {
    const lowerText = text.toLowerCase().trim();

    // Audio commands
    if (/^(manda|envia|responde com|usa)\s*(audio|áudio|voz)/i.test(lowerText) ||
        /^(só|somente|apenas)\s*(audio|áudio|voz)/i.test(lowerText) ||
        /^audio\s*(on|ligado|ativado)?$/i.test(lowerText)) {
      return { command: 'setResponseMode', params: { mode: 'audio' } };
    }

    // Text commands
    if (/^(manda|envia|responde com|usa)\s*(texto|text)/i.test(lowerText) ||
        /^(só|somente|apenas)\s*(texto|text)/i.test(lowerText) ||
        /^texto\s*(on|ligado|ativado)?$/i.test(lowerText)) {
      return { command: 'setResponseMode', params: { mode: 'text' } };
    }

    // Auto mode
    if (/^(modo\s*)?(auto|automatico|automático|normal)/i.test(lowerText) ||
        /^(responde|resposta)\s*(auto|normal)/i.test(lowerText)) {
      return { command: 'setResponseMode', params: { mode: 'auto' } };
    }

    // Pause bot
    if (/^(pausa|pause|para|desliga)\s*(o\s*)?(bot)?$/i.test(lowerText) ||
        /^\/pause$/i.test(lowerText)) {
      return { command: 'pause', params: {} };
    }

    // Resume bot
    if (/^(continua|resume|liga|ativa)\s*(o\s*)?(bot)?$/i.test(lowerText) ||
        /^\/resume$/i.test(lowerText)) {
      return { command: 'resume', params: {} };
    }

    // Status
    if (/^(status|como\s*ta|como\s*está|estado)$/i.test(lowerText) ||
        /^\/status$/i.test(lowerText)) {
      return { command: 'status', params: {} };
    }

    // Help
    if (/^(ajuda|help|comandos|\?)$/i.test(lowerText) ||
        /^\/help$/i.test(lowerText)) {
      return { command: 'help', params: {} };
    }

    return null;
  }

  /**
   * Execute admin command
   */
  executeCommand(command, params) {
    switch (command) {
      case 'setResponseMode':
        this.preferences.responseMode = params.mode;
        logger.info(`[ADMIN] Response mode set to: ${params.mode}`);
        return `Modo de resposta: ${params.mode.toUpperCase()}`;

      case 'pause':
        this.preferences.botPaused = true;
        logger.info('[ADMIN] Bot paused');
        return 'Bot pausado. Mande "continua" para reativar.';

      case 'resume':
        this.preferences.botPaused = false;
        logger.info('[ADMIN] Bot resumed');
        return 'Bot ativado!';

      case 'status':
        return `Status do Bot:
- Modo resposta: ${this.preferences.responseMode}
- Bot ativo: ${!this.preferences.botPaused ? 'Sim' : 'Não (pausado)'}
- Debug: ${this.preferences.debugMode ? 'On' : 'Off'}`;

      case 'help':
        return `Comandos disponíveis:
- "audio" ou "manda audio" - Responde só com áudio
- "texto" - Responde só com texto
- "auto" - Modo automático (padrão)
- "pausa" - Pausa o bot
- "continua" - Reativa o bot
- "status" - Ver status`;

      default:
        return null;
    }
  }

  /**
   * Get current response mode
   */
  getResponseMode() {
    return this.preferences.responseMode;
  }

  /**
   * Check if bot is paused
   */
  isBotPaused() {
    return this.preferences.botPaused;
  }

  /**
   * Should respond with audio?
   */
  shouldRespondWithAudio(isIncomingAudio = false) {
    const mode = this.preferences.responseMode;

    if (mode === 'audio') return true;
    if (mode === 'text') return false;
    // Auto mode: mirror input (audio -> audio, text -> text)
    return isIncomingAudio;
  }
}

module.exports = new AdminController();
