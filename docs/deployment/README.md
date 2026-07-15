# Deployment Guide — Veent Event Scraper

Production deployment on DigitalOcean using a single droplet running Django (gunicorn + nginx),
SvelteKit (Node adapter), and n8n as the pipeline scheduler.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [How the Scrapers Work](#2-how-the-scrapers-work)
3. [System Requirements](#3-system-requirements)
4. [Environment Variables](#4-environment-variables)
5. [One-Time Server Setup](#5-one-time-server-setup)
6. [Application Deployment](#6-application-deployment)
7. [n8n Pipeline Automation](#7-n8n-pipeline-automation)
8. [Session Cookie Renewal](#8-session-cookie-renewal)
9. [Monitoring & Maintenance](#9-monitoring--maintenance)

---

## 1. Architecture Overview

```
DigitalOcean Droplet (Ubuntu 24.04, 4 GB RAM minimum)
│
├── nginx  (port 80 / 443, TLS via certbot)
│   ├── /          → SvelteKit Node server  (port 3000)
│   ├── /api/*     → Django gunicorn        (port 8000)
│   └── /n8n/*     → n8n web UI             (port 5678)
│
├── gunicorn       — Django app server (WSGI)
│   └── apps/backend/   Django project
│       ├── Playwright + Chromium  (headless, via scraper jobs)
│       └── Groq API calls         (categorization + structuring)
│
├── SvelteKit      — operational dashboard (Node.js, port 3000)
│
└── n8n            — pipeline scheduler / webhook automator
    ├── POST /api/scrapers/run-all/   → triggers all active scrapers
    └── POST /api/pipeline/push/      → pushes new events to CRM
```

**Weekly pipeline (two separate n8n workflows):**

| Day | Step | What happens |
|---|---|---|
| Monday 2 AM | Scrape | n8n → `POST /api/scrapers/run-all/` → Django spawns a `ScraperRun` per active scraper; Playwright fetches FB/IG posts via DataImpulse proxy; Groq structures + categorizes; new `Event` rows saved to Neon DB |
| Tuesday 2 AM | Push | n8n → `POST /api/pipeline/push/` → Django sends events where `crm_pushed_at IS NULL` (or `updated_at > crm_pushed_at`) to the CRM ingest endpoint |

Splitting scrape and push across days gives the Monday run time to fully complete and
lets you review the dashboard before leads hit the CRM.

---

## 2. How the Scrapers Work

### Scraper types

| Key | Source | Mechanism |
|---|---|---|
| `facebook_posts` | Facebook search + pages | Playwright headless Chromium + cookies |
| `instagram_posts` | Instagram hashtags | Playwright headless Chromium + cookies |
| `allevents` | AllEvents.in API | HTTP REST (`ALLEVENTS_API_KEY`) |

### SearchQuery → ScraperRun lifecycle

Every active `SearchQuery` row in the database drives the scrapers.
A `SearchQuery` has a `source` field (`facebook_posts`, `instagram_posts`, `allevents`)
and a `query` string (keyword or URL for social scrapers, city/keyword for AllEvents).

When `POST /api/scrapers/run-all/` is received:

1. A `ScraperRun` row is created per scraper key (`status=queued`).
2. A background thread picks up each run (`status=running`, `started_at` stamped).
3. The scraper iterates all active `SearchQuery` rows for its source.
4. Raw posts / API results are fed through Groq to extract structured event fields.
5. Dedup runs against existing `Event` rows (title + date + venue fingerprint).
6. New events are saved; `_categorize_after_save()` assigns `agent_categories` via Groq.
7. Run finishes (`status=success`, `finished_at` stamped) or crashes (`status=failed`,
   `error_message` contains the full traceback).

### Playwright + session cookies (FB/IG)

Facebook and Instagram block headless browsers without a valid session. The scrapers:

1. Read cookie files from `FB_COOKIES_FILE` / `IG_COOKIES_FILE` on disk.
2. Inject them into a fresh Playwright browser context before navigating.
3. Use `playwright-stealth` to mask automation signals.
4. Route all traffic through a DataImpulse residential proxy (`DATAIMPULSE_USER/PASS`).

**Session expiry detection** — after navigating to each query URL the scraper checks
`page.url` for auth-redirect markers (`login`, `checkpoint`, `accounts/login`, etc.).
If detected, it raises `SessionExpiredError` which propagates to the run as `status=failed`
with `error_message` starting with `session_expired:<source>`. The dashboard surfaces this
as a red "Session Expired" badge on the Scraper Center and Dashboard pages.

### Groq API usage

- **Structuring** (`llama-3.3-70b-versatile`): converts raw FB/IG post text into
  structured event JSON (title, date, venue, description, tickets URL, organizer).
- **Categorization** (`llama-3.1-8b-instant`): assigns `agent_categories` to each event.
- Free tier: 14k requests/day, 131k tokens/minute. Sufficient for nightly pipeline runs.

### Proxy (DataImpulse)

Social platform scrapers on a server IP will be blocked within minutes without a
residential proxy. DataImpulse routes each request through a real residential IP in the
Philippines (`__cr.ph` suffix on the username). The AllEvents scraper does not need a proxy.

---

## 3. System Requirements

### Droplet spec

| Resource | Minimum | Recommended |
|---|---|---|
| RAM | 4 GB | 8 GB |
| CPU | 2 vCPU | 4 vCPU |
| Disk | 25 GB SSD | 50 GB SSD |
| OS | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |

Playwright spawns a Chromium process per scraper run. 4 GB RAM is the minimum to avoid OOM
kills; 8 GB is comfortable when two scrapers run concurrently.

### System packages (Ubuntu)

```bash
# Core
apt install -y python3.12 python3.12-venv python3-pip git nginx certbot python3-certbot-nginx

# Playwright Chromium system dependencies
apt install -y \
  libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
  libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
  libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libatspi2.0-0 libgtk-3-0

# Node.js 20+ (for SvelteKit and n8n)
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs

# pnpm
npm install -g pnpm
```

### External services / credentials required

| Service | Purpose | Where to get |
|---|---|---|
| Neon PostgreSQL | Database | neon.tech — free tier is sufficient |
| Groq API | AI structuring + categorization | console.groq.com |
| DataImpulse | Residential proxy for FB/IG | dataimpulse.com |
| Google Places API | Venue enrichment (optional) | console.cloud.google.com |
| AllEvents API | Event discovery API | allevents.developer.azure-api.net |
| Facebook cookies | FB scraper auth | Exported from your browser (see §8) |
| Instagram cookies | IG scraper auth | Exported from your browser (see §8) |

---

## 4. Environment Variables

Copy `apps/backend/.env.example` to `apps/backend/.env` and fill in every value.

```bash
# ── Django ────────────────────────────────────────────────────────────────────
SECRET_KEY=<long random string — use: python -c "import secrets; print(secrets.token_urlsafe(50))">
DEBUG=false
DATABASE_URL=postgresql://user:pass@host/dbname?sslmode=require

# ── Groq ──────────────────────────────────────────────────────────────────────
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_CATEGORIZE_MODEL=llama-3.1-8b-instant

# ── CRM ingest ────────────────────────────────────────────────────────────────
CRM_INGEST_URL=https://your-crm.example.com/api/leads/ingest
CRM_INGEST_SECRET=your-ingest-secret

# ── DataImpulse proxy ─────────────────────────────────────────────────────────
DATAIMPULSE_USER=your-username__cr.ph
DATAIMPULSE_PASS=your-password
# DATAIMPULSE_HOST=gw.dataimpulse.com   (default)
# DATAIMPULSE_PORT=823                  (default)

# ── Facebook scraper ──────────────────────────────────────────────────────────
FB_COOKIES_FILE=/home/veent/cookies/facebook.json
# FB_HEADLESS=true                      (default)

# ── Instagram scraper ─────────────────────────────────────────────────────────
IG_COOKIES_FILE=/home/veent/cookies/instagram.txt
# IG_HEADLESS=true                      (default)

# ── External APIs ─────────────────────────────────────────────────────────────
PLACES_API_KEY=AIza...
ALLEVENTS_API_KEY=your-key
```

**Do not commit `.env`** — it is in `.gitignore`. Store it in DigitalOcean's droplet directly
or use a secrets manager.

---

## 5. One-Time Server Setup

### 5.1 Create a deploy user

```bash
adduser veent
usermod -aG sudo veent
su - veent
```

### 5.2 Clone the repo

```bash
git clone https://github.com/<your-org>/veent-event-scraper.git /home/veent/app
cd /home/veent/app
```

### 5.3 Backend (Django)

```bash
cd apps/backend

# Create virtualenv and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Install Playwright's Chromium browser binary
playwright install chromium

# Copy and fill in environment variables
cp .env.example .env
nano .env

# Run database migrations
python manage.py migrate

# Create a superuser for Django admin
python manage.py createsuperuser

# Backfill: push all existing events to CRM (first deploy only)
python manage.py push_crm_leads --all

# Collect static files (Django admin + templates)
python manage.py collectstatic --noinput
```

### 5.4 Frontend (SvelteKit)

```bash
cd /home/veent/app
pnpm install
pnpm --filter frontend build
```

The build output lands in `apps/frontend/.svelte-kit/output/`. For production, use the
`@sveltejs/adapter-node` adapter (check `apps/frontend/svelte.config.js`) and run:

```bash
node apps/frontend/build/index.js
```

Or use PM2 to manage the process (see §6.3).

### 5.5 Create cookie directories

```bash
mkdir -p /home/veent/cookies
chmod 700 /home/veent/cookies
# Upload your exported cookie files here (see §8)
```

---

## 6. Application Deployment

### 6.1 Gunicorn (Django)

Create `/etc/systemd/system/veent-backend.service`:

```ini
[Unit]
Description=Veent Backend (gunicorn)
After=network.target

[Service]
User=veent
WorkingDirectory=/home/veent/app/apps/backend
ExecStart=/home/veent/app/apps/backend/venv/bin/gunicorn \
    --workers 2 \
    --bind 127.0.0.1:8000 \
    --timeout 300 \
    --log-file /var/log/veent/gunicorn.log \
    config.wsgi:application
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
mkdir -p /var/log/veent
systemctl daemon-reload
systemctl enable veent-backend
systemctl start veent-backend
```

The `--timeout 300` is important — scraper jobs can run for several minutes.

### 6.2 PM2 (SvelteKit)

```bash
npm install -g pm2
pm2 start apps/frontend/build/index.js --name veent-frontend -- --port 3000
pm2 save
pm2 startup   # follow the printed systemd command
```

### 6.3 nginx

Create `/etc/nginx/sites-available/veent`:

```nginx
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    client_max_body_size 10M;

    # Django API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }

    # Django admin + static
    location /admin/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /static/ {
        alias /home/veent/app/apps/backend/staticfiles/;
    }

    # n8n
    location /n8n/ {
        proxy_pass http://127.0.0.1:5678/;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # SvelteKit — catch-all
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

```bash
ln -s /etc/nginx/sites-available/veent /etc/nginx/sites-enabled/
certbot --nginx -d your-domain.com
nginx -t && systemctl reload nginx
```

### 6.4 n8n

```bash
npm install -g n8n

# Create systemd service
cat > /etc/systemd/system/veent-n8n.service << 'EOF'
[Unit]
Description=n8n workflow automation
After=network.target

[Service]
User=veent
Environment=N8N_HOST=your-domain.com
Environment=N8N_PORT=5678
Environment=N8N_PROTOCOL=https
Environment=WEBHOOK_URL=https://your-domain.com/n8n/
Environment=N8N_PATH=/n8n/
ExecStart=/usr/bin/n8n start
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable veent-n8n
systemctl start veent-n8n
```

---

## 7. n8n Pipeline Automation

The pipeline has two trigger endpoints. n8n calls them in sequence on a schedule.

### Endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/scrapers/run-all/` | Queues a `ScraperRun` for every active scraper |
| `POST /api/pipeline/push/` | Pushes unpushed/updated events to the CRM (fire-and-forget, guarded by a lock to prevent concurrent runs) |

### Schedule

The pipeline runs on a **weekly cadence**, split across two days:

| Day | Time (UTC) | Action |
|---|---|---|
| Monday | 2:00 AM | Scrape — `POST /api/scrapers/run-all/` |
| Tuesday | 2:00 AM | Push — `POST /api/pipeline/push/` |

Scraping on Monday gives the scrapers the full night to finish and lets the data settle
(dedup, categorization, any manual review). The push runs the next morning, so CRM leads
always reflect a clean, fully-categorized dataset.

### n8n workflow structure

Create **two separate workflows** in n8n — one for scraping, one for pushing.
Keeping them separate makes it easy to re-trigger either step independently.

**Workflow 1 — Weekly Scrape (Monday)**

```
Schedule Trigger
  Cron: 0 2 * * 1   (Monday 2 AM UTC)
        │
        ▼
HTTP Request — Scrape
  Method: POST
  URL: https://your-domain.com/api/scrapers/run-all/
```

**Workflow 2 — Weekly Push (Tuesday)**

```
Schedule Trigger
  Cron: 0 2 * * 2   (Tuesday 2 AM UTC)
        │
        ▼
HTTP Request — Push
  Method: POST
  URL: https://your-domain.com/api/pipeline/push/
```

**Authentication:** Django's CSRF is exempt on both endpoints (`@csrf_exempt`). If you expose
these URLs without additional auth, restrict them at the nginx level to the n8n server's IP,
or add a shared secret header check in the views.

**Checking run status:** `GET /api/scrapers/runs/?limit=20` returns recent runs with
`status`, `created_count`, and `error_message`. You can add an n8n HTTP Request node after
the scrape trigger to poll this endpoint and send a Slack/email alert if any run failed before
Tuesday's push.

---

## 8. Session Cookie Renewal

Facebook and Instagram session cookies expire roughly every 60 days. When they do,
the scraper raises `SessionExpiredError` and the run shows a red "Session Expired" badge
on the dashboard.

### How to renew

1. Open Chrome on your local machine and log in to Facebook / Instagram as the account
   used for scraping.
2. Install the [Cookie Editor](https://cookie-editor.com/) browser extension.
3. Navigate to `facebook.com` (or `instagram.com`).
4. Open Cookie Editor → **Export** → **Export as JSON**.
5. Save the file locally.
6. Upload it to the server:
   ```bash
   scp facebook.json veent@your-domain.com:/home/veent/cookies/facebook.json
   ```
7. Restart the backend to pick up the new cookies:
   ```bash
   systemctl restart veent-backend
   ```

**Tips:**
- Use a dedicated Facebook/Instagram account for scraping, not your personal account.
- Keep the account active — log in at least once a month to avoid session decay.
- Facebook cookies: export as JSON (Cookie Editor format). Instagram cookies: export as
  JSON or Netscape `.txt` format — both are supported by the scraper.

---

## 9. Monitoring & Maintenance

### Dashboard

The SvelteKit dashboard at `https://your-domain.com` shows:
- **Pipeline health strip** — last run status, DataImpulse quota, pending CRM push count.
- **Session status** — per-scraper badge; turns red when `error_message` contains
  `session_expired:<source>`.
- **Pipeline Runs page** (`/runs`) — filterable run history with expandable logs and
  full tracebacks.

### Logs

| Log | Location |
|---|---|
| gunicorn | `/var/log/veent/gunicorn.log` |
| Django app | Configured via `LOGGING` in `config/settings.py` |
| ScraperRun log | `GET /api/scrapers/runs/<id>/` → `log_output` field |
| n8n | `journalctl -u veent-n8n -f` |

### Deployment update checklist

After pulling new code:

```bash
cd /home/veent/app
git pull

# Backend
cd apps/backend
source venv/bin/activate
pip install -r requirements.txt       # only if requirements changed
python manage.py migrate              # only if new migrations
python manage.py collectstatic --noinput
systemctl restart veent-backend

# Frontend
cd /home/veent/app
pnpm install
pnpm --filter frontend build
pm2 restart veent-frontend
```

### DataImpulse quota

The dashboard shows monthly DataImpulse bandwidth usage (pulled from `BandwidthLog`).
Log in to the DataImpulse dashboard to top up or upgrade if the quota bar approaches 100%.

### Database backups

Neon PostgreSQL provides automatic daily backups on all plans. For additional safety,
schedule a weekly `pg_dump`:

```bash
# /etc/cron.weekly/veent-backup
pg_dump "$DATABASE_URL" | gzip > /home/veent/backups/veent_$(date +%F).sql.gz
find /home/veent/backups -mtime +30 -delete
```
