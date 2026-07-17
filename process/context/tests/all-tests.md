# Veent Event Scraper - All Tests

Last updated: 2026-07-16

Attach this file first when the task involves testing, verification, or test debugging.

This is the fast operator guide for the testing surface:

- which runner to use
- what command to start with
- how to quickly debug common failures
- which deeper file to read next

Do not load the whole `process/context/tests/` folder by default. Start here, then drill down.

---

## What This Covers

- test runner selection
- quick commands
- fast debugging procedures
- current testing gaps worth remembering

## Read This When

Use this file when you need to:

- run tests after implementation
- decide how to verify a change
- debug failing tests

## Quick Routing

(No deeper test docs yet. Add routing entries here as they are created — e.g. a
`scraper-testing.md` once scrapers have a dedicated mocking pattern doc, or `e2e-tests.md`
if browser tests are added.)

## Quick Decision Guide

### Backend: Django's test runner

The backend uses **Django's built-in test framework** (`unittest`-based, via `manage.py test`).
There is no pytest and no separate e2e runner. CI is configured (`.github/workflows/ci.yml`).
Tests live next to the app at `apps/backend/events/tests.py` — **197 tests as of 2026-07-16**,
covering: scraper upsert/dedup, venue dedup, `verification_status` re-scrape preservation,
`Organizer.status` re-scrape preservation, category normalization (`normalize_category`), the
`/review/` UI views, and the scraper run-jobs subsystem (`runner.py` — trigger/cancel/run-all).

**Important:** backend tests must be run with `DEBUG=true`. With `DEBUG=False`, the production
`SECURE_SSL_REDIRECT=True` block issues 301 redirects that break ~48 view and API tests.
CI sets `DEBUG: "true"` in the backend job env to enforce this.

### Frontend: svelte-check + build (no unit tests yet)

The frontend has no Vitest or Playwright tests. The two automated checks are:
- `pnpm --filter frontend check` — runs svelte-check + tsc (type errors, Svelte compiler warnings)
- `pnpm --filter frontend build` — full Vite production build (catches import errors, missing modules)

CI runs these checks: `.github/workflows/ci.yml` backend job (with `DEBUG: "true"`) +
migration check + `pnpm --filter frontend check` on push/PR.

### TestCase vs. TransactionTestCase

- Use **`TestCase`** (default) for most tests — wraps each test in a transaction that rolls
  back on teardown.
- Use **`TransactionTestCase`** for tests that involve `threading.Thread` (e.g. runner tests).
  `TestCase`'s transaction wrapping means spawned threads cannot see uncommitted rows. The
  runner tests use `TransactionTestCase` and explicitly truncate data in `tearDown` because
  the DB is Neon Postgres (not an auto-destroyed temp DB).

## Default Verification Order

After any backend change:

1. run the narrowest relevant `manage.py test` target (a single test method/class)
2. widen to the app (`manage.py test events`) once the unit passes
3. for scraper behavior with no automated coverage, verify manually via the `scrape` command

After any frontend change:

1. `pnpm --filter frontend check` — catch type and compiler errors
2. `pnpm --filter frontend build` — catch bundler/import errors
3. manual browser check via `pnpm dev` (proxy to Django at localhost:8000)

## Commands

All backend commands assume cwd `apps/backend/`. The venv is at `apps/backend/venv/` — activate
it with `source apps/backend/venv/bin/activate`, or prefix each command with `./venv/bin/python`.

| Purpose | Command | Notes |
|---|---|---|
| Run all backend tests | `cd apps/backend && DEBUG=true ./venv/bin/python manage.py test events` | runs the full 197-test suite; DEBUG=true required |
| Run all (discovery) | `cd apps/backend && DEBUG=true ./venv/bin/python manage.py test` | discovers `events/tests.py` |
| Run one test class | `cd apps/backend && ./venv/bin/python manage.py test events.tests.RunnerTests` | dotted path |
| Run one test method | `cd apps/backend && ./venv/bin/python manage.py test events.tests.RunnerTests.test_trigger_creates_run_row` | |
| Verbose | `cd apps/backend && ./venv/bin/python manage.py test events -v 2` | |
| Keep test DB | `cd apps/backend && ./venv/bin/python manage.py test --keepdb` | faster reruns (Postgres) |
| Check migrations | `cd apps/backend && ./venv/bin/python manage.py makemigrations --check --dry-run` | good CI gate |
| Apply migrations | `cd apps/backend && ./venv/bin/python manage.py migrate` | |
| Manual scrape check | `cd apps/backend && ./venv/bin/python manage.py scrape --list` / `scrape myruntime` | lists registered scrapers / exercises one end-to-end |
| Run the app | `cd apps/backend && ./venv/bin/python manage.py runserver` | Django at http://127.0.0.1:8000/ |
| Frontend type-check | `pnpm --filter frontend check` | svelte-check + tsc |
| Frontend build | `pnpm --filter frontend build` | Vite production build |
| Full dev stack | `pnpm dev` (root) | starts backend + frontend; frontend proxies /api/* to :8000 |

## Debugging Quick Reference

- **Test database:** Neon PostgreSQL (configured via `DATABASE_URL` in `apps/backend/.env`).
  Django does **not** create a separate SQLite temp DB — it creates/uses a test database on
  the Neon cluster. Rows from `TransactionTestCase` tests persist until explicitly cleaned
  in `tearDown`; `TestCase` tests roll back automatically.
- **`testserver` host:** already in `ALLOWED_HOSTS`, so the test client works out of the box.
- **Timezone:** `USE_TZ=True`. Use `django.utils.timezone.now()` in tests, not naive
  `datetime`, or comparisons against model datetimes will be wrong.
- **Scraper tests:** mock the scraper's outbound boundary (e.g. `requests.get` for HTTP-based
  scrapers, or browser/page objects for Playwright-backed ones) and scraper execution
  (`SCRAPERS[key]().run()`) rather than hitting live sites. For scrapers that persist via
  `save_events` / `save_organizers`, a plain `TestCase` (transactional rollback per test) is
  fine. Assert on the `{"created", "updated"}` dict and on resulting DB rows.
- **Category tests:** `normalize_category` is a pure function — test it directly, no DB needed.
- **Runner tests require `TransactionTestCase`:** see TestCase vs. TransactionTestCase above.
  Mock `SCRAPERS[key]().run()` so no real scraper execution happens in tests.
- **Common failure: rows from a prior TransactionTestCase test bleeding into the next** —
  ensure `tearDown` truncates `ScraperRun.objects.all().delete()` (and any other model rows
  created without transaction rollback).
- **Frontend check failures:** if `pnpm --filter frontend check` fails with type errors on
  Svelte 5 runes, ensure the file is not in `node_modules` (runes are forced for all project
  files via `vite.config.ts`).

## Debugging Quick Reference — DEBUG=true requirement

**Backend tests require `DEBUG=true`.** With `DEBUG=False`, `settings.py` activates
`SECURE_SSL_REDIRECT=True` (production hardening block). Django's test client then receives
`301 Moved Permanently` on view and API requests instead of the expected `200`/`302`, causing
~48 test failures. Always prefix backend test commands with `DEBUG=true` or set it in
`apps/backend/.env`. CI enforces this via `DEBUG: "true"` in the backend job environment.

## Known Gaps

- **No frontend (Svelte) tests.** Highest-value first tests: organizer table sort logic
  (`sort.ts`), `normalize_category` end-to-end via the `/api/events/by-category/` response
  shape, and the `StatCard` / `Badge` component rendering.
- **No coverage measurement.** CI runs tests but does not measure or enforce coverage thresholds.
- **No e2e tests.** No Playwright suite exists. The `/review/` HTMX flow and the SvelteKit
  routes (including the Scraper Center and auth gate) have no browser-level automated coverage.
- **Playwright scrapers are not tested end-to-end.** `allevents_cdo` and `happeningnext_cdo`
  require a live Playwright session; they are excluded from automated tests.
- **No view/template tests for the Django-rendered list/detail pages** (event_list, venue_list,
  etc.); only the `/review/` staff UI has coverage.
- **Scraper mocking pattern** not yet standardized into a shared fixture or base class.
  Each scraper test currently sets up its own mock; extract when the pattern stabilizes.
