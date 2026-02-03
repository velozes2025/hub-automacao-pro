/**
 * LID (Linked ID) Resolver
 * Resolves WhatsApp LID JIDs (e.g., 12345@lid) to real phone numbers
 * for Instagram/Facebook Messenger integration
 */

const { getDatabase } = require('../db/sqlite');
const logger = require('../utils/logger');
const axios = require('axios');
const config = require('../config');

// In-memory cache: lid_jid -> phone
const cache = new Map();

class LIDResolver {
  constructor() {
    this.evolutionUrl = config.evolution.url;
    this.apiKey = config.evolution.apiKey;
  }

  /**
   * Check if a JID is a LID (Linked ID)
   */
  isLID(jid) {
    return jid && jid.includes('@lid');
  }

  /**
   * Get the correct JID for sending messages
   * If it's a LID, try to resolve it; otherwise return as-is
   */
  async getDestinationJid(instanceName, remoteJid) {
    if (!this.isLID(remoteJid)) {
      // Regular WhatsApp number, use as-is
      return remoteJid;
    }

    // Try to resolve LID to phone number
    const phone = await this.resolve(instanceName, remoteJid);
    if (phone) {
      return `${phone}@s.whatsapp.net`;
    }

    // If we can't resolve, return original (Evolution might handle it)
    logger.warn(`Could not resolve LID: ${remoteJid}, using original`);
    return remoteJid;
  }

  /**
   * Resolve a LID JID to a real phone number
   */
  async resolve(instanceName, lidJid) {
    // Check cache first
    if (cache.has(lidJid)) {
      return cache.get(lidJid);
    }

    // Check database
    const db = getDatabase();
    try {
      const mapping = db.prepare(`
        SELECT phone FROM lid_mappings WHERE lid_jid = ?
      `).get(lidJid);

      if (mapping?.phone) {
        cache.set(lidJid, mapping.phone);
        logger.debug(`LID resolved from DB: ${lidJid} -> ${mapping.phone}`);
        return mapping.phone;
      }
    } catch (e) {
      // Table might not exist, create it
      this.ensureTable();
    }

    // Try to resolve via contacts API
    try {
      const contacts = await this.fetchContacts(instanceName);
      if (contacts && contacts.length > 0) {
        const lidContact = contacts.find(c => c.remoteJid === lidJid);

        if (lidContact) {
          const picUrl = lidContact.profilePicUrl;
          const pushName = lidContact.pushName;

          // Strategy 1: Match by profile picture URL
          if (picUrl) {
            for (const c of contacts) {
              if (c.remoteJid?.endsWith('@s.whatsapp.net') &&
                  this.sameProfilePic(c.profilePicUrl, picUrl)) {
                const phone = c.remoteJid.split('@')[0];
                this.saveMapping(lidJid, phone, pushName, 'profilePic');
                return phone;
              }
            }
          }

          // Strategy 2: Match by unique pushName
          if (pushName) {
            const candidates = contacts.filter(c =>
              c.remoteJid?.endsWith('@s.whatsapp.net') &&
              c.pushName === pushName
            );

            if (candidates.length === 1) {
              const phone = candidates[0].remoteJid.split('@')[0];
              this.saveMapping(lidJid, phone, pushName, 'pushName');
              return phone;
            }
          }
        }
      }
    } catch (error) {
      logger.error('LID resolution error:', error.message);
    }

    logger.warn(`LID unresolved: ${lidJid}`);
    return null;
  }

  /**
   * Compare profile picture URLs (ignoring query params)
   */
  sameProfilePic(url1, url2) {
    if (!url1 || !url2) return false;
    return url1.split('?')[0] === url2.split('?')[0];
  }

  /**
   * Fetch contacts from Evolution API
   */
  async fetchContacts(instanceName) {
    try {
      const response = await axios.post(
        `${this.evolutionUrl}/chat/findContacts/${instanceName}`,
        {},
        {
          headers: {
            'apikey': this.apiKey,
            'Content-Type': 'application/json',
          },
          timeout: 10000,
        }
      );
      return response.data || [];
    } catch (error) {
      logger.error('Failed to fetch contacts:', error.message);
      return [];
    }
  }

  /**
   * Save LID -> phone mapping to database
   */
  saveMapping(lidJid, phone, pushName, source) {
    const db = getDatabase();
    this.ensureTable();

    try {
      db.prepare(`
        INSERT OR REPLACE INTO lid_mappings (lid_jid, phone, push_name, source, updated_at)
        VALUES (?, ?, ?, ?, datetime('now'))
      `).run(lidJid, phone, pushName || '', source);

      cache.set(lidJid, phone);
      logger.info(`[OK] LID resolved via ${source}: ${lidJid} -> ${phone}`);
    } catch (error) {
      logger.error('Failed to save LID mapping:', error.message);
    }
  }

  /**
   * Learn from incoming message (contacts.upsert event)
   */
  learnFromContact(contactData) {
    try {
      const contactId = contactData.id || contactData.remoteJid || '';
      const lid = contactData.lid || '';

      if (contactId.includes('@s.whatsapp.net') && lid.includes('@lid')) {
        const phone = contactId.split('@')[0];
        const pushName = contactData.name || contactData.notify || contactData.pushName || '';
        this.saveMapping(lid, phone, pushName, 'contacts_event');
        return { lid, phone };
      }
    } catch (error) {
      logger.error('Learn from contact error:', error.message);
    }
    return null;
  }

  /**
   * Ensure lid_mappings table exists
   */
  ensureTable() {
    const db = getDatabase();
    db.exec(`
      CREATE TABLE IF NOT EXISTS lid_mappings (
        lid_jid TEXT PRIMARY KEY,
        phone TEXT NOT NULL,
        push_name TEXT,
        source TEXT,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    `);
  }
}

module.exports = new LIDResolver();
