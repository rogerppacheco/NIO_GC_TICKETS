from django.db import migrations
from django.core.management import call_command

def load_fixture(apps, schema_editor):
    call_command('loaddata', 'guia_pendencias.json', app_label='tickets')

def unload_fixture(apps, schema_editor):
    GuiaPendencia = apps.get_model('tickets', 'GuiaPendencia')
    GuiaPendencia.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0036_guiapendencia'),
    ]

    operations = [
        migrations.RunPython(load_fixture, reverse_code=unload_fixture),
    ]
