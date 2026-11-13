#!/bin/sh
set -e

echo "==> Running Django database migrations..."
python manage.py migrate --noinput

echo "==> Starting Gunicorn server on 0.0.0.0:${PORT:-8000}..."
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 2
