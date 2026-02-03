FROM python:3.11-slim

WORKDIR /workspace

RUN pip install --no-cache-dir \
    flask==3.0.* \
    requests==2.31.* \
    psycopg2-binary==2.9.* \
    lxml \
    gunicorn==22.*

# Copy app module (needed for whatsapp channel imports)
COPY app/ ./app/

# Copy admin panel
COPY admin/ ./admin/

# Start script handles PORT env gracefully
COPY admin/start.sh ./start.sh
RUN chmod +x start.sh

CMD ["./start.sh"]
