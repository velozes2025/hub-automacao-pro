const { getDatabase } = require('../db/sqlite');
const logger = require('../utils/logger');
const config = require('../config');

class MemoryManager {
  getOrCreateMemory(whatsappId, businessId = 'default') {
    const db = getDatabase();

    let memory = db.prepare(`
      SELECT * FROM conversation_memory
      WHERE whatsapp_id = ? AND business_id = ?
    `).get(whatsappId, businessId);

    if (!memory) {
      const now = new Date().toISOString();
      const result = db.prepare(`
        INSERT INTO conversation_memory (whatsapp_id, business_id, first_contact_at, last_contact_at)
        VALUES (?, ?, ?, ?)
      `).run(whatsappId, businessId, now, now);

      memory = db.prepare('SELECT * FROM conversation_memory WHERE id = ?').get(result.lastInsertRowid);
      logger.info(`Created new memory for ${whatsappId}`);
    }

    return memory;
  }

  updateMemory(memoryId, updates) {
    const db = getDatabase();
    const fields = [];
    const values = [];

    const allowedFields = [
      'summary_short', 'summary_detailed', 'facts',
      'lead_stage', 'lead_temperature', 'last_contact_at', 'total_messages'
    ];

    for (const [key, value] of Object.entries(updates)) {
      if (allowedFields.includes(key)) {
        fields.push(`${key} = ?`);
        values.push(typeof value === 'object' ? JSON.stringify(value) : value);
      }
    }

    if (fields.length === 0) return;

    fields.push('updated_at = ?');
    values.push(new Date().toISOString());
    values.push(memoryId);

    db.prepare(`
      UPDATE conversation_memory
      SET ${fields.join(', ')}
      WHERE id = ?
    `).run(...values);
  }

  addToHistory(memoryId, role, content, sentiment = null) {
    const db = getDatabase();

    db.prepare(`
      INSERT INTO conversation_history (memory_id, role, content, sentiment)
      VALUES (?, ?, ?, ?)
    `).run(memoryId, role, content, sentiment);

    // Update message count
    db.prepare(`
      UPDATE conversation_memory
      SET total_messages = total_messages + 1,
          last_contact_at = CURRENT_TIMESTAMP,
          updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
    `).run(memoryId);
  }

  getHistory(memoryId, limit = config.memory.maxHistoryMessages) {
    const db = getDatabase();

    return db.prepare(`
      SELECT role, content, sentiment, created_at
      FROM conversation_history
      WHERE memory_id = ?
      ORDER BY created_at DESC
      LIMIT ?
    `).all(memoryId, limit).reverse();
  }

  getFacts(memoryId) {
    const db = getDatabase();
    const memory = db.prepare('SELECT facts FROM conversation_memory WHERE id = ?').get(memoryId);

    try {
      return JSON.parse(memory?.facts || '{}');
    } catch {
      return {};
    }
  }

  updateFacts(memoryId, newFacts) {
    const currentFacts = this.getFacts(memoryId);
    const mergedFacts = { ...currentFacts, ...newFacts };
    this.updateMemory(memoryId, { facts: mergedFacts });
    return mergedFacts;
  }

  needsSummary(memoryId) {
    const db = getDatabase();
    const count = db.prepare(`
      SELECT COUNT(*) as count FROM conversation_history WHERE memory_id = ?
    `).get(memoryId);

    return count.count >= config.memory.summaryThreshold;
  }

  getBusinessContext(businessId) {
    const db = getDatabase();
    return db.prepare(`
      SELECT * FROM business_contexts WHERE business_id = ? AND active = 1
    `).get(businessId);
  }

  createBusinessContext(businessId, name, options = {}) {
    const db = getDatabase();

    db.prepare(`
      INSERT OR REPLACE INTO business_contexts
      (business_id, name, industry, system_prompt, tools_enabled)
      VALUES (?, ?, ?, ?, ?)
    `).run(
      businessId,
      name,
      options.industry || null,
      options.systemPrompt || null,
      JSON.stringify(options.toolsEnabled || [])
    );
  }
}

module.exports = new MemoryManager();
