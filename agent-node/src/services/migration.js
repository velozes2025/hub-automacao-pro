const { getDatabase } = require('../db/sqlite');
const logger = require('../utils/logger');
const axios = require('axios');

class MigrationService {
  constructor() {
    // PostgreSQL connection via internal API or direct
    this.pgApiUrl = process.env.MIGRATION_PG_API_URL || 'http://hub-bot:3000';
  }

  /**
   * Migrates conversations and messages from PostgreSQL to SQLite
   * Called via API endpoint or on startup
   */
  async migrateFromPostgres(pgData) {
    const db = getDatabase();
    const stats = { conversations: 0, messages: 0, facts: 0, errors: [] };

    try {
      logger.info('Starting migration from PostgreSQL...');

      // Begin transaction
      const migrate = db.transaction((data) => {
        for (const conv of data.conversations) {
          try {
            // Insert or update conversation memory
            const existing = db.prepare(`
              SELECT id FROM conversation_memory
              WHERE whatsapp_id = ? AND business_id = ?
            `).get(conv.contact_phone, conv.tenant_id || 'default');

            let memoryId;

            if (existing) {
              // Update existing
              db.prepare(`
                UPDATE conversation_memory SET
                  summary_short = COALESCE(?, summary_short),
                  summary_detailed = COALESCE(?, summary_detailed),
                  facts = COALESCE(?, facts),
                  lead_stage = ?,
                  first_contact_at = COALESCE(first_contact_at, ?),
                  last_contact_at = ?,
                  updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
              `).run(
                conv.summary_short || null,
                conv.summary_detailed || null,
                conv.facts ? JSON.stringify(conv.facts) : null,
                conv.stage || 'new',
                conv.created_at,
                conv.last_message_at || conv.created_at,
                existing.id
              );
              memoryId = existing.id;
            } else {
              // Insert new
              const result = db.prepare(`
                INSERT INTO conversation_memory
                (whatsapp_id, business_id, summary_short, summary_detailed, facts,
                 lead_stage, first_contact_at, last_contact_at, total_messages)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
              `).run(
                conv.contact_phone,
                conv.tenant_id || 'default',
                conv.summary_short || null,
                conv.summary_detailed || null,
                conv.facts ? JSON.stringify(conv.facts) : '{}',
                conv.stage || 'new',
                conv.created_at,
                conv.last_message_at || conv.created_at,
                conv.messages?.length || 0
              );
              memoryId = result.lastInsertRowid;
              stats.conversations++;
            }

            // Insert messages
            if (conv.messages && conv.messages.length > 0) {
              const insertMsg = db.prepare(`
                INSERT OR IGNORE INTO conversation_history
                (memory_id, role, content, sentiment, created_at)
                VALUES (?, ?, ?, ?, ?)
              `);

              for (const msg of conv.messages) {
                insertMsg.run(
                  memoryId,
                  msg.role,
                  msg.content,
                  msg.sentiment || null,
                  msg.created_at
                );
                stats.messages++;
              }
            }

            // Insert facts from client_memory
            if (conv.client_facts && conv.client_facts.length > 0) {
              const currentFacts = JSON.parse(
                db.prepare('SELECT facts FROM conversation_memory WHERE id = ?')
                  .get(memoryId)?.facts || '{}'
              );

              for (const fact of conv.client_facts) {
                currentFacts[fact.fact_key] = fact.fact_value;
                stats.facts++;
              }

              db.prepare('UPDATE conversation_memory SET facts = ? WHERE id = ?')
                .run(JSON.stringify(currentFacts), memoryId);
            }

          } catch (err) {
            stats.errors.push({ phone: conv.contact_phone, error: err.message });
            logger.error(`Error migrating ${conv.contact_phone}:`, err);
          }
        }
      });

      migrate(pgData);

      logger.info(`Migration complete: ${stats.conversations} conversations, ${stats.messages} messages, ${stats.facts} facts`);
      return stats;

    } catch (error) {
      logger.error('Migration failed:', error);
      throw error;
    }
  }

  /**
   * Fetches data from PostgreSQL via hub-bot internal API
   */
  async fetchPostgresData() {
    try {
      // This would call an internal API endpoint on hub-bot
      // For now, we'll provide a direct SQL export method
      logger.info('Fetching data from PostgreSQL...');

      const response = await axios.get(`${this.pgApiUrl}/internal/export-conversations`, {
        timeout: 60000,
      });

      return response.data;
    } catch (error) {
      logger.error('Failed to fetch PostgreSQL data:', error.message);
      throw error;
    }
  }

  /**
   * Exports migration data format (to be called from Python side)
   * Returns the expected JSON structure
   */
  getExpectedFormat() {
    return {
      conversations: [
        {
          contact_phone: '5511999999999',
          contact_name: 'John Doe',
          tenant_id: 'uuid-or-default',
          stage: 'new',
          created_at: '2024-01-01T00:00:00Z',
          last_message_at: '2024-01-02T00:00:00Z',
          summary_short: 'Customer interested in product X',
          summary_detailed: 'Full summary...',
          facts: { nome: 'John', empresa: 'ACME' },
          messages: [
            { role: 'user', content: 'Hello', created_at: '2024-01-01T00:00:00Z' },
            { role: 'assistant', content: 'Hi!', created_at: '2024-01-01T00:00:01Z' },
          ],
          client_facts: [
            { fact_key: 'nome', fact_value: 'John' },
          ],
        },
      ],
    };
  }

  /**
   * Check migration status
   */
  getMigrationStats() {
    const db = getDatabase();

    const memoryCount = db.prepare('SELECT COUNT(*) as count FROM conversation_memory').get();
    const historyCount = db.prepare('SELECT COUNT(*) as count FROM conversation_history').get();
    const migratedCount = db.prepare(`
      SELECT COUNT(*) as count FROM conversation_memory
      WHERE created_at < datetime('now', '-1 hour')
    `).get();

    return {
      total_memories: memoryCount.count,
      total_messages: historyCount.count,
      likely_migrated: migratedCount.count,
    };
  }
}

module.exports = new MigrationService();
