# Veent Event Scraper

Monorepo for scraping events, venues, and organizers (Facebook/Instagram via Playwright,
AllEvents API) and surfacing them in an operational dashboard that feeds a CRM.

## Stack

- **Backend** (`apps/backend/`) — Django 6 + gunicorn, PostgreSQL (Neon) in prod / SQLite in
  dev, Playwright/Chromium + `beautifulsoup4`/`lxml` scrapers, Groq for AI structuring &
  categorization, django-axes brute-force lockout.
- **Frontend** (`apps/frontend/`) — SvelteKit (Node adapter) dashboard that also acts as the
  per-user auth gate and reverse proxy to Django.
- **n8n** (`apps/n8n/`) — weekly pipeline scheduler (scrape → push to CRM).
- Tooling: pnpm workspace + Turborepo.

## Layout

```
apps/
  backend/        Django project (config/ settings + events/ app + scrapers)
  frontend/       SvelteKit dashboard, auth gate, /api proxy (src/hooks.server.ts)
  n8n/            Pipeline automation
  ollama/         Retired (categorization moved to Groq)
docs/
  deployment/     Deployment guide (Docker Compose + native)
  ...             Architecture, dedup, n8n, analysis docs
process/          Spec-driven workflow artifacts (plans, context, protocols)
docker-compose.yml, Caddyfile, .env.example   Container deployment
```

## Quick start (local dev)

```bash
# Backend
cd apps/backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env      # set DEBUG=true and a SECRET_KEY for dev
python manage.py migrate
python manage.py runserver          # http://127.0.0.1:8000

# Frontend (separate terminal, from repo root)
pnpm install
pnpm --filter frontend dev          # http://localhost:5173  (ENVIRONMENT=development → no auth gate)
```

The whole stack also runs via Turborepo from the repo root with `pnpm dev`.

## Deployment

See **[`docs/deployment/README.md`](docs/deployment/README.md)**. The recommended path is
Docker Compose behind Caddy (auto-HTTPS):

```bash
cp .env.example .env      # fill in secrets
docker compose up -d --build
docker compose exec backend python manage.py createsuperuser
```

A full native (droplet + nginx + systemd) runbook is documented in the same guide.

## Scraping

Scrapers are driven by `SearchQuery` rows and run via the dashboard or the
`POST /api/scrapers/run-all/` endpoint (n8n triggers this weekly). See the deployment guide
§2 for scraper internals (Playwright + session cookies, DataImpulse proxy, Groq structuring)
and `apps/backend/events/scrapers/` for the framework.
