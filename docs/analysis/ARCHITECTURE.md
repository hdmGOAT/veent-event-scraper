# Architecture Overview

> A systems-level view of the Veent Event Scraper — how components fit together, data flows, and cross-cutting concerns.

---

## System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser / n8n                                                   │
│  (user or automation)                                           │
└────────────────┬────────────────────────────────────────────────┘
                 │  HTTP
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│  SvelteKit Frontend  (apps/frontend/)                           │
│  Vite dev-proxy: /api/* → localhost:8000                        │
└────────────────┬────────────────────────────────────────────────┘
                 │  HTTP (proxied in dev, direct in prod)
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│  Django 6.0 Backend  (apps/backend/)                            │
│                                                                 │
│  views.py (30+ endpoints)                                       │
│    ├── HTML pages                                               │
│    ├── JSON API (/api/*)                                        │
│    └── Webhooks (/webhooks/*)                                   │
│                                                                 │
│  runner.py                                                      │
│    └── trigger_scraper_run() → subprocess (manage.py run_scraper_job)
│                                                                 │
│  ai_categories.py                                               │
│    └── batch_categorize() → subprocess (claude CLI)            │
└───────┬─────────────────────────────────────────────────────────┘
        │                         │
        │ SQLite (dev)            │ subprocess
        │ PostgreSQL (prod)       │
        ▼                         ▼
┌───────────────┐    ┌────────────────────────────────────────────┐
│  Database     │    │  Scraper Worker Process                    │
│               │    │  (management/commands/run_scraper_job.py)  │
│  Event        │    │                                            │
│  Venue        │    │  BaseScraper subclass (one of 22)          │
│  Organizer    │◄───│    └── save_events() → DB writes           │
│  ScraperRun   │    │                                            │
│  SearchQuery  │    │  facebook_events.py:                       │
│  TrackerNote  │    │    └── Playwright → Chromium               │
└───────────────┘    │         └── proxy (DataImpulse or free)    │
                     │         └── CDP bandwidth tracking         │
                     │                                            │
                     │  _DBLogHandler → ScraperRun.log_output     │
                     └────────────────────────────────────────────┘
```

---

## Component Breakdown

### Frontend — `apps/frontend/`

**Technology:** SvelteKit + TypeScript + Vite

The frontend is a thin admin UI. It fetches data from the Django JSON API and presents:
- Event list, search, and detail
- Venue and organizer management
- Scraper status dashboard (trigger, cancel, view logs)
- Settings (proxy toggle, search queries)

**Key file:** [apps/frontend/src/lib/api.ts](../../apps/frontend/src/lib/api.ts) — typed `djangoApi` client with `fetch` wrappers for all Django API endpoints.

**Notable issue:** A dead `nodeApi` client exists pointing to `/node-api/*` — no Node.js backend is present in the repo. See [TD-11](TECHNICAL-DEBT.md#td-11--low--dead-nodeapi-client-in-the-frontend--no-nodejs-backend-exists).

**Dev proxy:** `vite.config.ts` proxies `/api/*` and `/webhooks/*` to `localhost:8000`, so browser CORS checks are bypassed in development. Production deployment needs explicit CORS configuration. See [SEC-8](SECURITY.md#sec-8--low--no-cors-configuration).

---

### Backend — `apps/backend/`

**Technology:** Django 6.0 + Python

The backend is a single Django app (`events`) containing all models, views, scrapers, and business logic.

#### Settings (`config/settings.py`)

- Custom `_load_dotenv()` replaces `python-dotenv` (see [TD-6](TECHNICAL-DEBT.md#td-6--medium--custom-env-loader-instead-of-python-dotenv))
- Hardcoded `SECRET_KEY` and `DEBUG = True` (see [SEC-1](SECURITY.md#sec-1--critical--hardcoded-secret_key-committed-to-source), [SEC-3](SECURITY.md#sec-3--high--debug--true-hardcoded))
- Database: SQLite in dev, PostgreSQL in prod via `dj_database_url`
- No installed CORS middleware

#### Models (`events/models.py`)

Six models, all in the `events` app:

| Model | Purpose | Key fields |
|---|---|---|
| `Event` | Core scraped event record | `title`, `slug`, `venue`, `organizer_ref`, `agent_categories` (JSON), `is_active` |
| `Venue` | Physical or online location | `name`, `slug`, `city`, `status` (TextChoices) |
| `Organizer` | Event organizer entity | `name`, `slug`, `website`, `status` (plain constants — inconsistent, see [TD-8](TECHNICAL-DEBT.md#td-8--medium--organizer-uses-plain-string-constants-venue-uses-textchoices--inconsistent-patterns)) |
| `TrackerNote` | Free-text notes on any entity | generic FK via `content_type` / `object_id` |
| `SearchQuery` | Keywords used by scrapers | `keyword`, `location`, `scraper_key` |
| `ScraperRun` | Audit record for each run | `scraper_key`, `status`, `log_output`, `extra_counts` (JSON), `started_at`, `finished_at` |

`ScraperRun` has a partial unique constraint (`unique_active_scraper_run`) preventing two simultaneous runs of the same scraper key.

#### Views (`events/views.py`)

1233-line god object. See [TD-1](TECHNICAL-DEBT.md#td-1--high--viewspy-is-a-1233-line-god-object-mixing-html-api-and-webhook-concerns) for the recommended split.

All action endpoints are `@csrf_exempt` with no authentication. See [SEC-2](SECURITY.md#sec-2--high--all-action-api-endpoints-are-unauthenticated).

#### Scraper Registry (`events/scrapers/__init__.py`)

22 scrapers are registered in the `SCRAPERS` dict, keyed by a string identifier (e.g., `"facebook_events"`, `"meetup_events"`). Each value is the scraper class (not an instance).

The registry is the authoritative list of available scrapers. The `runner.py` and views look up scrapers by key from this registry.

#### Base Scraper (`events/scrapers/base.py`)

`BaseScraper` is the abstract base class all scrapers inherit from. It provides:
- `scrape()` — abstract method subclasses must implement, returning a list of `ScrapedEvent`
- `save_events()` — persists scraped events to the database, resolves organizers, deduplicates
- `save_venues()` — persists scraped venues
- `_resolve_organizer()` — matches a scraped organizer to an existing `Organizer` record (O(n) scan — see [BUG-1](BUGS.md#bug-1--high--_resolve_organizer-performs-a-full-table-scan-on-every-save))
- `_dedup_after_save()` — removes duplicate events after saving

557 lines — should be split. See [TD-2](TECHNICAL-DEBT.md#td-2--high--basepy-is-a-557-line-mixed-responsibility-module).

#### Runner (`events/runner.py`)

`trigger_scraper_run(key, search_queries)` orchestrates scraper execution:

1. Creates a `ScraperRun` record with `status=RUNNING`
2. Spawns `python manage.py run_scraper_job <run_id>` as a subprocess with `start_new_session=True`
3. Returns the `ScraperRun` immediately (fire-and-forget)

The subprocess writes its result back to the database via the `ScraperRun` record's `log_output` and `extra_counts` fields. Django does not track the subprocess PID beyond `ScraperRun.pid`.

`cancel_run(run_id)` sends `SIGTERM` to the process group (POSIX only — see [BUG-7](BUGS.md#bug-7--medium--cancel_run-uses-oskillpg--posix-only-crashes-on-windows)).

#### Scraper Worker (`events/management/commands/run_scraper_job.py`)

The worker subprocess:
1. Loads the `ScraperRun` by PK
2. Resolves the scraper class from the registry
3. Loads `SearchQuery` records for this scraper
4. Calls `scraper.scrape(search_queries)` → `scraper.save_events(events)`
5. Updates `ScraperRun.status` to `SUCCESS` or `ERROR`
6. Sets `DJANGO_ALLOW_ASYNC_UNSAFE=true` globally (see [TD-12](TECHNICAL-DEBT.md#td-12--low--django_allow_async_unsafetrue-set-globally-in-the-scraper-worker-subprocess))

A custom `_DBLogHandler` flushes log lines to `ScraperRun.log_output` every 2 seconds, capped at 2000 lines.

#### Facebook Events Scraper (`events/scrapers/facebook_events.py`)

The most complex scraper at 1267 lines. Uses Playwright (synchronous API) to drive a headless Chromium browser. Key behaviors:

- **Proxy selection:** Tries DataImpulse residential proxy first; falls back to free rotating proxy from `proxy_manager.py`
- **Stealth:** Uses `playwright_stealth` to reduce bot-detection fingerprint
- **CDP bandwidth tracking:** Uses Chrome DevTools Protocol to measure data transferred per keyword
- **Keyword retry:** Up to 5 retries per keyword (`_KEYWORD_RETRIES=5`), rotating proxies on failure
- **Modal dismissal:** Injects `_DISMISS_MODAL_JS` to close cookie consent and login prompts
- **Extraction:** Four inline JS strings extract event data at different page stages
- **Certificate bypass:** `--ignore-certificate-errors` when on free proxies (see [SEC-5](SECURITY.md#sec-5--high--ignore-certificate-errors-passed-to-chromium-globally-when-using-free-proxies))

#### AI Categorization (`events/ai_categories.py`)

Shells out to the `claude` CLI (Haiku model) to categorize events into one of 15 canonical categories. Called as a batch operation on uncategorized events. Does not check subprocess return code (see [BUG-5](BUGS.md#bug-5--medium--batch_categorize-ignores-non-zero-subprocess-return-code)).

---

## Data Flow — Scraper Run

```
1. User/n8n → POST /api/scrapers/<key>/run/
2. views.py → runner.trigger_scraper_run(key)
3. runner.py → ScraperRun.objects.create(status=RUNNING)
4. runner.py → subprocess: manage.py run_scraper_job <run_id>
5. worker  → scraper.scrape(search_queries)
            → for each keyword:
               → Playwright opens browser (with proxy)
               → navigates to facebook.com/events/search?q=<keyword>
               → extracts event cards (JS injection)
               → for each event URL:
                  → navigate to event detail page
                  → extract event data (JS injection)
                  → extract organizer data (JS injection)
               → returns list[ScrapedEvent]
6. worker  → BaseScraper.save_events(events)
            → for each event:
               → _resolve_organizer() [O(n) scan]
               → Event.objects.update_or_create(slug=...)
            → _dedup_after_save(saved_ids, updated_ids)
7. worker  → ScraperRun.objects.update(status=SUCCESS, extra_counts={...})
8. Frontend polls GET /api/scrapers/runs/<id>/ until status != RUNNING
```

---

## Cross-Cutting Concerns

### Authentication & Authorization

Currently absent for all API endpoints. The system is designed as a trusted internal tool. See [SEC-2](SECURITY.md#sec-2--high--all-action-api-endpoints-are-unauthenticated) for the full risk assessment.

### Proxy Architecture

Two proxy tiers:

| Tier | Provider | File | Cost | Reliability |
|---|---|---|---|---|
| Primary | DataImpulse residential | `social_proxy.py` | Paid (per GB) | High |
| Fallback | Public GitHub proxy lists | `proxy_manager.py` | Free | Very low (~1% pass rate) |

The Facebook scraper tries DataImpulse first. If no DataImpulse credentials are configured, it falls back to free proxies. Free proxy election can take 30–60 seconds and requires disabling SSL verification.

### Database Schema

SQLite in development, PostgreSQL in production. Several features only work in production:
- `distinct("field")` queries (see [BUG-4](BUGS.md#bug-4--high--api_scrapers-uses-postgresql-specific-distinctscraper_key--crashes-on-sqlite))
- `psycopg2` in dedup tests (see [BUG-11](BUGS.md#bug-11--low--psycopg2extrarealdictcursor-imported-in-tests--fails-on-sqlite))
- Database-level advisory locks for dedup serialization

This means certain code paths cannot be tested locally without a PostgreSQL instance.

### Process Model

Django runs as the main process. Scrapers run as independent child processes (one per scraper run). The `ScraperRun` table is the shared communication channel between parent and child:

- Parent writes: `ScraperRun.pid`, `status=RUNNING`
- Child writes: `log_output` (via `_DBLogHandler`), `extra_counts`, `status=SUCCESS/ERROR`
- Parent reads: `status`, `log_output` (served to frontend via API)

There is no IPC beyond the database. This is simple but means:
- A crashed child leaves the run in `RUNNING` state indefinitely
- There is no backpressure — any number of scrapers can run simultaneously (until the unique constraint fires)

### Monorepo Structure

```
veent-event-scraper/
├── apps/
│   ├── backend/    Django (Python) — main product
│   └── frontend/   SvelteKit (TypeScript) — admin UI
├── docs/           Documentation
├── process/        RIPER-5 plans and context
├── scripts/        Standalone utilities (deduplicate.py)
├── turbo.json      Turborepo task graph
└── package.json    pnpm workspace root
```

Turborepo coordinates builds, but the two apps are largely independent — the frontend calls the backend's HTTP API and has no shared code.

---

## Key Risks Summary

| Risk | Severity | Category | Reference |
|---|---|---|---|
| Hardcoded SECRET_KEY in git | CRITICAL | Security | [SEC-1](SECURITY.md#sec-1--critical--hardcoded-secret_key-committed-to-source) |
| All APIs unauthenticated | HIGH | Security | [SEC-2](SECURITY.md#sec-2--high--all-action-api-endpoints-are-unauthenticated) |
| No task queue / process leaks on crash | HIGH | Architecture | [TD-4](TECHNICAL-DEBT.md#td-4--medium--no-task-queue--all-long-running-work-blocks-the-request-or-spawns-unmanaged-subprocesses) |
| O(n) organizer scan per event save | HIGH | Performance | [PERF-1](PERFORMANCE.md#perf-1--high--_resolve_organizer-on-python-scan-on-every-save_events-call) |
| TOCTOU slug race → IntegrityError | HIGH | Bug | [BUG-3](BUGS.md#bug-3--high--_unique_slug-has-a-toctou-race-condition) |
| SQLite/PostgreSQL divergence | HIGH | Architecture | [BUG-4](BUGS.md#bug-4--high--api_scrapers-uses-postgresql-specific-distinctscraper_key--crashes-on-sqlite) |
| Webhook blocks Django worker thread | MEDIUM | Architecture | [TD-5](TECHNICAL-DEBT.md#td-5--medium--webhook-handler-is-synchronous--blocks-django-worker-thread-for-the-full-scraper-duration) |
| Process-local dedup lock | MEDIUM | Bug | [TD-9](TECHNICAL-DEBT.md#td-9--medium--process-local-_dedup_lock-provides-no-protection-across-multiple-django-workers) |
