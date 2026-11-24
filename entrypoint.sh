#!/bin/sh
set -e

python - <<'PY'
import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from django.db import connection
schema = os.environ.get("POSTGRES_SCHEMA", "nio_gc_tickets")
engine = connection.settings_dict.get("ENGINE", "")
if engine.endswith("postgresql"):
    with connection.cursor() as cur:
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    print(f"schema ok: {schema}")
else:
    print("sqlite/local — skip schema")
PY

python manage.py migrate --noinput
python manage.py createcachetable
python manage.py collectstatic --noinput
python manage.py seed_nio || true

PORT=${PORT:-8000}
# Timeout 180s: import OSAB ainda pode ser pesado; a causa principal do 500
# (full-scan Sysmap por PDV) foi corrigida no código — isto é só folga.
exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} --workers 2 --timeout 180 --access-logfile - --error-logfile -
