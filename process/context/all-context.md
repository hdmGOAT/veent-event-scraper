# Veent Event Scraper - All Context

Last updated: 2026-06-16 (rev 2 — Organizer model, myruntime + racemeister scrapers)

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

**Current state vs. target:** The repo today is a clean, working Django scaffold — `Venue`
and `Event` models with scraping-provenance fields, a small pluggable scraper framework, a
`manage.py scrape` command, Django admin registrations, and a server-rendered list/detail
UI with search. The example scraper yields demo data. The larger product vision (many real
scrapers, fuzzy cross-source dedup/merge, CSV + JSON/REST export, monitoring dashboards) is
**not yet built** — it is the roadmap this codebase grows into.

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
inline below (three models, several migrations). A `scrapers/` context group is now a strong
candidate — the project has 4 real scrapers with two distinct patterns (event scrapers and
organizer scrapers). Create it when scraper-specific docs exceed one screen of inline prose.

## Task Routing Table

| If the task involves... | Start with | Then load |
|---|---|---|
| architecture or stack questions | this file | — |
| adding or changing a scraper | this file (Scraper Framework section) | `events/scrapers/base.py`, `events/scrapers/__init__.py`, existing scraper for pattern |
| models / schema / migrations | this file (Data Model section) | `events/models.py`, `events/migrations/` |
| admin behavior | this file (Admin section) | `events/admin.py` |
| views / templates / UI | this file (Web UI section) | `events/views.py`, `events/urls.py`, `templates/events/` |
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

```
veent-event-scraper/
  manage.py                 -- Django entrypoint
  requirements.txt          -- pip dependencies (Django 6, requests, bs4, lxml)
  db.sqlite3                -- dev database (git-ignored)
  config/                   -- Django project package
    settings.py             -- settings (SQLite, INSTALLED_APPS, etc.)
    urls.py                 -- root URLConf (admin/ + events app)
    wsgi.py / asgi.py       -- server entrypoints
  events/                   -- the single application
    models.py               -- Venue, Event, Organizer models (scraping provenance fields)
    views.py                -- list/detail views with search + staff /review/ UI
    urls.py                 -- app URLConf (namespace "events")
    admin.py                -- VenueAdmin, EventAdmin, OrganizerAdmin
    tests.py                -- Django TestCase suite (scraper, dedup, verification, review UI)
    migrations/             -- 0001_initial … 0007_organizer
    scrapers/               -- scraper framework
      base.py               -- BaseScraper + ScrapedEvent/ScrapedVenue/ScrapedOrganizer + save_events/save_organizers
      allevents.py          -- AllEventsCDOScraper (key: allevents_cdo, Playwright)
      happeningnext.py      -- HappeningNextCDOScraper (key: happeningnext_cdo, Playwright)
      myruntime.py          -- MyRuntimeScraper (key: myruntime, JSON API)
      places.py             -- GooglePlacesVenueScraper (key: google_places, Places API)
      racemeister.py        -- RacemeisterPartnersScraper (key: racemeister_partners, requests+BS4)
      __init__.py           -- SCRAPERS registry {key -> class}
    management/commands/
      scrape.py             -- `manage.py scrape [source] [--list]`
  templates/                -- server-rendered UI
    base.html
    events/                 -- event_list, event_detail, venue_list, venue_detail
      review/               -- staff /review/ UI: dashboard, venue_detail, _status_control partial
  process/                  -- agent harness workspace (context, plans, protocols)
```

## Technology Stack

- **Framework:** Django 6.0.6
- **Language / runtime:** Python 3.14 (venv at `./venv`)
- **Database:** SQLite (`db.sqlite3`) via the Django ORM (dev only; production DB undecided)
- **Scraping:** `requests` 2.34 for HTTP, `beautifulsoup4` 4.15 + `lxml` 6.1 for HTML parsing
- **Admin:** Django's built-in admin (`django.contrib.admin`) is the primary operator surface
- **UI:** server-rendered Django templates (`APP_DIRS` + project-level `templates/`); no JS framework
- **Package manager:** pip + `requirements.txt`, virtualenv (`venv/`)
- **Auth:** Django's built-in `django.contrib.auth` (admin login only; no third-party auth)

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

**Current SCRAPERS registry:**
```python
{
    "google_places":       GooglePlacesVenueScraper,   # venue-only, Places API
    "allevents_cdo":       AllEventsCDOScraper,         # events, Playwright
    "happeningnext_cdo":   HappeningNextCDOScraper,     # events, Playwright
    "myruntime":           MyRuntimeScraper,             # events + organizers, JSON API
    "racemeister_partners":RacemeisterPartnersScraper,   # organizers, requests+BS4
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

## Web UI

`events/views.py` provides four public function-based views — `event_list`, `event_detail`,
`venue_list`, `venue_detail` — plus three **staff-only review views** (`review_dashboard`,
`review_venue_detail`, `review_set_status`). All are wired in `events/urls.py` under the
`events` namespace and included at the site root in `config/urls.py` (admin lives at
`/admin/`). List views support a `?q=` search (icontains across name/description/venue for
events; name/city for venues) and use `select_related` / `annotate(Count)` to avoid N+1
queries. Templates live in `templates/events/`, extending `templates/base.html`.

**Venue review UI (`/review/`):** a UX-friendly alternative to Django admin for the manual
venue-verification workflow. All three views are gated with `@staff_member_required` (reuses
Django auth — no new auth system). The dashboard shows status-count cards + filter tabs +
search + a queue of venue cards; the detail view adds website/map/rating/amenities/recent
events. `review_set_status` is `@require_POST`, validates against
`Venue.VerificationStatus.values`, writes with `update_fields` (status only), and returns the
`templates/events/review/_status_control.html` partial. Status changes are **HTMX**-driven —
buttons `hx-post` and swap the badge partial in place, no full reload. HTMX is loaded via CDN
in `base.html`; CSRF rides on `<body hx-headers='{"X-CSRFToken": ...}'>`. Styling extends the
existing CSS-variable dark design system (no Tailwind, no build step).

## Key Patterns and Conventions

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

## Environment and Configuration

- **Config file:** `config/settings.py` (currently hardcoded dev values).
- **`.gitignore`** already excludes `.env` / `.env.*`, `db.sqlite3`, `/media/`, `/staticfiles/`, `venv/`.
- **No env-var system yet.** `SECRET_KEY` is the insecure dev default, `DEBUG=True`,
  `ALLOWED_HOSTS=['localhost','127.0.0.1','testserver']`, SQLite hardcoded. Moving secrets
  and environment-specific settings to env vars (e.g. `SECRET_KEY`, `DEBUG`, `DATABASE_URL`,
  `ALLOWED_HOSTS`) is expected before any non-dev deployment — names only, never commit values.

## Gotchas / Watch-outs

- `db.sqlite3` is committed in the working tree but git-ignored; it holds demo data from the
  example scraper. Do not rely on it as a source of truth.
- `events/tests.py` now holds a real Django `TestCase` suite (21 tests as of 2026-06-16)
  covering the Places scraper, venue dedup/upsert, the `verification_status` field
  (including re-scrape preservation), and the `/review/` UI. Run with
  `./venv/bin/python manage.py test events`.
- Production hardening (real `SECRET_KEY`, `DEBUG=False`, real DB, env config) is unaddressed
  by design at this stage.

## Scan Metadata

- Generated: 2026-06-16 (rev 2 updated same day)
- Package manager: pip (requirements.txt + venv)
- Active scrapers: 5 (google_places, allevents_cdo, happeningnext_cdo, myruntime, racemeister_partners)
- Migrations: 0001–0007 applied
