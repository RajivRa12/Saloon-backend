from django.db import migrations
from django.core.management import call_command

def run_cleanup(apps, schema_editor):
    try:
        call_command('cleanup_dummy_data')
    except Exception as e:
        print(f"Warning during cleanup_dummy_data: {e}")

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0035_alter_service_name'),
    ]

    operations = [
        migrations.RunPython(run_cleanup, reverse_code=migrations.RunPython.noop),
    ]

