#!/bin/sh
set -e

echo "==> Running Django database migrations..."
python manage.py migrate --noinput

echo "==> Ensuring default superuser exists..."
python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from apps.core.models import User
if not User.objects.filter(is_superuser=True).exists():
    User.objects.create_superuser('admin@nearbyme.com', 'password123')
    print('✔ Default superuser created: admin@nearbyme.com / password123')
else:
    print('✔ Superuser already exists.')
" || true

echo "==> Starting Gunicorn server on 0.0.0.0:${PORT:-8000}..."
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 2
