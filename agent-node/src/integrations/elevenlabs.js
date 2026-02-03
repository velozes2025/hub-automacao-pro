const axios = require('axios');
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');
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
            stability: 0.30,
            similarity_boost: 0.60,
            style: 0.40,
            use_speaker_boost: true,
          },
          output_format: 'mp3_44100_192',
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

      // Process audio to reduce echo/reverb
      const rawAudio = Buffer.from(response.data);
      const processedAudio = await this.processAudio(rawAudio);
      return processedAudio;

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

  /**
   * Process audio with ffmpeg to reduce echo/reverb
   */
  async processAudio(audioBuffer) {
    try {
      const tmpDir = os.tmpdir();
      const inputFile = path.join(tmpDir, `tts_in_${Date.now()}.mp3`);
      const outputFile = path.join(tmpDir, `tts_out_${Date.now()}.mp3`);

      // Write input audio
      fs.writeFileSync(inputFile, audioBuffer);

      // Natural voice processing - preserve bass for masculine tone:
      // - lowpass=f=14000: preserve natural highs
      // - equalizer: boost low-mids for fuller/deeper voice
      // - afftdn=nf=-30: minimal noise reduction
      const ffmpegCmd = `ffmpeg -i "${inputFile}" -af "lowpass=f=14000,equalizer=f=180:t=q:w=1:g=3,equalizer=f=2500:t=q:w=1:g=-1,afftdn=nf=-30" -y "${outputFile}" 2>/dev/null`;

      execSync(ffmpegCmd, { timeout: 30000 });

      // Read processed audio
      const processedBuffer = fs.readFileSync(outputFile);

      // Cleanup temp files
      try {
        fs.unlinkSync(inputFile);
        fs.unlinkSync(outputFile);
      } catch (e) {}

      logger.debug('[TTS] Audio processed with echo reduction');
      return processedBuffer;

    } catch (error) {
      logger.warn('[TTS] Audio processing failed, using original:', error.message);
      return audioBuffer;
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
