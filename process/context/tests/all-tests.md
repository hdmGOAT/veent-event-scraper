# Veent Event Scraper - All Tests

Last updated: 2026-06-17

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
`scraper-testing.md` once scrapers have a mocking pattern, or `e2e-tests.md` if browser
tests are added.)

## Quick Decision Guide

### Backend: Django's test runner

The backend uses **Django's built-in test framework** (`unittest`-based, via
`manage.py test`). There is no pytest. Tests live at `apps/backend/events/tests.py`.
49 tests as of 2026-06-17, covering: scraper upsert/dedup, venue dedup, `verification_status`
re-scrape preservation, `Organizer.status` re-scrape preservation, category normalization
(`normalize_category`), and the `/review/` UI views.

### Frontend: svelte-check + build (no unit tests yet)

The frontend has no Vitest or Playwright tests. The two automated checks are:
- `pnpm --filter frontend check` — runs svelte-check + tsc (type errors, Svelte compiler warnings)
- `pnpm --filter frontend build` — full Vite production build (catches import errors, missing modules)

CI is planned but not yet set up. When added it should run `manage.py test`, a migration
check, and `pnpm --filter frontend check` on push/PR.

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

All backend commands assume cwd `apps/backend/`. The venv is at `apps/backend/venv/`.

| Purpose | Command | Notes |
|---|---|---|
| Run all backend tests | `cd apps/backend && ./venv/bin/python manage.py test` | discovers `events/tests.py` |
| Run one app | `cd apps/backend && ./venv/bin/python manage.py test events` | |
| Run one test class | `cd apps/backend && ./venv/bin/python manage.py test events.tests.MyTest` | dotted path |
| Run one test method | `cd apps/backend && ./venv/bin/python manage.py test events.tests.MyTest.test_x` | |
| Verbose | `cd apps/backend && ./venv/bin/python manage.py test -v 2` | |
| Keep test DB | `cd apps/backend && ./venv/bin/python manage.py test --keepdb` | faster reruns |
| Check migrations | `cd apps/backend && ./venv/bin/python manage.py makemigrations --check --dry-run` | good CI gate |
| Apply migrations | `cd apps/backend && ./venv/bin/python manage.py migrate` | |
| Manual scrape check | `cd apps/backend && ./venv/bin/python manage.py scrape --list` | lists registered scrapers |
| Frontend type-check | `pnpm --filter frontend check` | svelte-check + tsc |
| Frontend build | `pnpm --filter frontend build` | Vite production build |
| Full dev stack | `pnpm dev` (root) | starts backend + frontend; frontend proxies /api/* to :8000 |

## Debugging Quick Reference

- **Test database:** Django creates a separate test DB automatically (a temp SQLite DB);
  it does not touch `db.sqlite3`. No `.env.test` or external DB needed.
- **`testserver` host:** already in `ALLOWED_HOSTS`, so the test client works out of the box.
- **Timezone:** `USE_TZ=True`. Use `django.utils.timezone.now()` in tests, not naive
  `datetime`, or comparisons against model datetimes will be wrong.
- **Scraper tests:** since `save_events` / `save_organizers` write to the DB, test scrapers
  with `TestCase` (transactional rollback per test). Mock outbound HTTP (`requests.get`) rather
  than hitting live sites; assert on the `{"created", "updated"}` dict and on resulting rows.
- **Category tests:** `normalize_category` is a pure function — test it directly, no DB needed.
- **Frontend check failures:** if `pnpm --filter frontend check` fails with type errors on
  Svelte 5 runes, ensure the file is not in `node_modules` (runes are forced for all project
  files via `vite.config.ts`).

## Known Gaps

- **No frontend tests.** Highest-value first tests: organizer table sort logic (`sort.ts`),
  `normalize_category` end-to-end via the `/api/events/by-category/` response shape, and
  the `StatCard` / `Badge` component rendering.
- **No CI** is configured yet (planned). No coverage measurement.
- **No e2e tests.** No Playwright suite exists. The `/review/` HTMX flow and the SvelteKit
  routes have no browser-level automated coverage.
- **Scraper mocking pattern** not yet standardized into a shared fixture or base class.
  Each scraper test currently sets up its own mock; extract when the pattern stabilizes.
