#!/bin/sh
PORT="${PORT:-9615}"
echo "Starting admin panel on port $PORT"
exec gunicorn --bind "0.0.0.0:$PORT" --workers 2 --timeout 30 admin.app:app
