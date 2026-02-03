FROM node:20-alpine

# Install build dependencies for native modules
RUN apk add --no-cache python3 make g++ sqlite

# Install PM2 globally
RUN npm install -g pm2

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies (use install instead of ci since no lock file)
RUN npm install --omit=dev

# Copy source code
COPY . .

# Create data and logs directories
RUN mkdir -p /app/data /app/logs

# Expose port
EXPOSE 3100

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:3100/health || exit 1

# Start with PM2
CMD ["pm2-runtime", "ecosystem.config.js", "--env", "production"]
