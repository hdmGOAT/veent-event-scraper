# Veent Event Scraper - All Context

Last updated: 2026-07-17 (rev 5 — per-user Django session auth + django-axes + SvelteKit fail-closed gate + 197 tests + CI)

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
is the SvelteKit frontend (now SSR-capable via `adapter-node`) with five routes (`/`, `/events`,
`/organizers`, `/venues`, `/scrapers`) — a Scraper Center with Run / Run All / run-history,
charts, sortable tables, and a shared component library, backed by the JSON endpoints. In
production the dashboard and all `/api/*` calls are protected by a per-user Django session
auth gate in `hooks.server.ts` (validates against `GET /api/auth/me/`; fail-closed on backend
outage; no-op in dev). Django settings are fully
env-driven (`SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`). CI is configured (`.github/workflows/ci.yml`).
The larger product vision (fuzzy cross-source dedup/merge, CSV + JSON/REST export) is **not
yet built** — it is the roadmap this codebase grows into.

**Audience / interface decisions:**

- Primary admin interface: **SvelteKit frontend** (Scraper Center, monitoring, managing scrapers).
- Secondary admin interface: **Django's built-in admin** (raw-data console for all models).
- Scraper triggering: **UI-triggered** via Scraper Center (POST to `/api/scrapers/<key>/run/`
  or `/api/scrapers/run-all/`); also triggerable via `manage.py scrape`.
- Scraper scheduling: **manual / OS cron** (no Celery/queue).
- Team project; tests run on Neon PostgreSQL; 197 tests currently passing.
- CI: `.github/workflows/ci.yml` runs backend tests (requires `DEBUG=true`), migration check,
  and `pnpm --filter frontend check` on push/PR.

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
        models.py                     -- Venue, Event, Organizer, ScraperRun models
        views.py                      -- function-based views: public list/detail + staff /review/ + JSON API
        urls.py                       -- app URLConf (namespace "events") — all routes
        admin.py                      -- VenueAdmin, EventAdmin, OrganizerAdmin, ScraperRunAdmin
        runner.py                     -- subprocess-based scraper runner (trigger_scraper_run, cancel_run)
        categories.py                 -- normalize_category(): display-layer category normalization
        tests.py                      -- Django TestCase suite (97 tests as of 2026-06-17)
        migrations/                   -- 0001_initial … 0012_scraperrun_unique_active_constraint (applied)
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
    frontend/                         -- SvelteKit 2 + Svelte 5 (primary admin UI, SSR via adapter-node)
      vite.config.ts                  -- Tailwind v4 plugin + runes enforced; proxy /api → :8000; adapter-node wired here
      src/
        app.css                       -- @theme {} design tokens
        hooks.server.ts               -- SSR handle: production auth gate (per-user Django session) + /api/* proxy to Django
        routes/
          +layout.ts                  -- (ssr kept server-side; no longer export const ssr = false globally)
          /                           -- dashboard
          /events / /organizers / /organizers/[slug] / /venues / /scrapers
          login/                      -- /login page + server action (+page.svelte, +page.server.ts)
          logout/                     -- /logout server handler (+server.ts)
        lib/
          (session.ts removed — shared-password gate replaced by Django session auth)
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
- **Auth:** Django's built-in `django.contrib.auth` for per-user session auth, Django admin,
  and the `/review/` staff UI. All `/api/*` JSON endpoints are guarded by `@api_login_required`
  (returns JSON 401 for anonymous requests); `@csrf_exempt` was removed from all SPA-mutating
  endpoints. Only webhook endpoints (`/webhooks/scrape/`, `/webhooks/ingest-events/`) retain
  `@csrf_exempt` (they authenticate via `X-Scraper-Key` instead). Django exposes four auth
  endpoints: `GET /api/auth/csrf/`, `POST /api/auth/login/`, `POST /api/auth/logout/`,
  `GET /api/auth/me/` (all trailing-slash). **Brute-force lockout** via `django-axes`
  (`AXES_FAILURE_LIMIT=5`, `AXES_COOLOFF_HOURS=1`, locks by username+IP,
  `django-axes[ipware]` for `X-Forwarded-For` header support). User accounts managed via
  Django `/admin/`. See Auth posture in the API Surface section for the full table.

**Frontend (`apps/frontend/`):**
- **Framework:** SvelteKit 2
- **Language:** TypeScript + Svelte 5 (runes mode forced via `vite.config.ts` `compilerOptions.runes`)
- **Rendering:** SSR-capable via `adapter-node` (produces `apps/frontend/build/index.js`; node server on port 3000).
  Active SSR hooks in `hooks.server.ts` handle the production auth gate and the `/api/*` proxy to Django.
  Note: adapter is wired in `vite.config.ts` (inline `sveltekit()` options), NOT in `svelte.config.js`
  — when options are passed inline, SvelteKit ignores `svelte.config.js` entirely.
- **Auth gate:** `hooks.server.ts` validates each request against `GET /api/auth/me/` (forwarding
  the `Cookie` header) in production (`ENVIRONMENT=production`). A 200 response means the user
  is authenticated; any other status redirects to `/login`. The gate **fails closed** — a backend
  outage or timeout returns HTTP 503 rather than letting requests through. Public paths reachable
  pre-login: `/login`, `/logout`, `/api/auth/csrf`, `/api/auth/login` (all exact prefix matches
  without trailing slash). Dev mode (`ENVIRONMENT` absent or not `'production'`) bypasses the
  gate entirely. Session cookies are Django's `sessionid` + `csrftoken` (HttpOnly, Secure in
  production, SameSite=Lax).
- **Styling:** Tailwind CSS v4 via `@tailwindcss/vite` plugin; design tokens in `src/app.css` `@theme {}`
- **Charts:** Chart.js (wrapped in `BarChart.svelte` and `DonutChart.svelte`)
- **Icons:** lucide-svelte
- **Build:** Vite + adapter-node; dev proxy routes `/api` → Django at `:8000`
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
  category, `agent_categories` (JSONField — AI-assigned canonical categories, empty list = not yet classified),
  `organizer` (CharField), `organizer_url` (URLField), `external_id` (indexed).
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
| All `GET /api/*` and `POST /api/*` JSON endpoints | `@api_login_required` Django-side (JSON 401 for anonymous); also gated at SvelteKit proxy layer |
| `/api/auth/csrf/`, `/api/auth/login/`, `/api/auth/logout/`, `/api/auth/me/` | Django session auth endpoints — no `@api_login_required` (reachable pre-login) |
| `/webhooks/scrape/`, `/webhooks/ingest-events/` | `@csrf_exempt` + `X-Scraper-Key` header auth |
| `/review/*` HTMX staff UI | `@staff_member_required` (Django session + CSRF) |
| `/admin/*` | Django admin auth |

**Auth architecture:** All `/api/*` JSON endpoints are directly protected by Django-side
`@api_login_required` (returns JSON `{"error": "Authentication required"}` with HTTP 401 for
anonymous requests). `@csrf_exempt` was removed from SPA-facing endpoints; Django's CSRF
protection is active for all non-exempt endpoints. The SvelteKit `hooks.server.ts` gate adds a
second layer by validating the session against `GET /api/auth/me/` before proxying any request.
This layered approach means the API is protected even if nginx routes `/api/` directly to
Django:8000, though routing through the SvelteKit node server (port 3000) is still recommended
for consistent session validation and fail-closed behavior. See the nginx /api/ routing note below.

### Auth endpoints

| Method | URL | Description |
|---|---|---|
| GET | `/api/auth/csrf/` | Return a fresh CSRF token (sets `csrftoken` cookie) |
| POST | `/api/auth/login/` | Authenticate with username+password; starts a Django session; CSRF-protected |
| POST | `/api/auth/logout/` | Flush the session; CSRF-protected; safe to call when anonymous |
| GET | `/api/auth/me/` | Return current user info (JSON 200) or 401 if anonymous; used by the SvelteKit gate |

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

**Key conventions:** SSR-capable (adapter-node); production auth gate in `hooks.server.ts`; Svelte 5
runes only (`$state`/`$props`/`$derived`/`$effect`); Tailwind v4 design tokens in `src/app.css @theme {}`;
all API calls via `src/lib/api.ts` (never ad-hoc `fetch`). Session cookies are Django's `sessionid`
(HttpOnly, Secure in production, SameSite=Lax) and `csrftoken` (readable by JS for `X-CSRFToken`
header). The old HMAC `sess` cookie and `session.ts` signing helpers were removed.

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
- **SSR-capable (adapter-node).** The production build runs as a Node.js server (`build/index.js`,
  port 3000). `hooks.server.ts` owns the auth gate and `/api/*` SSR proxy. Route-level `load()`
  functions run server-side in production.
- **Production auth gate in `hooks.server.ts`.** Validates each request against `GET /api/auth/me/`
  by forwarding the `Cookie` header. 200 = authenticated (request continues); any other status =
  redirect to `/login`. Gate **fails closed** on backend outage (returns 503). Public paths
  reachable pre-login: `/login`, `/logout`, `/api/auth/csrf`, `/api/auth/login`. Dev mode
  (no `ENVIRONMENT=production`) bypasses the gate entirely. Do not add other `/api/` paths to
  the public bypass list — the Django layer protects them independently.
- **Adapter wired in `vite.config.ts`, not `svelte.config.js`.** This project passes SvelteKit
  options inline via `sveltekit({ ... })` in `vite.config.ts`; `svelte.config.js` is ignored
  when options are passed inline. Always edit `vite.config.ts` for adapter/compiler changes.
- **Svelte 5 runes are enforced project-wide** (`runes: true` in `vite.config.ts`, for all
  non-`node_modules` files). Use `$state`, `$props`, `$derived`, `$effect` — not legacy `$:`,
  stores, or the Options API.
- **Tailwind v4 `@theme {}`.** Design tokens (colors, spacing, fonts) live in `src/app.css`
  inside the `@theme {}` block. Do not use `tailwind.config.js`-style configuration.
- **Typed API layer.** All backend calls go through `src/lib/api.ts`. Add new endpoints there,
  not as ad-hoc `fetch()` calls in route files.

## Environment and Configuration

- **Config file:** `apps/backend/config/settings.py`.
- **`.env` files:** `apps/backend/.env` (git-ignored) and `apps/frontend/.env` (git-ignored).
  Backend `.env` contains `DATABASE_URL`, `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `PROD_ORIGIN`,
  and any scraper API keys. Frontend `.env` contains only `DJANGO_API_URL`, `NODE_API_URL`,
  and `ENVIRONMENT` — `DASHBOARD_PASSWORD` and `SESSION_SECRET` were removed when the
  shared-password gate was replaced by Django session auth.
- **`.gitignore`** excludes `.env` / `.env.*`, `db.sqlite3`, `/media/`, `/staticfiles/`, `venv/`.
- **Database:** Neon PostgreSQL. Set via the `DATABASE_URL` env var; `dj_database_url.config()`
  in `settings.py` parses it. **Never configure SQLite for any real environment.**
- **Backend env vars** (names only, never commit values):
  - `DATABASE_URL` — Neon Postgres connection string
  - `SECRET_KEY` — Django secret key (fully env-driven; no hardcoded fallback; the key previously
    committed to git is burned — generate a fresh one for any production deploy)
  - `DEBUG` — parsed as `os.environ.get('DEBUG', 'False').lower() not in ('false', '0', 'no')`;
    defaults to `False` when absent (production-safe). **Backend tests require `DEBUG=true`** —
    with `DEBUG=False` the `SECURE_SSL_REDIRECT=True` block issues 301 redirects that break ~48
    view/API tests. CI sets `DEBUG: "true"` in the backend job env.
  - `ALLOWED_HOSTS` — comma-separated; defaults to `['localhost', '127.0.0.1', 'testserver']`
    when absent (dev convenience only)
  - `PROD_ORIGIN` — production origin (e.g. `https://your-domain.com`); added to `CSRF_TRUSTED_ORIGINS`
  - `AXES_FAILURE_LIMIT` — number of failed login attempts before lockout (default `5`)
  - `AXES_COOLOFF_HOURS` — lockout cooloff window in hours (default `1`); lockout is per username+IP
  - `SESSION_COOKIE_AGE_SECONDS` — Django session lifetime in seconds (default `28800` = 8 hours)
  - Scraper-specific API keys as needed (e.g. `GOOGLE_PLACES_API_KEY`)
- **Frontend env vars** (read at node process start via `$env/dynamic/private`, not build time):
  - `DJANGO_API_URL` — Django backend URL for the SSR proxy (default `http://localhost:8000`)
  - `NODE_API_URL` — node API URL for `/node-api/*` proxy (default `http://localhost:8001`)
  - `ENVIRONMENT` — set to `production` to enable the per-user auth gate; any other value (or
    absent) disables the gate (dev-safe default)
  - `DASHBOARD_PASSWORD` and `SESSION_SECRET` — **removed**; the shared-password gate and HMAC
    `sess` cookie are gone. Authentication now relies entirely on Django `sessionid` + `csrftoken`.
- **Frontend dev:** `pnpm dev` uses Vite's dev proxy (`/api/*` → Django at `http://localhost:8000`);
  no `.env` is needed for dev (auth gate is disabled when `ENVIRONMENT` is not `production`).

## Commands

| Purpose | Command |
|---|---|
| Start full monorepo dev (frontend + backend) | `pnpm dev` (from repo root) |
| Backend only | `cd apps/backend && ./venv/bin/python manage.py runserver` |
| Frontend only | `pnpm --filter frontend dev` |
| Run backend tests | `cd apps/backend && ./venv/bin/python manage.py test events` | requires `DEBUG=true` — see Environment section |
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
- **Auth posture:** Django JSON endpoints are now directly protected by `@api_login_required`
  (returns JSON 401 for anonymous requests). `@csrf_exempt` was removed from all SPA-facing
  endpoints — Django's CSRF protection is active for them. The SvelteKit gate in
  `hooks.server.ts` adds a second validation layer (checks `GET /api/auth/me/` before proxying).
  The two layers are independent: even a direct nginx → Django:8000 route is now protected at
  the Django layer, removing the previous single-gate bypass risk.
- **Django `@staff_member_required` on JSON endpoints returns 302 → HTML.** A `fetch()` call
  that assumes `res.ok === 200 → JSON` will throw on a 302 redirect to the login page.
  Use `@api_login_required` for JSON endpoints (returns JSON 401); keep `@staff_member_required`
  only for browser-navigated HTML views. Do not use `@csrf_exempt` on SPA-facing endpoints —
  CSRF protection is now active on all `/api/*` endpoints (the SvelteKit client sends
  `X-CSRFToken` from the `csrftoken` cookie via `src/lib/api.ts`).
- **Playwright scrapers** (allevents_cdo, happeningnext_cdo) may take minutes. The run-jobs
  polling model (polling until the DB row is terminal) is designed to tolerate this.
- **Frontend has no tests yet.** `pnpm --filter frontend check` (svelte-check + tsc) and
  `pnpm --filter frontend build` are the only automated frontend verification steps.
- **CI is configured** (`.github/workflows/ci.yml`). Backend job sets `DEBUG: "true"` in env —
  required because `DEBUG=False` activates `SECURE_SSL_REDIRECT=True` which issues 301 redirects
  breaking ~48 view/API tests. CI also runs a migration check and `pnpm --filter frontend check`.
- **197 tests currently passing** as of 2026-07-16 (`apps/backend/events/tests.py`).
  Run with: `cd apps/backend && DEBUG=true ./venv/bin/python manage.py test events`.
- **SvelteKit inline-Vite-config gotcha:** when `sveltekit()` options are passed inline in
  `vite.config.ts`, SvelteKit **ignores `svelte.config.js` entirely**. The adapter must be set
  in `vite.config.ts`. Editing only `svelte.config.js` produces "No adapter specified" and no
  `build/index.js`. This project wires `adapter-node` in `vite.config.ts`; `svelte.config.js`
  is kept in sync for consistency but is not the authoritative adapter source.
- **Layered auth and the nginx /api/ routing note:** `hooks.server.ts` gates the dashboard AND
  all `/api/*` proxy calls. Unlike the previous shared-password design, Django now also enforces
  `@api_login_required` on every `/api/*` endpoint — so a direct nginx → Django:8000 route no
  longer bypasses all auth. The recommended nginx config still routes all traffic through port
  3000 (SvelteKit upstream) and binds Django's gunicorn to `127.0.0.1:8000` (localhost-only);
  this ensures the SvelteKit gate's fail-closed behavior and session validation fire consistently.
  But the previous "bypass entirely" risk is mitigated because the Django layer is now an
  independent authentication check.
- **Backend tests require `DEBUG=true`:** the `if not DEBUG:` block in `settings.py` enables
  `SECURE_SSL_REDIRECT=True`, which causes Django's test client to receive 301 redirects instead
  of 200/302 responses for ~48 view and API tests. Always run backend tests with `DEBUG=true`
  (or `DEBUG=true` in `apps/backend/.env`). CI enforces this via the backend job env.

## Scan Metadata

- Generated: 2026-06-16 (rev 2); revised 2026-06-17 (rev 3); revised 2026-07-16 (rev 4); revised 2026-07-17 (rev 5)
- Package managers: pnpm (monorepo root + frontend), pip/venv (backend)
- Active scrapers: 10 (google_places, allevents_cdo, happeningnext_cdo, racemeister_partners, racemeister_events, myruntime, ticket2me, planout, luma, eventbrite)
- Migrations: 0001–0012 applied
- Backend tests: 197 (all passing with DEBUG=true, Neon Postgres)
- Frontend tests: 0 (svelte-check + build are the only automated verification)
- CI: configured (.github/workflows/ci.yml)
