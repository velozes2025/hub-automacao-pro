const Database = require('better-sqlite3');
const fs = require('fs');
const path = require('path');
const config = require('../config');
const logger = require('../utils/logger');

let db = null;

function getDatabase() {
  if (!db) {
    const dbDir = path.dirname(config.sqlite.path);
    if (!fs.existsSync(dbDir)) {
      fs.mkdirSync(dbDir, { recursive: true });
    }

    db = new Database(config.sqlite.path);
    db.pragma('journal_mode = WAL');
    db.pragma('foreign_keys = ON');
  }
  return db;
}

async function initDatabase() {
  const database = getDatabase();

  const migrationPath = path.join(__dirname, 'migrations', '001_initial.sql');
  const migration = fs.readFileSync(migrationPath, 'utf8');

  database.exec(migration);
  logger.info('Database migrations applied');

  return database;
}

function closeDatabase() {
  if (db) {
    db.close();
    db = null;
  }
}

module.exports = {
  getDatabase,
  initDatabase,
  closeDatabase,
};
