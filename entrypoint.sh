#!/bin/sh
set -e

echo "==> Running Django database migrations..."
python manage.py migrate --noinput

if [ "$SYNC_CLEAN_DATA" = "true" ]; then
    echo "==> SYNC_CLEAN_DATA is set to true: flushing old data and loading clean backup..."
    python manage.py flush --noinput
    python manage.py loaddata clean_database_backup.json
    echo "==> Clean database backup loaded successfully!"
fi

echo "==> Starting Gunicorn server on 0.0.0.0:${PORT:-8000}..."
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 2
