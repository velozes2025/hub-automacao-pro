const express = require('express');
const router = express.Router();
const { getDatabase } = require('../../db/sqlite');
const logger = require('../../utils/logger');

/**
 * GET /history/:userId
 * Returns full conversation history for a user (migrated + new)
 */
router.get('/:userId', (req, res) => {
  try {
    const { userId } = req.params;
    const { limit = 100, offset = 0, businessId = 'default' } = req.query;

    const db = getDatabase();

    // Get memory record
    const memory = db.prepare(`
      SELECT * FROM conversation_memory
      WHERE whatsapp_id = ? AND business_id = ?
    `).get(userId, businessId);

    if (!memory) {
      return res.status(404).json({ error: 'User not found' });
    }

    // Get conversation history
    const history = db.prepare(`
      SELECT id, role, content, sentiment, created_at
      FROM conversation_history
      WHERE memory_id = ?
      ORDER BY created_at ASC
      LIMIT ? OFFSET ?
    `).all(memory.id, parseInt(limit), parseInt(offset));

    // Get total count
    const totalCount = db.prepare(`
      SELECT COUNT(*) as count FROM conversation_history WHERE memory_id = ?
    `).get(memory.id);

    // Parse facts
    let facts = {};
    try {
      facts = JSON.parse(memory.facts || '{}');
    } catch (e) {
      facts = {};
    }

    res.json({
      user: {
        whatsapp_id: memory.whatsapp_id,
        business_id: memory.business_id,
        lead_stage: memory.lead_stage,
        lead_temperature: memory.lead_temperature,
        first_contact: memory.first_contact_at,
        last_contact: memory.last_contact_at,
        total_messages: memory.total_messages,
      },
      summary: {
        short: memory.summary_short,
        detailed: memory.summary_detailed,
      },
      facts,
      messages: history,
      pagination: {
        total: totalCount.count,
        limit: parseInt(limit),
        offset: parseInt(offset),
        hasMore: parseInt(offset) + history.length < totalCount.count,
      },
    });

  } catch (error) {
    logger.error('Error fetching history:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

/**
 * GET /history
 * List all users with conversation history
 */
router.get('/', (req, res) => {
  try {
    const { limit = 50, offset = 0, businessId } = req.query;

    const db = getDatabase();

    let query = `
      SELECT
        whatsapp_id,
        business_id,
        summary_short,
        lead_stage,
        lead_temperature,
        total_messages,
        first_contact_at,
        last_contact_at
      FROM conversation_memory
    `;

    const params = [];

    if (businessId) {
      query += ' WHERE business_id = ?';
      params.push(businessId);
    }

    query += ' ORDER BY last_contact_at DESC LIMIT ? OFFSET ?';
    params.push(parseInt(limit), parseInt(offset));

    const users = db.prepare(query).all(...params);

    // Get total count
    let countQuery = 'SELECT COUNT(*) as count FROM conversation_memory';
    if (businessId) {
      countQuery += ' WHERE business_id = ?';
    }
    const totalCount = db.prepare(countQuery).get(businessId || undefined);

    res.json({
      users,
      pagination: {
        total: totalCount?.count || 0,
        limit: parseInt(limit),
        offset: parseInt(offset),
      },
    });

  } catch (error) {
    logger.error('Error listing history:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

/**
 * DELETE /history/:userId
 * Delete a user's conversation history (GDPR compliance)
 */
router.delete('/:userId', (req, res) => {
  try {
    const { userId } = req.params;
    const { businessId = 'default' } = req.query;

    const db = getDatabase();

    // Get memory ID
    const memory = db.prepare(`
      SELECT id FROM conversation_memory
      WHERE whatsapp_id = ? AND business_id = ?
    `).get(userId, businessId);

    if (!memory) {
      return res.status(404).json({ error: 'User not found' });
    }

    // Delete in transaction
    const deleteUser = db.transaction(() => {
      db.prepare('DELETE FROM conversation_history WHERE memory_id = ?').run(memory.id);
      db.prepare('DELETE FROM conversation_memory WHERE id = ?').run(memory.id);
    });

    deleteUser();

    logger.info(`Deleted history for user ${userId}`);
    res.json({ success: true, message: 'History deleted' });

  } catch (error) {
    logger.error('Error deleting history:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

module.exports = router;
