const winston = require('winston');
const path = require('path');
const config = require('../config');

const logFormat = winston.format.combine(
  winston.format.timestamp({ format: 'YYYY-MM-DD HH:mm:ss' }),
  winston.format.errors({ stack: true }),
  winston.format.printf(({ level, message, timestamp, stack }) => {
    return `${timestamp} [${level.toUpperCase()}]: ${stack || message}`;
  })
);

const transports = [
  new winston.transports.Console({
    format: winston.format.combine(
      winston.format.colorize(),
      logFormat
    ),
  }),
];

if (config.nodeEnv === 'production') {
  transports.push(
    new winston.transports.File({
      filename: path.join(__dirname, '../../logs/error.log'),
      level: 'error',
      format: logFormat,
    }),
    new winston.transports.File({
      filename: path.join(__dirname, '../../logs/combined.log'),
      format: logFormat,
    })
  );
}

const logger = winston.createLogger({
  level: config.nodeEnv === 'production' ? 'info' : 'debug',
  transports,
});

module.exports = logger;
