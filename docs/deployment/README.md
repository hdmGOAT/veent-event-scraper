# Deployment Guide — Veent Event Scraper

Two supported deployment paths:

1. **Docker Compose (recommended)** — the whole stack in three containers behind Caddy
   (automatic HTTPS). Fastest path: `cp .env.example .env` → fill secrets → `docker compose up -d --build`.
   See [Quick Start](#0-quick-start--docker-compose-recommended) below.
2. **Native / manual** — a single droplet running Django (gunicorn + nginx) and SvelteKit
   (Node adapter) directly on the host. Documented in full from §3 onward.

Both use the same environment variables. In Docker Compose, the database runs as a local
Postgres container. In native deployments, point `DATABASE_URL` at any reachable Postgres
instance (local or managed).

---

## 0. Quick Start — Docker Compose (recommended)

This runs Django (gunicorn + Playwright/Chromium), the SvelteKit dashboard, and a local
Postgres database as containers, with **Caddy** terminating TLS and reverse-proxying to them.
The Playwright system-package list is baked into the backend image, and Caddy fetches and
renews Let's Encrypt certificates automatically — no `apt` marathon, no certbot.

### Prerequisites

- A host with Docker Engine + the Compose plugin (`docker --version`, `docker compose version`).
- A domain's A record pointing at the host, with ports **80** and **443** reachable
  (required for automatic TLS). For a purely local run, set `DOMAIN=localhost` — Caddy
  serves a self-signed cert.
- Groq / DataImpulse / API credentials (see `.env.example`).

### Steps

```bash
git clone https://github.com/<your-org>/veent-event-scraper.git
cd veent-event-scraper

# 1. Configure — copy the root example and fill in every secret.
cp .env.example .env
nano .env
#   - SECRET_KEY: generate fresh → python3 -c "import secrets; print(secrets.token_urlsafe(50))"
#   - DEBUG=false, DOMAIN=your-domain.com, ALLOWED_HOSTS=your-domain.com
#   - POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB — local DB credentials (your choice)
#   - DATABASE_URL=postgresql://<user>:<pass>@postgres:5432/<db>
#   (ALLOWED_HOSTS gets `,backend` appended automatically for internal calls.)

# 2. Drop the FB/IG session cookie files where the backend can read them.
mkdir -p cookies
#   cp facebook.json cookies/facebook.json   (matches FB_COOKIES_FILE=/cookies/facebook.json)
#   cp instagram.txt cookies/instagram.txt   (matches IG_COOKIES_FILE=/cookies/instagram.txt)

# 3. Build and start everything.
docker compose up -d --build
#   The backend entrypoint runs `migrate` + `collectstatic` automatically on start.

# 4. Create the first login account (no shared password — see §5).
docker compose exec backend python manage.py createsuperuser
```

Open `https://your-domain.com` → you'll be redirected to `/login`.

### How the pieces map

| Container | Role | Reachable via |
|---|---|---|
| `caddy` | TLS + reverse proxy (ports 80/443) | the only public entrypoint |
| `frontend` | SvelteKit dashboard, auth gate, `/api` proxy | Caddy `/*` |
| `backend` | Django gunicorn + Playwright scrapers | Caddy `/admin/`, `/static/`; internal `backend:8000` |
| `postgres` | local Postgres database | internal `postgres:5432` only — never exposed publicly |

The database is a container (`postgres:16`) with a named Docker volume (`postgres_data`).
Data persists across restarts. Back up the volume before destructive operations.

### Everyday operations

```bash
docker compose logs -f backend           # tail gunicorn / scraper logs
docker compose exec backend python manage.py axes_reset --username <name>   # unlock a user
docker compose exec backend python manage.py push_crm_leads --all           # first-deploy CRM backfill

# Update after pulling new code:
git pull && docker compose up -d --build   # entrypoint re-runs migrate + collectstatic
```

### Notes & caveats

- **`/node-api/*` is unwired.** `NODE_API_URL` has no service in this repo (the old Node/ollama
  path was removed); leave it unset. Any dashboard feature that calls `/node-api/*` returns 502
  until such a service is added — this is pre-existing, not introduced by Docker.
- The backend container currently runs as root (needed for the Playwright browser cache). A
  non-root hardening pass is a reasonable future improvement.
- The sections below (§3–§10) remain the reference for the **native** deployment and for the
  deeper operational topics (scraper internals, auth model, cookie renewal, monitoring) that
  apply to both paths.
