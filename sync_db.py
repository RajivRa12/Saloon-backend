import os
import sys
import django

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connection, transaction
from django.core.management import call_command
from apps.core.models import User

print("==> [sync_db] Starting database sync...", flush=True)

# 1. Clean out old dummy users (keep only the 4 clean local users)
clean_emails = [
    'admin@nearbyme.com',
    'manager@rootsmenssalonalpha.com',
    'rfdsdgsg@gmail.com',
    '919840256789@phone.nearbyme.local'
]

try:
    deleted_count, _ = User.objects.exclude(email__in=clean_emails).delete()
    print(f"==> [sync_db] Removed {deleted_count} old dummy records.", flush=True)
except Exception as e:
    print(f"==> [sync_db] Note while cleaning users: {e}", flush=True)

# 2. Load the clean database fixture
fixture_file = 'clean_database_backup.json'
if os.path.exists(fixture_file):
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                try:
                    cursor.execute("SET CONSTRAINTS ALL DEFERRED;")
                except Exception:
                    pass
            call_command('loaddata', fixture_file)
        print("==> [sync_db] Clean database fixture loaded successfully!", flush=True)
    except Exception as e:
        print(f"==> [sync_db] Note while loading fixture: {e}", flush=True)
else:
    print(f"==> [sync_db] Fixture {fixture_file} not found, skipping fixture load.", flush=True)

# 3. Ensure superuser exists and has correct password
try:
    admin = User.objects.filter(email='admin@nearbyme.com').first()
    if not admin:
        admin = User.objects.create(
            email='admin@nearbyme.com',
            username='admin@nearbyme.com',
            role='ADMIN',
            is_staff=True,
            is_superuser=True,
            is_active=True
        )
    admin.is_staff = True
    admin.is_superuser = True
    admin.is_active = True
    admin.set_password('password123')
    admin.save()
    print(f"==> [sync_db] Superuser {admin.email} verified with password123.", flush=True)
except Exception as e:
    print(f"==> [sync_db] Note while setting superuser: {e}", flush=True)

print(f"==> [sync_db] Current total users: {User.objects.count()}", flush=True)
print("==> [sync_db] Database sync completed.", flush=True)
