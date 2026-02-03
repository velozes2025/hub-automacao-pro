const express = require('express');
const webhookRoutes = require('./routes/webhook');
const historyRoutes = require('./routes/history');
const migrationRoutes = require('./routes/migration');
const logger = require('../utils/logger');
const { getDatabase } = require('../db/sqlite');

function createServer() {
  const app = express();

  // Middleware
  app.use(express.json({ limit: '50mb' })); // Increased for migration imports
  app.use(express.urlencoded({ extended: true }));

  // Request logging
  app.use((req, res, next) => {
    if (req.path !== '/health') {
      logger.debug(`${req.method} ${req.path}`);
    }
    next();
  });

  // Health check with stats
  app.get('/health', (req, res) => {
    try {
      const db = getDatabase();
      const memoryCount = db.prepare('SELECT COUNT(*) as count FROM conversation_memory').get();
      const msgCount = db.prepare('SELECT COUNT(*) as count FROM conversation_history').get();

      res.json({
        status: 'ok',
        timestamp: new Date().toISOString(),
        stats: {
          conversations: memoryCount.count,
          messages: msgCount.count,
        },
      });
    } catch (error) {
      res.json({
        status: 'ok',
        timestamp: new Date().toISOString(),
        stats: { error: 'Unable to fetch stats' },
      });
    }
  });

  // API Routes
  app.use('/webhook', webhookRoutes);
  app.use('/history', historyRoutes);
  app.use('/migration', migrationRoutes);

  // Dashboard summary endpoint
  app.get('/dashboard/summary', (req, res) => {
    try {
      const db = getDatabase();

      const totalConversations = db.prepare('SELECT COUNT(*) as count FROM conversation_memory').get();
      const totalMessages = db.prepare('SELECT COUNT(*) as count FROM conversation_history').get();
      const activeToday = db.prepare(`
        SELECT COUNT(*) as count FROM conversation_memory
        WHERE date(last_contact_at) = date('now')
      `).get();
      const leadsByStage = db.prepare(`
        SELECT lead_stage, COUNT(*) as count
        FROM conversation_memory
        GROUP BY lead_stage
      `).all();
      const leadsByTemp = db.prepare(`
        SELECT lead_temperature, COUNT(*) as count
        FROM conversation_memory
        GROUP BY lead_temperature
      `).all();
      const recentActivity = db.prepare(`
        SELECT
          cm.whatsapp_id,
          cm.summary_short,
          cm.lead_stage,
          cm.last_contact_at,
          (SELECT COUNT(*) FROM conversation_history WHERE memory_id = cm.id) as msg_count
        FROM conversation_memory cm
        ORDER BY cm.last_contact_at DESC
        LIMIT 10
      `).all();

      res.json({
        overview: {
          total_conversations: totalConversations.count,
          total_messages: totalMessages.count,
          active_today: activeToday.count,
        },
        leads_by_stage: leadsByStage.reduce((acc, row) => {
          acc[row.lead_stage] = row.count;
          return acc;
        }, {}),
        leads_by_temperature: leadsByTemp.reduce((acc, row) => {
          acc[row.lead_temperature] = row.count;
          return acc;
        }, {}),
        recent_activity: recentActivity,
      });

    } catch (error) {
      logger.error('Dashboard error:', error);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  // 404 handler
  app.use((req, res) => {
    res.status(404).json({ error: 'Not found' });
  });

  // Error handler
  app.use((err, req, res, next) => {
    logger.error('Unhandled error:', err);
    res.status(500).json({ error: 'Internal server error' });
  });

  return app;
}

module.exports = { createServer };
