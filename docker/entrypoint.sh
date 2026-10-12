#!/bin/sh
set -e

echo "==> Running entrypoint script for Many Gym..."

# Wait for PostgreSQL
if [ "$DB_ENGINE" = "django.db.backends.postgresql" ] || [ -n "$POSTGRES_DB" ]; then
    echo "==> Waiting for PostgreSQL ($DB_HOST:$DB_PORT)..."
    python - <<END
import socket
import time
import os

host = os.environ.get("DB_HOST", "db")
port = int(os.environ.get("DB_PORT", 5432))
timeout = 60
start_time = time.time()

while True:
    try:
        with socket.create_connection((host, port), timeout=2):
            print("==> PostgreSQL is ready!")
            break
    except OSError:
        if time.time() - start_time > timeout:
            print("==> Timed out waiting for PostgreSQL.")
            exit(1)
        time.sleep(1)
END
fi

# Wait for Redis
if [ -n "$REDIS_HOST" ]; then
    echo "==> Waiting for Redis ($REDIS_HOST:${REDIS_PORT:-6379})..."
    python - <<END
import socket
import time
import os

host = os.environ.get("REDIS_HOST", "redis")
port = int(os.environ.get("REDIS_PORT", 6379))
timeout = 60
start_time = time.time()

while True:
    try:
        with socket.create_connection((host, port), timeout=2):
            print("==> Redis is ready!")
            break
    except OSError:
        if time.time() - start_time > timeout:
            print("==> Timed out waiting for Redis.")
            exit(1)
        time.sleep(1)
END
fi

# Execute migrations if requested via env
if [ "$RUN_MIGRATIONS" = "True" ] || [ "$RUN_MIGRATIONS" = "true" ]; then
    echo "==> Applying database migrations..."
    python manage.py migrate --noinput
fi

# Collect static assets if requested
if [ "$COLLECT_STATIC" = "True" ] || [ "$COLLECT_STATIC" = "true" ]; then
    echo "==> Collecting static assets..."
    python manage.py collectstatic --noinput
fi

exec "$@"
