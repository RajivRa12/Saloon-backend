#!/bin/sh
set -e

echo "==> Running Django database migrations..."
python manage.py migrate --noinput || true

if [ "$SYNC_CLEAN_DATA" = "true" ]; then
    echo "==> SYNC_CLEAN_DATA is true: running sync_db.py..."
    python sync_db.py || true
fi

echo "==> Starting Gunicorn server on 0.0.0.0:${PORT:-8000}..."
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 2
