#!/bin/sh
set -e

# Runs on every container start. Both commands are idempotent and safe to re-run:
#   migrate      — applies any pending DB migrations (includes django-axes tables)
#   collectstatic — gathers admin/template static assets for WhiteNoise to serve
python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
