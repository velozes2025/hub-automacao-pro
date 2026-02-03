const express = require('express');
const router = express.Router();
const migrationService = require('../../services/migration');
const logger = require('../../utils/logger');

/**
 * POST /migration/import
 * Import conversations from PostgreSQL format
 * Body: { conversations: [...] }
 */
router.post('/import', async (req, res) => {
  try {
    const { conversations } = req.body;

    if (!conversations || !Array.isArray(conversations)) {
      return res.status(400).json({
        error: 'Invalid format',
        expected: migrationService.getExpectedFormat(),
      });
    }

    logger.info(`Starting import of ${conversations.length} conversations`);

    const stats = await migrationService.migrateFromPostgres({ conversations });

    res.json({
      success: true,
      stats,
      message: `Imported ${stats.conversations} conversations, ${stats.messages} messages`,
    });

  } catch (error) {
    logger.error('Import error:', error);
    res.status(500).json({ error: error.message });
  }
});

/**
 * GET /migration/status
 * Check migration status
 */
router.get('/status', (req, res) => {
  try {
    const stats = migrationService.getMigrationStats();
    res.json(stats);
  } catch (error) {
    logger.error('Status error:', error);
    res.status(500).json({ error: error.message });
  }
});

/**
 * GET /migration/format
 * Get expected import format
 */
router.get('/format', (req, res) => {
  res.json(migrationService.getExpectedFormat());
});

/**
 * POST /migration/from-postgres
 * Direct migration via SQL query (run inside container with PG access)
 */
router.post('/from-postgres', async (req, res) => {
  try {
    const { connectionString } = req.body;

    if (!connectionString) {
      return res.status(400).json({
        error: 'connectionString required',
        example: 'postgresql://user:pass@host:5432/db',
      });
    }

    // This would require pg module - for now return instructions
    res.json({
      message: 'Direct PostgreSQL migration',
      instructions: [
        '1. Use the export script to generate JSON from PostgreSQL',
        '2. POST the JSON to /migration/import',
        '3. Or use the Python export endpoint',
      ],
      exportScript: `
        -- Run this SQL in PostgreSQL to export data:
        SELECT json_agg(row_to_json(t)) FROM (
          SELECT
            c.contact_phone,
            c.contact_name,
            c.stage,
            c.created_at,
            c.last_message_at,
            (
              SELECT json_agg(row_to_json(m))
              FROM messages m
              WHERE m.conversation_id = c.id
              ORDER BY m.created_at
            ) as messages
          FROM conversations c
        ) t;
      `,
    });

  } catch (error) {
    logger.error('Migration error:', error);
    res.status(500).json({ error: error.message });
  }
});

module.exports = router;
