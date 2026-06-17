# Veent Event Scraper - All Context

Last updated: 2026-06-17 (rev 3 — monorepo + Neon Postgres + 10 scrapers + ScraperRun run-jobs + category normalization)

This file is the root context entrypoint for the repo.

Use it for two things:

1. quick routing to the right context pack or root file
2. broad architecture and repository understanding

Start here before loading deeper context files.

---

## Project Overview

**Veent Event Scraper** is a web-based **administrative platform** for automatically
collecting, processing, managing, and analyzing event information from multiple online
sources — public event platforms, venue websites, educational institutions, community
organizations, and other publicly accessible sources.

In the operators' own words, the system aggregates events into a unified database and
gives administrators tools to monitor scraping operations, review collected data, detect
duplicate events, manage event records, and export datasets for analysis or integration
with external systems.

**Objectives:**

- Automate event data collection from multiple online sources.
- Centralize event information into a unified database.
- Reduce manual effort in discovering and organizing events.
- Detect and merge duplicate event records (cross-source deduplication is a **core target feature**).
- Provide administrators with monitoring and management tools.
- Enable export of structured event datasets (CSV/Excel and JSON/REST API are planned).
- Support future integration with additional event sources and APIs.

**Current state vs. target:** The repo is a working **pnpm/Turborepo monorepo** with two apps:
`apps/backend/` (Django 6 on Neon PostgreSQL) and `apps/frontend/` (SvelteKit 2 + Svelte 5).
Four models (Venue, Event, Organizer, ScraperRun) cover scraping provenance, dedup, admin
review workflows, and UI-triggered run jobs. A pluggable scraper framework registers 10
scrapers; a `manage.py scrape` command and JSON API endpoints both drive them. The backend
also exposes display-layer category normalization (`events/categories.py`) and a staff
`/review/` UI; Django admin remains a secondary raw-data console. The primary operator surface
is the CSR-only SvelteKit frontend with five routes (`/`, `/events`, `/organizers`, `/venues`,
`/scrapers`) — a Scraper Center with Run / Run All / run-history, charts, sortable tables, and
a shared component library, backed by the JSON endpoints. The larger product vision (fuzzy
cross-source dedup/merge, CSV + JSON/REST export, CI, production hardening) is **not yet built**
— it is the roadmap this codebase grows into.

**Audience / interface decisions:**

- Primary admin interface: **SvelteKit frontend** (Scraper Center, monitoring, managing scrapers).
- Secondary admin interface: **Django's built-in admin** (raw-data console for all models).
- Scraper triggering: **UI-triggered** via Scraper Center (POST to `/api/scrapers/<key>/run/`
  or `/api/scrapers/run-all/`); also triggerable via `manage.py scrape`.
- Scraper scheduling: **manual / OS cron** (no Celery/queue).
- Team project; tests run on Neon PostgreSQL; 97 tests currently passing.

---

## How This File Works

Agents: read this first → find context group in the routing tables below → read `all-{group}.md` → only then load the specific deep doc. Never load the whole `process/context/` tree.

---

## Quick Start

For most substantial tasks:

1. read this file first
2. choose the smallest relevant root file or context group from the tables below
3. only then load deeper files

**Critical context-freshness rule:** Before planning or implementing, validate the working
tree against this file. `all-context.md` can drift (e.g., monorepo layout, DB engine, scraper
count). If unsure, scan `apps/backend/events/scrapers/__init__.py` for the real SCRAPERS
registry, and the latest migration number from `apps/backend/events/migrations/`.

---

## Current Root Entry Points

| File | Read when |
|---|---|
| `process/context/all-context.md` | any substantial planning, research, review, or implementation task |
| `process/context/tests/all-tests.md` | testing, verification, debugging test failures, execution planning |
| `process/context/planning/all-planning.md` | plan-shape calibration, planning examples, SIMPLE vs COMPLEX reference docs |

## Current Context Groups

| Group | Entry point | Scope |
|---|---|---|
| `planning/` | `process/context/planning/all-planning.md` | plan-shape calibration, planning examples, SIMPLE vs COMPLEX reference docs |
| `tests/` | `process/context/tests/all-tests.md` | test runner, commands, debugging, gaps |

No `database/`, `auth/`, or `infra/` context groups exist yet. The data layer is documented
inline below (four models, several migrations). A `scrapers/` context group is a strong
candidate — the project now has 10 scrapers across two distinct patterns plus a run-jobs
subsystem. Create it when scraper-specific docs genuinely exceed one screen of inline prose
or a second durable scraper doc is added. A `frontend/` context group may also be warranted
as the SvelteKit app grows.

## Task Routing Table

| If the task involves... | Start with | Then load |
|---|---|---|
| architecture or stack questions | this file | — |
| adding or changing a scraper | this file (Scraper Framework section) | `apps/backend/events/scrapers/base.py`, `apps/backend/events/scrapers/__init__.py`, existing scraper for pattern |
| scraper run jobs / run API | this file (Run-Jobs subsystem section) | `apps/backend/events/runner.py`, `apps/backend/events/views.py` |
| category normalization | this file (Backend API section) | `apps/backend/events/categories.py`, `apps/backend/events/views.py` |
| models / schema / migrations | this file (Data Model section) | `apps/backend/events/models.py`, `apps/backend/events/migrations/` |
| admin behavior | this file (Admin section) | `apps/backend/events/admin.py` |
| backend views / API | this file (Backend API section) | `apps/backend/events/views.py`, `apps/backend/events/urls.py` |
| Django templates / `/review/` UI | this file (Web UI section) | `apps/backend/events/views.py`, `apps/backend/templates/` |
| SvelteKit frontend routes / components | this file (Frontend section) | `apps/frontend/src/routes/`, `apps/frontend/src/lib/` |
| testing or verification | `process/context/tests/all-tests.md` | the specific test file |
| creating a new plan | `process/context/planning/all-planning.md` | the relevant example PRD |
| context maintenance | this file | run `audit-context` after edits |

---

## Repository Structure

Monorepo managed with **pnpm workspaces + Turborepo**.

```
veent-event-scraper/
  apps/
    backend/                          -- Django 6 backend
      manage.py
      config/                         -- Django project package (settings.py, urls.py)
      events/                         -- single Django app
        models.py                     -- Venue, Event, Organizer, ScraperRun
        views.py                      -- function-based views: public list/detail + /review/ + JSON API
        urls.py                       -- app URLConf (namespace "events")
        admin.py
        runner.py                     -- trigger_scraper_run, cancel_run (subprocess-based)
        categories.py                 -- normalize_category(): display-layer normalization
        tests.py                      -- 97 tests
        migrations/                   -- 0001–0011 applied
        scrapers/
          base.py                     -- BaseScraper + ScrapedEvent/Venue/Organizer + save_events/save_organizers
          allevents.py / happeningnext.py  -- Playwright scrapers
          myruntime.py / luma.py / eventbrite.py  -- JSON API scrapers
          ticket2me.py / planout.py / racemeister_events.py  -- requests+BS4 event scrapers
          racemeister.py              -- requests+BS4 organizer scraper
          places.py                   -- Google Places venue scraper
          __init__.py                 -- SCRAPERS registry {key -> class}
        management/commands/
          scrape.py / run_scraper_job.py
      templates/                      -- secondary surface (legacy list/detail + /review/)
    frontend/                         -- SvelteKit 2 + Svelte 5 (primary admin UI, CSR-only)
      vite.config.ts                  -- Tailwind v4 plugin + runes enforced; proxy /api → :8000
      src/
        app.css                       -- @theme {} design tokens
        routes/                       -- /, /events, /organizers, /organizers/[slug], /venues, /scrapers
        lib/
          components/                 -- Sidebar, PageHeader, Badge, StatCard, BarChart, DonutChart, TableSkeleton, SortHeader
          api.ts                      -- typed fetch wrappers for all /api/* endpoints
          types.ts / format.ts / sort.ts
          index.ts                    -- barrel re-exports
  process/                            -- agent harness workspace (context, plans, protocols)

NOTE: root-level events/ and config/ directories are vestigial dead shells from before the
monorepo conversion. Do NOT use them as references. All active code lives under apps/.
```

## Technology Stack

**Monorepo tooling:**
- **Workspace manager:** pnpm workspaces + Turborepo (`turbo.json`)

**Backend (`apps/backend/`):**
- **Framework:** Django 6.0.x
- **Language / runtime:** Python (venv at `apps/backend/venv/`)
- **Database:** **Neon PostgreSQL** via `dj_database_url` (configured via the `DATABASE_URL`
  env var). SQLite is no longer used in any environment.
- **Scraping:** `requests` for HTTP, `beautifulsoup4` + `lxml` for HTML parsing, Playwright
  for JS-heavy scrapers
- **Admin:** Django's built-in admin (`django.contrib.admin`) as a secondary raw-data console
- **Backend templates:** server-rendered Django templates still exist (legacy list/detail views + `/review/` UI); no JS framework on that surface
- **API:** plain Django `JsonResponse` views (no DRF) — mostly GET, plus the POST scraper-run
  trigger endpoints — consumed by the SvelteKit frontend
- **Category normalization:** `events/categories.py` (`normalize_category`) maps raw scraper
  category strings to display buckets at the API layer (no stored field mutated)
- **Package manager (Python):** pip + `requirements.txt`, virtualenv (`venv/`)
- **Auth:** Django's built-in `django.contrib.auth` for Django admin + `/review/` staff UI
  (`@staff_member_required`). The SvelteKit frontend has **no auth bridge to Django** — the
  "Admin User" display in the sidebar is static HTML; no login flow exists in the SvelteKit
  app. JSON API auth posture is described in the API Surface section below.

**Frontend (`apps/frontend/`):**
- **Framework:** SvelteKit 2
- **Language:** TypeScript + Svelte 5 (runes mode forced via `vite.config.ts` `compilerOptions.runes`)
- **Rendering:** CSR-only (`export const ssr = false` in `+layout.ts`); no SSR, no hydration concerns
- **Styling:** Tailwind CSS v4 via `@tailwindcss/vite` plugin; design tokens in `src/app.css` `@theme {}`
- **Charts:** Chart.js (wrapped in `BarChart.svelte` and `DonutChart.svelte`)
- **Icons:** lucide-svelte
- **Build:** Vite; dev proxy routes `/api` → Django at `:8000`
- **Package manager (JS):** pnpm

## Data Model

Four models in `apps/backend/events/models.py`, all carrying provenance fields (`source`,
`source_url`, `scraped_at`) on the data models:

- **`Venue`** — physical place: name, unique `slug`, address/city/country, website,
  lat/long, `primary_type_display`. Ordered by name. `get_absolute_url` → `events:venue_detail`.
  Carries a **`verification_status`** field (`Venue.VerificationStatus` TextChoices: `pending`
  / `verified` / `rejected`, default `pending`, indexed) — set only by staff (admin actions or
  the `/review/` UI); **never written by the scraper upsert path**, so reviewer decisions
  survive re-scrapes.

- **`Event`** — a scraped event, optional FK to `Venue` (`on_delete=SET_NULL`,
  `related_name="events"`), optional FK to `Organizer` (`organizer_ref`, `on_delete=SET_NULL`).
  Fields: name, unique `slug`, description, `starts_at`/`ends_at`, url, image_url, price,
  category, `organizer` (CharField), `organizer_url` (URLField), `external_id` (indexed).
  Ordered by `starts_at, name`.

- **`Organizer`** — an event organizer scraped from partner directories. Fields: name, unique
  `slug`, **`status`** (`pending` / `confirmed` / `rejected`, default `pending`, indexed),
  contact fields (website, email, phone, address, city, country, facebook_url, instagram_url,
  description), plus provenance fields. Ordered by name. `status` is **never overwritten on
  re-scrape** — admin decisions survive. Unique constraint on `(source, external_id)` where
  `external_id` is non-empty.

- **`ScraperRun`** — a single scraper run job record; the source of truth for both live job
  state and history. Fields:
  - `scraper_key` (CharField, db_index) — the SCRAPERS dict key
  - `status` (`Status` TextChoices: `queued` / `running` / `success` / `failed` / `cancelled`,
    db_index)
  - `started_at` / `finished_at` (DateTimeField, nullable)
  - `created_count` / `updated_count` (IntegerField, default 0)
  - `extra_counts` (JSONField, default dict) — any extra keys from run() result dict beyond
    `source/created/updated` (e.g. `organizers_created`, `organizers_updated`)
  - `error_message` (TextField, blank) — traceback string on failure
  - `pid` (PositiveIntegerField, nullable) — OS PID of the worker subprocess, stored
    immediately after `Popen`; used by `cancel_run` to send `SIGTERM` to the process group
  - `triggered_by` (FK to `auth.User`, nullable) — set if a logged-in user triggered the run;
    null for anonymous / run-all / cron triggers
  - `created_at` (auto_now_add) / `updated_at` (auto_now)
  - Meta: `ordering = ["-created_at"]`; partial unique constraint `unique_active_scraper_run`
    (`scraper_key` unique where `status IN ('queued', 'running')`) prevents duplicate active runs
  - Properties: `duration_seconds` (computed from timestamps), `is_active`

**Dedup invariants:**
- `Event`: `UniqueConstraint(["source", "external_id"])` conditional on `external_id__gt=""`
  (named `unique_source_external_id`). Per-source upsert dedup.
- `Organizer`: same pattern — `UniqueConstraint(["source", "external_id"])` conditional on
  `external_id__gt=""` (named `unique_organizer_source_external_id`).
- **Cross-source fuzzy matching/merge does not exist yet** — do not assume it when reasoning
  about duplicates.

## Scraper Framework

The framework keeps individual scrapers tiny by centralizing persistence:

- A scraper subclasses **`BaseScraper`** (`apps/backend/events/scrapers/base.py`), sets a
  unique `source` key, and implements `fetch()` to yield dataclasses.
- `BaseScraper.run()` collects `fetch()` and calls the appropriate persistence helper.
- Scrapers are registered in **`apps/backend/events/scrapers/__init__.py`** under the `SCRAPERS`
  dict (`key -> class`). The `scrape` command and the run-jobs API resolve scrapers by this key.

**Two scraper patterns exist:**

1. **Event scrapers** — `fetch()` yields `ScrapedEvent` (optionally carrying a `ScrapedVenue`).
   `BaseScraper.run()` calls `save_events(source, events)`, which handles slugging
   (`_unique_slug`), venue upsert (`_upsert_venue`), and event upsert on `(source, external_id)`.
   Examples: `allevents_cdo` (Playwright), `happeningnext_cdo` (Playwright), `myruntime`
   (JSON API — also calls `save_organizers` to persist derived organizers), `ticket2me`
   (requests+BS4), `planout` (requests+BS4), `racemeister_events` (requests+BS4).

2. **Organizer scrapers** — `fetch()` yields `ScrapedOrganizer`. The scraper overrides `run()`
   to call `save_organizers(source, organizers)` directly. `save_organizers` upserts on
   `(source, external_id)` but **never overwrites `status`** — admin decisions survive re-scrapes.
   Example: `racemeister_partners` (requests+BS4, two-phase: list then contact enrichment).

**`ScrapedEvent` fields:** name, description, starts_at, ends_at, url, image_url, price,
category, external_id, source_url, organizer (str), organizer_url, venue (ScrapedVenue|None).

**`ScrapedOrganizer` fields:** name, website, email, phone, address, city, country,
facebook_url, instagram_url, description, external_id, source_url.

**Adding a scraper:** create `apps/backend/events/scrapers/<name>.py` with a `BaseScraper`
subclass, set a unique `source`, implement `fetch()` to yield the right dataclass, and register
it in `SCRAPERS`. Persistence is automatic — do not write to the ORM directly from a scraper.

**Current SCRAPERS registry (10 scrapers):**
```python
{
    "google_places":        GooglePlacesVenueScraper,    # venue-only, Places API
    "allevents_cdo":        AllEventsCDOScraper,          # events, Playwright
    "happeningnext_cdo":    HappeningNextCDOScraper,      # events, Playwright
    "racemeister_partners": RacemeisterPartnersScraper,   # organizers, requests+BS4
    "racemeister_events":   RacemeisterEventsScraper,     # events, requests+BS4
    "myruntime":            MyRuntimeScraper,              # events + organizers, JSON API
    "ticket2me":            Ticket2MeScraper,              # events, requests+BS4
    "planout":              PlanoutScraper,                # events, requests+BS4
    "luma":                 LumaScraper,                   # events + organizers, JSON API
    "eventbrite":           EventbriteScraper,             # events, requests + JSON API
}
```

## Run-Jobs Subsystem

Admins trigger scraper runs from the SvelteKit Scraper Center. The system is subprocess-based —
no Celery or task queues.

**`apps/backend/events/runner.py`** owns all execution logic:
- `trigger_scraper_run(key, triggered_by=None) -> tuple[ScraperRun, bool]` — public function.
  Checks for an active run (concurrency guard; also backed by DB partial unique constraint
  `unique_active_scraper_run`; returns `(None, True)` for 409). Creates a `ScraperRun` row
  (status=queued), spawns `manage.py run_scraper_job --run-id <id>` via `subprocess.Popen`
  with `start_new_session=True` (POSIX `setsid` — gives the child its own process group),
  stores the subprocess `pid` on the row, and returns `(run, False)`.
- `cancel_run(run_id) -> tuple[ScraperRun, str]` — sends `SIGTERM` to the worker's process
  group via `os.killpg(os.getpgid(pid), SIGTERM)`, then marks the row `CANCELLED`. Uses
  `SELECT FOR UPDATE` + `refresh_from_db` to handle the race where the worker writes
  `SUCCESS`/`FAILED` concurrently.

**`apps/backend/events/management/commands/run_scraper_job.py`** — the worker process:
- Fetches the `ScraperRun` row, transitions `QUEUED → RUNNING` via a conditional
  `filter(status=QUEUED).update(...)` (exits cleanly if already cancelled), calls
  `SCRAPERS[key]().run()`, writes `success`/`failed` + counts/traceback back to the row.

**`run()` return dict → count mapping:**
- Event scrapers return `{source, created, updated}` → `created_count`, `updated_count`, `extra_counts={}`
- MyRuntime returns `{source, created, updated, organizers_created, organizers_updated}` →
  `extra_counts={"organizers_created": N, "organizers_updated": N}`

## API Surface

All JSON endpoints are registered in `apps/backend/events/urls.py` under the `events` namespace
and included at the root in `config/urls.py`.

### Auth posture

| Endpoint | Auth |
|---|---|
| All `GET /api/*` JSON endpoints | Public — no auth, no CSRF |
| `POST /api/scrapers/<key>/run/` | Public, `@csrf_exempt` |
| `POST /api/scrapers/run-all/` | Public, `@csrf_exempt` |
| `/review/*` HTMX staff UI | `@staff_member_required` (Django session + CSRF) |
| `/admin/*` | Django admin auth |

**Why the trigger endpoints are public:** The SvelteKit frontend has no auth bridge to Django
(no login flow, no session). Django session/CSRF cannot be satisfied from the SvelteKit client.
Mutation protection is deferred — this is a **known security debt** until a real auth bridge
is implemented. See Gotchas section.

### Scraper / Run-Jobs endpoints

| Method | URL | Description |
|---|---|---|
| GET | `/api/scrapers/` | List all scrapers with metadata and last-run info |
| POST | `/api/scrapers/<key>/run/` | Trigger a run for one scraper (public, csrf_exempt); returns `{id, status}` or 404/409 |
| POST | `/api/scrapers/run-all/` | Trigger all scrapers; skips already-active keys; returns `{created: [...], skipped: [...]}` |
| GET | `/api/scrapers/runs/` | Recent run history (default limit 50) |
| GET | `/api/scrapers/runs/active/` | Active (queued/running) runs only — used for polling |
| GET | `/api/scrapers/runs/<id>/` | Single run detail |
| POST | `/api/scrapers/runs/<id>/cancel/` | Cancel a queued/running run (`cancel_run`); public, csrf_exempt |

### Other endpoints

| Method | URL | Description |
|---|---|---|
| GET | `/api/stats/` | Dashboard stats |
| GET | `/api/events/` | Paginated events list |
| GET | `/api/events/by-source/` | Events grouped by source key |
| GET | `/api/events/by-category/` | Events grouped by **normalized** category — calls `normalize_category` from `events/categories.py`; returns Top-N buckets + "Other" |
| GET | `/api/organizers/` | Organizers list |
| GET | `/api/organizers/<slug>/` | Organizer detail |
| GET | `/api/venues/` | Venues list |

## Admin

Raw-data console (`apps/backend/events/admin.py`) for all four models. `VenueAdmin` has bulk **Mark verified / rejected** actions; `/review/` is the primary verification surface. `OrganizerAdmin` has bulk **Mark Confirmed / Rejected**. `ScraperRunAdmin` is fully readonly (`has_add_permission` and `has_delete_permission` return False).

## Backend API

Function-based `JsonResponse` views in `views.py`; all registered in `urls.py` under the `events` namespace. Full endpoint list is in **API Surface** above.

**Category normalization seam:** `events/categories.py` exports `normalize_category(raw: str) -> str`. Maps raw `Event.category` values (e.g. `"10K, 5K, 3K"` from `myruntime`/`ticket2me`) to display buckets (e.g. `"Fun Run / Road Race"`) at query time — no stored field mutated. Storing canonical values is a roadmap item.

**Frontend API client (`apps/frontend/src/lib/api.ts`):** typed `api` object covering every endpoint; `post<T>()` helper reads `csrftoken` cookie and sends it as `X-CSRFToken`.

## Web UI (Legacy Django Templates)

Secondary surface. Public views: `event_list`, `event_detail`, `venue_list`, `venue_detail`. Staff-gated `/review/` (venue verification): dashboard + `review_venue_detail` + `review_set_status`. All `/review/*` views are `@staff_member_required`; status changes are HTMX-driven, swapping the `_status_control.html` partial in place. Templates in `apps/backend/templates/`.

## Frontend (SvelteKit Admin Dashboard)

CSR-only SvelteKit 2 + Svelte 5 dashboard. Dev server proxies `/api/*` → Django at `:8000` (`vite.config.ts`). Routes and components are listed in the **Repository Structure** tree above.

**Key conventions:** `ssr = false` enforced; Svelte 5 runes only (`$state`/`$props`/`$derived`/`$effect`); Tailwind v4 design tokens in `src/app.css @theme {}`; all API calls via `src/lib/api.ts` (never ad-hoc `fetch`).

## Key Patterns and Conventions

**Backend:**
- **Monorepo layout:** backend in `apps/backend/`, frontend in `apps/frontend/`. Root-level
  `events/` and `config/` are dead shells — do not reference them.
- **Standard Django layout:** project package `config/`, single app `events/`. Function-based
  views, `app_name` URL namespacing, `get_absolute_url` via `reverse`.
- **Scrapers yield dataclasses, never touch the ORM directly.** All persistence/dedup is
  centralized in `save_events` (events) or `save_organizers` (organizers). Keep this boundary.
- **Provenance on every row:** always set `source` / `source_url` / `scraped_at` (the
  framework does this for you). `external_id` drives dedup — set it whenever the source has a
  stable id.
- **Slugs are auto-generated and uniqued** by `_unique_slug`; do not hand-set slugs in scrapers.
- **Timezone-aware datetimes** (`USE_TZ=True`); use `django.utils.timezone.now()`, not naive
  `datetime`.
- **Resilient batch scraping:** the `scrape` command catches per-scraper exceptions so one
  failing scraper does not kill the rest.
- **Django JSON views are function-based.** No DRF. `JsonResponse` for all `/api/*` endpoints.
- **Category normalization at the API layer only.** `normalize_category` in `events/categories.py`
  is a pure function — it does not write to the DB. The stored `Event.category` field always
  holds the raw scraper value. This is intentional; Option B (storing canonical values) is a
  roadmap item.

**Frontend:**
- **CSR-only.** `export const ssr = false` in `apps/frontend/src/routes/+layout.ts`. All data
  fetching happens in the browser via `load()` functions or inline `fetch` calls.
- **Svelte 5 runes are enforced project-wide** (`runes: true` in `vite.config.ts`, for all
  non-`node_modules` files). Use `$state`, `$props`, `$derived`, `$effect` — not legacy `$:`,
  stores, or the Options API.
- **Tailwind v4 `@theme {}`.** Design tokens (colors, spacing, fonts) live in `src/app.css`
  inside the `@theme {}` block. Do not use `tailwind.config.js`-style configuration.
- **Typed API layer.** All backend calls go through `src/lib/api.ts`. Add new endpoints there,
  not as ad-hoc `fetch()` calls in route files.

## Environment and Configuration

- **Config file:** `apps/backend/config/settings.py`.
- **`.env` file:** `apps/backend/.env` (git-ignored). Contains `DATABASE_URL` (Neon Postgres
  connection string), `SECRET_KEY`, and any scraper API keys.
- **`.gitignore`** excludes `.env` / `.env.*`, `db.sqlite3`, `/media/`, `/staticfiles/`, `venv/`.
- **Database:** Neon PostgreSQL. Set via the `DATABASE_URL` env var; `dj_database_url.config()`
  in `settings.py` parses it. **Never configure SQLite for any real environment.**
- **Key env vars** (names only, never commit values):
  - `DATABASE_URL` — Neon Postgres connection string
  - `SECRET_KEY` — Django secret key
  - `DEBUG` — set False in production
  - `ALLOWED_HOSTS` — comma-separated allowed hosts
  - Scraper-specific API keys as needed (e.g. `GOOGLE_PLACES_API_KEY`)
- **Frontend:** no `.env` needed for dev; Vite proxy config in `apps/frontend/vite.config.ts`
  proxies `/api/*` to Django at `http://localhost:8000` during `pnpm dev` (no CORS config needed).

## Commands

| Purpose | Command |
|---|---|
| Start full monorepo dev (frontend + backend) | `pnpm dev` (from repo root) |
| Backend only | `cd apps/backend && ./venv/bin/python manage.py runserver` |
| Frontend only | `pnpm --filter frontend dev` |
| Run backend tests | `cd apps/backend && ./venv/bin/python manage.py test events` |
| Run one test class | `cd apps/backend && ./venv/bin/python manage.py test events.tests.MyTest` |
| Frontend type-check | `pnpm --filter frontend check` |
| Frontend build | `pnpm --filter frontend build` |
| Apply migrations | `cd apps/backend && ./venv/bin/python manage.py migrate` |
| Check migrations | `cd apps/backend && ./venv/bin/python manage.py makemigrations --check --dry-run` |
| List scrapers | `cd apps/backend && ./venv/bin/python manage.py scrape --list` |
| Run one scraper | `cd apps/backend && ./venv/bin/python manage.py scrape <key>` |

## Gotchas / Watch-outs

- **Root-level dead shells:** `events/` and `config/` at the repo root are vestigial from
  before the monorepo conversion. They are not active code. Always use `apps/backend/events/`
  and `apps/backend/config/`.
- **Database is Neon PostgreSQL** in every environment; SQLite is no longer used. `db.sqlite3`
  may linger in the working tree but is git-ignored and is **not** a source of truth.
- **Test database is Neon PostgreSQL.** Tests run against the real Neon DB (not a local
  Neon PostgreSQL DB. Runner tests use `TransactionTestCase` (not `TestCase`) because the worker
  runs as a separate subprocess that opens its own DB connection and cannot see an open
  transaction. Runner tests mock `SCRAPERS[key]().run()` to avoid real network calls.
- **Category data gotcha:** `myruntime` and `ticket2me` populate `Event.category` with
  comma-joined race distances or ticket-tier names (e.g. `"10K, 5K, 3K"`,
  `"SUB1 Elite, SUB1 Competitor, Open Wave"`). Raw values are not human-readable category
  labels. Always use `normalize_category` (from `events/categories.py`) when displaying
  category data — the `/api/events/by-category/` endpoint does this automatically.
- **Auth/security debt:** The SvelteKit frontend has no login flow. All JSON endpoints
  (including the POST trigger/run-all/cancel) are public and `@csrf_exempt`. This is intentional
  for now but is a **known follow-up item** — re-gate when a real Django-SvelteKit auth
  bridge is added.
- **Django `@staff_member_required` on JSON endpoints returns 302 → HTML.** A `fetch()` call
  that assumes `res.ok === 200 → JSON` will throw on a 302 redirect to the login page.
  Use `@csrf_exempt` for JSON mutations from session-less clients; keep `@staff_member_required`
  only for browser-navigated HTML views.
- **Playwright scrapers** (allevents_cdo, happeningnext_cdo) may take minutes. The run-jobs
  polling model (polling until the DB row is terminal) is designed to tolerate this.
- **Frontend has no tests yet.** `pnpm --filter frontend check` (svelte-check + tsc) and
  `pnpm --filter frontend build` are the only automated frontend verification steps.
- **No CI** is configured yet. Setting up CI to run `manage.py test` + migration check +
  `pnpm check` on push is a planned but unscheduled item.
- Production hardening (real `SECRET_KEY`, `DEBUG=False`, env config) is unaddressed by design
  at this stage.
- **97 tests currently passing** as of 2026-06-17 (`apps/backend/events/tests.py`).
  Run with: `cd apps/backend && ./venv/bin/python manage.py test events`.

## Scan Metadata

Rev 3 (2026-06-17) — 10 scrapers, migrations 0001–0011, 97 backend tests passing, 0 frontend tests.
