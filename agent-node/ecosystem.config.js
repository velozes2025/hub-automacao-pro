module.exports = {
  apps: [{
    name: 'agent-node',
    script: './src/index.js',
    instances: 1,
    exec_mode: 'fork',
    env: {
      NODE_ENV: 'development',
      PORT: 3100,
    },
    env_production: {
      NODE_ENV: 'production',
      PORT: 3100,
    },
    max_memory_restart: '500M',
    log_file: './logs/combined.log',
    error_file: './logs/error.log',
    out_file: './logs/out.log',
    time: true,
    watch: false,
    autorestart: true,
  }]
};
