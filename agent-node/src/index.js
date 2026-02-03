require('dotenv').config();

const { initDatabase, closeDatabase } = require('./db/sqlite');
const { createServer } = require('./api/server');
const logger = require('./utils/logger');
const config = require('./config');
const consumptionLogger = require('./services/consumption-logger');

let httpServer = null;

async function main() {
  try {
    logger.info('='.repeat(50));
    logger.info('Starting agent-node service...');
    logger.info(`Environment: ${config.nodeEnv}`);
    logger.info(`Port: ${config.port}`);
    logger.info('='.repeat(50));

    // Initialize SQLite database
    await initDatabase();
    logger.info('[OK] Database initialized');

    // Initialize consumption logger (PostgreSQL for cost tracking)
    await consumptionLogger.init();
    logger.info('[OK] Consumption logger initialized');

    // Start Express server
    const app = createServer();
    httpServer = app.listen(config.port, () => {
      logger.info(`[OK] Server running on port ${config.port}`);
      logger.info('[OK] Agent-node ready to receive messages');
    });

    // Graceful shutdown
    const shutdown = async (signal) => {
      logger.info(`Received ${signal}, shutting down gracefully...`);

      if (httpServer) {
        httpServer.close(async () => {
          logger.info('[OK] HTTP server closed');
          closeDatabase();
          logger.info('[OK] Database closed');
          await consumptionLogger.close();
          logger.info('[OK] Consumption logger closed');
          process.exit(0);
        });

        // Force exit after 10 seconds
        setTimeout(() => {
          logger.warn('Forced shutdown after timeout');
          process.exit(1);
        }, 10000);
      } else {
        process.exit(0);
      }
    };

    process.on('SIGTERM', () => shutdown('SIGTERM'));
    process.on('SIGINT', () => shutdown('SIGINT'));

  } catch (error) {
    logger.error('Failed to start service:', error);
    process.exit(1);
  }
}

main();
