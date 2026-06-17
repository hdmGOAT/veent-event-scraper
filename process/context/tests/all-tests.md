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
`scraper-testing.md` once scrapers have a dedicated mocking pattern doc, or `e2e-tests.md`
if browser tests are added.)

## Quick Decision Guide

### Use Django's test runner for everything

This project uses **Django's built-in test framework** (`unittest`-based, via
`manage.py test`). There is no pytest, no separate e2e runner, and no CI yet. Tests live next
to the app in `apps/backend/events/tests.py` (64 tests as of 2026-06-17).

CI is planned but not yet set up; when added, it should run `manage.py test` (and a migration
check) on push/PR.

### TestCase vs. TransactionTestCase

- Use **`TestCase`** (default) for most tests — wraps each test in a transaction that rolls
  back on teardown.
- Use **`TransactionTestCase`** for tests that involve `threading.Thread` (e.g. runner tests).
  `TestCase`'s transaction wrapping means spawned threads cannot see uncommitted rows. The
  runner tests use `TransactionTestCase` and explicitly truncate data in `tearDown` because
  the DB is Neon Postgres (not an auto-destroyed temp DB).

## Default Verification Order

Unless the task clearly needs a different path:

1. run the narrowest relevant `manage.py test` target (a single test method/class)
2. widen to the app (`manage.py test events`) once the unit passes
3. for scraper/UI behavior with no automated coverage yet, verify manually via the
   `scrape` command and `runserver` (see commands below)

## Commands

Activate the venv first (from repo root or `apps/backend/`):
`source apps/backend/venv/bin/activate`

Or prefix each command with the full venv path:

| Purpose | Command | Notes |
|---|---|---|
| Run all tests | `cd apps/backend && ./venv/bin/python manage.py test events` | runs the full 64-test suite |
| Run one test class | `./venv/bin/python manage.py test events.tests.RunnerTests` | dotted path |
| Run one test method | `./venv/bin/python manage.py test events.tests.RunnerTests.test_trigger_creates_run_row` | |
| Verbose | `./venv/bin/python manage.py test events -v 2` | |
| Keep test DB | `./venv/bin/python manage.py test --keepdb` | faster reruns (Postgres) |
| Check migrations | `./venv/bin/python manage.py makemigrations --check --dry-run` | good CI gate |
| Apply migrations | `./venv/bin/python manage.py migrate` | |
| Manual scrape check | `./venv/bin/python manage.py scrape --list` / `scrape myruntime` | exercises scraper end-to-end |
| Run the app | `./venv/bin/python manage.py runserver` | Django at http://127.0.0.1:8000/ |

All commands assume CWD is `apps/backend/`.

## Debugging Quick Reference

- **Test database:** Neon PostgreSQL (configured via `DATABASE_URL` in `apps/backend/.env`).
  Django does **not** create a separate SQLite temp DB — it creates/uses a test database on
  the Neon cluster. Rows from `TransactionTestCase` tests persist until explicitly cleaned
  in `tearDown`; `TestCase` tests roll back automatically.
- **`testserver` host:** already in `ALLOWED_HOSTS`, so the test client works out of the box.
- **Timezone:** `USE_TZ=True`. Use `django.utils.timezone.now()` in tests, not naive
  `datetime`, or comparisons against model datetimes will be wrong.
- **Scraper tests:** mock outbound HTTP (`requests.get`) and scraper execution
  (`SCRAPERS[key]().run()`) rather than hitting live sites. Assert on the `{"created", "updated"}`
  dict and on resulting DB rows.
- **Runner tests require `TransactionTestCase`:** see TestCase vs. TransactionTestCase above.
  Mock `SCRAPERS[key]().run()` so no real scraper execution happens in tests.
- **Common failure: rows from a prior TransactionTestCase test bleeding into the next** —
  ensure `tearDown` truncates `ScraperRun.objects.all().delete()` (and any other model rows
  created without transaction rollback).

## Known Gaps

- **No CI** is configured yet (planned). No coverage measurement.
- **No frontend (Svelte) tests.** The SvelteKit frontend has no unit or e2e test suite yet.
- **Playwright scrapers are not tested end-to-end.** `allevents_cdo` and `happeningnext_cdo`
  require a live Playwright session; they are excluded from automated tests.
- **No view/template tests for the Django-rendered list/detail pages** (event_list, venue_list,
  etc.), only the `/review/` staff UI has coverage.
