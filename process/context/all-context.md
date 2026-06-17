# Veent Event Scraper - All Context

Last updated: 2026-06-17 (rev 3 — monorepo, SvelteKit frontend, 3 new scrapers, 49 tests)

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

**Current state vs. target:** The repo is a **pnpm/Turborepo monorepo** with two apps:
`apps/backend/` (Django 6) and `apps/frontend/` (SvelteKit 2). The Django backend has
`Venue`, `Event`, and `Organizer` models with scraping-provenance fields, a pluggable scraper
framework with 8 registered scrapers, a `manage.py scrape` command, Django admin
registrations, a staff `/review/` UI, and a set of JSON API endpoints consumed by the
frontend. The SvelteKit frontend is a CSR-only admin dashboard with five routes (`/`,
`/events`, `/organizers`, `/venues`, `/scrapers`), charts, sortable tables, and shared
component library. The larger product vision (fuzzy cross-source dedup/merge, CSV + JSON/REST
export, CI, production hardening) is **not yet built** — it is the roadmap this codebase
grows into.

**Audience / interface decisions (from setup conversation):**

- Primary admin interface: **Django's built-in admin** (monitor, review, manage records).
- Scraper scheduling: **manual / OS cron** via the `manage.py scrape` command (no Celery/queue yet).
- Team project; **CI is to be set up**; tests use Django's built-in test runner for now.

---

## How This File Works (the `all-*.md` Convention)

Every `process/context/` directory has one `all-*.md` entrypoint that acts as an attachable
quick router for that domain. This root file (`all-context.md`) is the top-level router.
Context groups each have their own `all-{group}.md` entrypoint.

**How agents use it:**

1. Agent reads `all-context.md` first (this file)
2. Finds the relevant context group from the routing tables below
3. Reads that group's `all-{group}.md` entrypoint
4. Only then loads the specific deep doc needed

This layered routing keeps context windows small. Never load the whole `process/context/` tree.

---

## Quick Start

For most substantial tasks:

1. read this file first
2. choose the smallest relevant root file or context group from the tables below
3. only then load deeper files

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
inline below (three models, several migrations). A `scrapers/` context group is a strong
candidate — the project has 8 real scrapers with two distinct patterns. Create it when
scraper-specific docs exceed one screen of inline prose. A `frontend/` context group may
also be warranted as the SvelteKit app grows.

## Task Routing Table

| If the task involves... | Start with | Then load |
|---|---|---|
| architecture or stack questions | this file | — |
| adding or changing a scraper | this file (Scraper Framework section) | `apps/backend/events/scrapers/base.py`, `apps/backend/events/scrapers/__init__.py`, existing scraper for pattern |
| models / schema / migrations | this file (Data Model section) | `apps/backend/events/models.py`, `apps/backend/events/migrations/` |
| admin behavior | this file (Admin section) | `apps/backend/events/admin.py` |
| backend views / API | this file (Backend API section) | `apps/backend/events/views.py`, `apps/backend/events/urls.py` |
| frontend routes / components | this file (Frontend section) | `apps/frontend/src/routes/`, `apps/frontend/src/lib/` |
| testing or verification | `process/context/tests/all-tests.md` | the specific test file |
| creating a new plan | `process/context/planning/all-planning.md` | the relevant example PRD |
| context maintenance | this file | run `audit-context` after edits |

## Context Group Lifecycle

Context groups are durable knowledge domains, not feature folders.

Create a group when:

- a topic has 3+ durable docs
- a single doc exceeds roughly 800 lines with separable subtopics
- multiple agents repeatedly need only one slice of a large context file
- the topic maps to a stable operational domain (tests, infra, database, auth, scrapers, etc.)

Move or split one group at a time. Use `all-{group}.md` entrypoints. Run the `audit-context`
skill after every context organization change.

## Context Update Protocol

When durable project knowledge changes:

1. update the smallest relevant context file
2. update this file if routing, ownership, naming, or groups changed
3. update the owning `all-{group}.md` entrypoint when a group exists
4. run `audit-context`

---

## Repository Structure

Monorepo managed with **pnpm workspaces + Turborepo**.

```
veent-event-scraper/            -- monorepo root
  package.json                  -- root workspace config (dev scripts: pnpm dev / build / check)
  pnpm-workspace.yaml           -- workspace glob: apps/*
  turbo.json                    -- Turborepo pipeline
  pnpm-lock.yaml
  apps/
    backend/                    -- Django 6 application
      manage.py                 -- Django entrypoint
      requirements.txt          -- pip dependencies (Django 6, requests, bs4, lxml)
      db.sqlite3                -- dev database (git-ignored)
      venv/                     -- Python virtualenv (not committed)
      config/                   -- Django project package
        settings.py             -- settings (SQLite, INSTALLED_APPS, etc.)
        urls.py                 -- root URLConf (admin/ + events app)
        wsgi.py / asgi.py       -- server entrypoints
      events/                   -- the single Django application
        models.py               -- Venue, Event, Organizer models (scraping provenance fields)
        views.py                -- API views + staff /review/ UI (function-based)
        urls.py                 -- app URLConf (namespace "events")
        admin.py                -- VenueAdmin, EventAdmin, OrganizerAdmin
        categories.py           -- normalize_category(): display-layer category normalization
        tests.py                -- Django TestCase suite (49 tests as of 2026-06-17)
        migrations/             -- 0001_initial … 0007_organizer
        scrapers/               -- scraper framework
          base.py               -- BaseScraper + ScrapedEvent/ScrapedVenue/ScrapedOrganizer + save_events/save_organizers
          allevents.py          -- AllEventsCDOScraper (key: allevents_cdo, Playwright)
          happeningnext.py      -- HappeningNextCDOScraper (key: happeningnext_cdo, Playwright)
          myruntime.py          -- MyRuntimeScraper (key: myruntime, JSON API + organizers)
          places.py             -- GooglePlacesVenueScraper (key: google_places, Places API)
          racemeister.py        -- RacemeisterPartnersScraper (key: racemeister_partners, requests+BS4)
          racemeister_events.py -- RacemeisterEventsScraper (key: racemeister_events)
          ticket2me.py          -- Ticket2MeScraper (key: ticket2me)
          planout.py            -- PlanoutScraper (key: planout)
          __init__.py           -- SCRAPERS registry {key -> class}
        management/commands/
          scrape.py             -- `manage.py scrape [source] [--list]`
      templates/                -- legacy server-rendered UI (still functional)
        base.html
        events/                 -- event_list, event_detail, venue_list, venue_detail
          review/               -- staff /review/ UI: dashboard, venue_detail, _status_control
    frontend/                   -- SvelteKit 2 admin dashboard (CSR-only)
      package.json
      vite.config.ts            -- tailwindcss plugin + sveltekit plugin (runes forced)
      svelte.config.js
      src/
        app.css                 -- Tailwind v4 @theme {} design tokens + global styles
        routes/
          +layout.svelte        -- root layout with Sidebar
          +layout.ts            -- export const ssr = false (CSR-only)
          +page.svelte          -- / — dashboard (StatCards, BarChart, DonutChart)
          +page.ts              -- load() fetches /api/stats/, /api/events/by-source/, /api/events/by-category/
          +error.svelte         -- global error boundary
          events/
            +page.svelte        -- /events — event list table
          organizers/
            +page.svelte        -- /organizers — sortable organizer table
            [slug]/
              +page.svelte      -- /organizers/[slug] — organizer detail
          venues/
            +page.svelte        -- /venues — venue list
          scrapers/
            +page.svelte        -- /scrapers — scraper registry list
            +page.ts            -- load() fetches /api/scrapers/
        lib/
          components/
            Sidebar.svelte      -- collapsible navigation sidebar
            PageHeader.svelte   -- page title + breadcrumb
            Badge.svelte        -- status badge (color-coded)
            StatCard.svelte     -- KPI card with icon + value
            BarChart.svelte     -- Chart.js bar chart wrapper
            DonutChart.svelte   -- Chart.js donut chart wrapper
            TableSkeleton.svelte -- loading skeleton for tables
            SortHeader.svelte   -- sortable column header (uses sort.ts)
          utils/
            sort.ts             -- generic client-side column sort helpers
          api.ts                -- typed fetch wrappers for all /api/* endpoints
          types.ts              -- shared TypeScript type definitions
          format.ts             -- display formatting utilities
          index.ts              -- barrel re-exports
  process/                      -- agent harness workspace (context, plans, protocols)
```

## Technology Stack

**Monorepo tooling:**
- **Workspace manager:** pnpm workspaces + Turborepo (`turbo.json`)

**Backend (`apps/backend/`):**
- **Framework:** Django 6.0.6
- **Language / runtime:** Python 3.14 (venv at `apps/backend/venv/`)
- **Database:** SQLite (`db.sqlite3`) via the Django ORM (dev only; production DB undecided)
- **Scraping:** `requests` 2.34 for HTTP, `beautifulsoup4` 4.15 + `lxml` 6.1 for HTML parsing
- **Admin:** Django's built-in admin (`django.contrib.admin`) is the primary operator surface for raw data
- **Backend templates:** server-rendered Django templates still exist (legacy list/detail views + `/review/` UI); no JS framework on that surface
- **API:** plain Django `JsonResponse` views (no DRF), GET-only — consumed by the SvelteKit frontend
- **Package manager (Python):** pip + `requirements.txt`, virtualenv (`venv/`)
- **Auth:** Django's built-in `django.contrib.auth` (admin login + `@staff_member_required` for `/review/`)

**Frontend (`apps/frontend/`):**
- **Framework:** SvelteKit 2
- **Language:** TypeScript + Svelte 5 (runes mode forced via `vite.config.ts` `compilerOptions.runes`)
- **Rendering:** CSR-only (`export const ssr = false` in `+layout.ts`); no SSR, no hydration concerns
- **Styling:** Tailwind CSS v4 via `@tailwindcss/vite` plugin; design tokens in `src/app.css` `@theme {}`
- **Charts:** Chart.js (wrapped in `BarChart.svelte` and `DonutChart.svelte`)
- **Icons:** lucide-svelte
- **Package manager (JS):** pnpm

## Data Model

Three models in `events/models.py`, all carrying provenance fields (`source`, `source_url`,
`scraped_at`) so every row records where it came from:

- **`Venue`** — physical place: name, unique `slug`, address/city/country, website,
  lat/long. Ordered by name. `get_absolute_url` → `events:venue_detail`. Carries a
  **`verification_status`** field (`Venue.VerificationStatus` TextChoices: `pending` /
  `verified` / `rejected`, default `pending`, indexed) — the manual admin review state for
  whether a venue is genuinely an events venue. Set only by staff (admin actions or the
  `/review/` UI); **never written by the scraper upsert path**, so a reviewer's decision
  survives re-scrapes.
- **`Event`** — a scraped event, optional FK to `Venue` (`on_delete=SET_NULL`,
  `related_name="events"`). Fields: name, unique `slug`, description, `starts_at`/`ends_at`,
  url, image_url, price, category, `organizer` (CharField), `organizer_url` (URLField),
  plus an indexed `external_id`. Ordered by `starts_at, name`.
- **`Organizer`** — an event organizer scraped from partner directories. Fields: name,
  unique `slug`, **`status`** (`pending` / `confirmed` / `rejected`, default `pending`,
  indexed), contact fields (website, email, phone, address, city, country, facebook_url,
  instagram_url, description), plus provenance fields. Ordered by name. The `status` field
  is **never overwritten on re-scrape** — admin confirm/reject decisions survive subsequent
  runs. Unique constraint on `(source, external_id)` where `external_id` is non-empty.

**Dedup invariants:**
- `Event`: `UniqueConstraint(["source", "external_id"])` conditional on `external_id__gt=""`
  (named `unique_source_external_id`). Per-source upsert dedup.
- `Organizer`: same pattern — `UniqueConstraint(["source", "external_id"])` conditional on
  `external_id__gt=""` (named `unique_organizer_source_external_id`).
- **Cross-source fuzzy matching/merge does not exist yet** and is the main data-layer feature
  on the roadmap — do not assume it when reasoning about duplicates.

## Scraper Framework

The framework keeps individual scrapers tiny by centralizing persistence:

- A scraper subclasses **`BaseScraper`** (`events/scrapers/base.py`), sets a unique
  `source` key, and implements `fetch()` to yield dataclasses.
- `BaseScraper.run()` collects `fetch()` and calls the appropriate persistence helper.
- Scrapers are registered in **`events/scrapers/__init__.py`** under the `SCRAPERS` dict
  (`key -> class`). The `scrape` command resolves scrapers by this key.

**Two scraper patterns exist:**

1. **Event scrapers** — `fetch()` yields `ScrapedEvent` (optionally carrying a `ScrapedVenue`).
   `BaseScraper.run()` calls `save_events(source, events)`, which handles slugging
   (`_unique_slug`), venue upsert (`_upsert_venue`), and event upsert on `(source, external_id)`.
   Examples: `allevents_cdo` (Playwright), `happeningnext_cdo` (Playwright), `myruntime`
   (JSON API — also calls `save_organizers` to persist derived organizers).

2. **Organizer scrapers** — `fetch()` yields `ScrapedOrganizer`. The scraper overrides
   `run()` to call `save_organizers(source, organizers)` directly. `save_organizers` upserts
   on `(source, external_id)` but **never overwrites `status`** — admin decisions survive
   re-scrapes. Example: `racemeister_partners` (requests+BS4, two-phase: list then
   contact enrichment from partner websites).

**`ScrapedEvent` fields:** name, description, starts_at, ends_at, url, image_url, price,
category, external_id, source_url, organizer (str), organizer_url, venue (ScrapedVenue|None).

**`ScrapedOrganizer` fields:** name, website, email, phone, address, city, country,
facebook_url, instagram_url, description, external_id, source_url.

**Adding a scraper:** create `events/scrapers/<name>.py` with a `BaseScraper` subclass, set a
unique `source`, implement `fetch()` to yield the right dataclass, and register it in
`SCRAPERS`. Persistence is automatic — do not write to the ORM directly from a scraper.

**Current SCRAPERS registry (8 scrapers):**
```python
{
    "google_places":        GooglePlacesVenueScraper,    # venue-only, Places API
    "allevents_cdo":        AllEventsCDOScraper,          # events, Playwright
    "happeningnext_cdo":    HappeningNextCDOScraper,      # events, Playwright
    "racemeister_partners": RacemeisterPartnersScraper,   # organizers, requests+BS4
    "racemeister_events":   RacemeisterEventsScraper,     # events, requests+BS4
    "myruntime":            MyRuntimeScraper,              # events + organizers, JSON API
    "ticket2me":            Ticket2MeScraper,              # events, JSON API
    "planout":              PlanoutScraper,                # events
}
```

## Admin

`events/admin.py` registers all three models:

- **`VenueAdmin`** — list display, filters, search, slug prepopulation. Exposes the manual
  review workflow: `verification_status` in `list_display`/`list_filter`/`list_editable` plus
  bulk **Mark verified** / **Mark rejected** actions. The admin is a raw-data console; the
  staff-facing `/review/` UI (below) is the primary verification surface.
- **`EventAdmin`** — list display includes `organizer`. Fieldsets group host/organizer fields
  separately. `autocomplete_fields=("venue",)`, `date_hierarchy="starts_at"`.
- **`OrganizerAdmin`** — `status` in `list_display`/`list_filter`/`list_editable` for
  inline pending→confirmed/rejected flips. Bulk **Mark Confirmed** / **Mark Rejected** actions.
  `search_fields` covers name, email, website, phone.

## Backend API

`apps/backend/events/views.py` exposes plain Django `JsonResponse` GET endpoints (no DRF).
All are registered in `apps/backend/events/urls.py` under the `events` namespace:

| Endpoint | View name | Notes |
|---|---|---|
| `GET /api/stats/` | `api_stats` | counts of events, venues, organizers by status |
| `GET /api/events/` | `api_events` | paginated event list |
| `GET /api/events/by-source/` | `api_events_by_source` | event counts grouped by source key |
| `GET /api/events/by-category/` | `api_events_by_category` | normalized category counts; calls `normalize_category` from `events/categories.py`; returns Top-8 + "Other" |
| `GET /api/organizers/` | `api_organizers` | organizer list with status |
| `GET /api/organizers/<slug>/` | `api_organizer_detail` | single organizer detail |
| `GET /api/venues/` | `api_venues` | venue list |
| `GET /api/scrapers/` | `api_scrapers` | list of registered scraper keys and metadata |

No mutation endpoints. The frontend is purely read-only.

**Category normalization seam:** `events/categories.py` exports `normalize_category(raw: str) -> str`.
It maps raw `Event.category` values (which `myruntime` and `ticket2me` populate with
comma-joined race distances or ticket-tier names like `"10K, 5K, 3K"`) to canonical human-readable
buckets (e.g. `"Fun Run / Road Race"`). The view applies this at query time — no stored field
is mutated. Option B (adding a `raw_category` field + persisting the canonical bucket) is a
roadmap item.

## Web UI (Legacy Django Templates)

`apps/backend/events/views.py` also provides four public server-rendered views — `event_list`,
`event_detail`, `venue_list`, `venue_detail` — plus three **staff-only review views**
(`review_dashboard`, `review_venue_detail`, `review_set_status`). Templates live in
`apps/backend/templates/events/`, extending `apps/backend/templates/base.html`.

**Venue review UI (`/review/`):** a UX-friendly alternative to Django admin for the manual
venue-verification workflow. All three views are gated with `@staff_member_required`. The
dashboard shows status-count cards + filter tabs + search + a queue of venue cards.
`review_set_status` is `@require_POST`, validates against `Venue.VerificationStatus.values`,
writes with `update_fields` (status only), and returns the
`templates/events/review/_status_control.html` partial. Status changes are **HTMX**-driven —
buttons `hx-post` and swap the badge partial in place, no full reload. HTMX loaded via CDN;
CSRF rides on `<body hx-headers='{"X-CSRFToken": ...}'>`.

## Frontend (SvelteKit Admin Dashboard)

`apps/frontend/` is a **CSR-only** SvelteKit 2 + Svelte 5 admin dashboard. The SvelteKit
dev server proxies `/api/*` to the Django backend at `localhost:8000` (configured in
`vite.config.ts`).

**Routes:**

| Route | File | Notes |
|---|---|---|
| `/` | `+page.svelte` + `+page.ts` | Dashboard — StatCards, BarChart (by source), DonutChart (by category normalized) |
| `/events` | `events/+page.svelte` | Event list table with search |
| `/organizers` | `organizers/+page.svelte` | Sortable organizer table (SortHeader + sort.ts) |
| `/organizers/[slug]` | `organizers/[slug]/+page.svelte` | Organizer detail |
| `/venues` | `venues/+page.svelte` | Venue list |
| `/scrapers` | `scrapers/+page.svelte` + `+page.ts` | Scraper registry list |

**Shared components (`apps/frontend/src/lib/components/`):**
- `Sidebar.svelte` — collapsible navigation with route links
- `PageHeader.svelte` — page title + optional breadcrumb
- `Badge.svelte` — status badge (color-coded by value)
- `StatCard.svelte` — KPI card (icon + numeric value + label)
- `BarChart.svelte` — Chart.js bar chart (events by source)
- `DonutChart.svelte` — Chart.js donut chart (events by category)
- `TableSkeleton.svelte` — loading-state skeleton rows
- `SortHeader.svelte` — clickable column header; manages sort field + direction state
- `+error.svelte` — global SvelteKit error boundary

**Utilities:**
- `sort.ts` — generic client-side sort helpers for table columns (operates on current page of results only; cross-page sort requires backend `ordering=` param, not yet implemented)
- `api.ts` — typed fetch wrappers for all `/api/*` endpoints
- `types.ts` — shared TypeScript type definitions
- `format.ts` — display formatting helpers

## Key Patterns and Conventions

**Backend:**
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
- **Category normalization at the API layer only.** `normalize_category` in `events/categories.py`
  is a pure function — it does not write to the DB. The stored `Event.category` field always
  holds the raw scraper value. This is intentional; Option B (storing canonical values) is a
  roadmap item.

**Frontend:**
- **CSR-only.** `export const ssr = false` in `apps/frontend/src/routes/+layout.ts`. All data
  fetching happens in the browser via `load()` functions or inline `fetch` calls.
- **Svelte 5 runes required.** The `vite.config.ts` sets `compilerOptions.runes: true` for all
  non-`node_modules` files. Use `$state`, `$derived`, `$effect` — not legacy `$:` or stores
  for reactive state.
- **Tailwind v4 `@theme {}`.** Design tokens (colors, spacing, fonts) live in `src/app.css`
  inside the `@theme {}` block. Do not use `tailwind.config.js`-style configuration.
- **Typed API layer.** All backend calls go through `src/lib/api.ts`. Add new endpoints there,
  not as ad-hoc `fetch()` calls in route files.

## Environment and Configuration

- **Backend config:** `apps/backend/config/settings.py` (currently hardcoded dev values).
- **`.gitignore`** excludes `.env` / `.env.*`, `db.sqlite3`, `/media/`, `/staticfiles/`, `venv/`.
- **No env-var system yet.** `SECRET_KEY` is the insecure dev default, `DEBUG=True`,
  `ALLOWED_HOSTS=['localhost','127.0.0.1','testserver']`, SQLite hardcoded. Moving secrets
  to env vars (`SECRET_KEY`, `DEBUG`, `DATABASE_URL`, `ALLOWED_HOSTS`) is expected before any
  non-dev deployment — names only, never commit values.
- **Frontend dev proxy:** `apps/frontend/vite.config.ts` proxies `/api/*` to Django at
  `http://localhost:8000` during `pnpm dev`. No CORS configuration needed in dev.

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

- `apps/backend/db.sqlite3` is committed in the working tree but git-ignored; it holds dev
  data. Do not rely on it as a source of truth.
- **Category data gotcha:** `myruntime` and `ticket2me` populate `Event.category` with
  comma-joined race distances or ticket-tier names (e.g. `"10K, 5K, 3K"`,
  `"SUB1 Elite, SUB1 Competitor, Open Wave"`). Raw values are not human-readable category
  labels. Always use `normalize_category` (from `events/categories.py`) when displaying
  category data — the `/api/events/by-category/` endpoint does this automatically.
- `apps/backend/events/tests.py` holds 49 tests (as of 2026-06-17). Run with
  `cd apps/backend && ./venv/bin/python manage.py test events`.
- **Frontend has no tests yet.** `pnpm --filter frontend check` (svelte-check + tsc) and
  `pnpm --filter frontend build` are the only automated frontend verification steps.
- **No CI** is configured yet. Setting up CI to run `manage.py test` + migration check +
  `pnpm check` on push is a planned but unscheduled item.
- Production hardening (real `SECRET_KEY`, `DEBUG=False`, real DB, env config) is unaddressed
  by design at this stage.

## Scan Metadata

- Generated: 2026-06-17 (rev 3)
- Package managers: pnpm (monorepo root + frontend), pip/venv (backend)
- Active scrapers: 8 (google_places, allevents_cdo, happeningnext_cdo, racemeister_partners, racemeister_events, myruntime, ticket2me, planout)
- Migrations: 0001–0007 applied
- Backend tests: 49
- Frontend tests: 0 (svelte-check + build are the only automated verification)
