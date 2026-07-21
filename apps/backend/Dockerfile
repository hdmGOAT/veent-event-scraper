# syntax=docker/dockerfile:1

# Django backend: gunicorn WSGI app server plus Playwright/Chromium for the
# Facebook/Instagram scrapers. Playwright's own `--with-deps` installer pulls
# Chromium and every OS library it needs, so the long manual apt list from the
# native runbook (libnss3, libatk, ...) is not required here.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/apps/backend

# Build/runtime libraries for lxml and psycopg2 wheels.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential libxml2-dev libxslt1-dev libpq-dev curl \
 && rm -rf /var/lib/apt/lists/*

# Python deps first so the layer is cached across code-only changes.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Chromium + its OS dependencies.
RUN playwright install --with-deps chromium

# Application code.
COPY . .

# Entrypoint applies migrations + collects static assets, then execs the CMD.
# Invoked via `sh` so it does not depend on the host file's execute bit.
ENTRYPOINT ["sh", "docker-entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--timeout", "300", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
