# Veent Event Scraper - All Tests

Last updated: 2026-06-16

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

### Use Django's test runner for everything

This project uses **Django's built-in test framework** (`unittest`-based, via
`manage.py test`). There is no pytest, no separate e2e runner, and no CI yet. Tests live next
to the app in `events/tests.py` (currently an empty placeholder — see Known Gaps).

CI is planned but not yet set up; when added, it should run `manage.py test` (and a migration
check) on push/PR.

## Default Verification Order

Unless the task clearly needs a different path:

1. run the narrowest relevant `manage.py test` target (a single test method/class)
2. widen to the app (`manage.py test events`) once the unit passes
3. for scraper/UI behavior with no automated coverage yet, verify manually via the
   `scrape` command and `runserver` (see commands below)

## Commands

Activate the venv first: `source venv/bin/activate`

| Purpose | Command | Notes |
|---|---|---|
| Run all tests | `python manage.py test` | discovers `events/tests.py` (empty today) |
| Run one app | `python manage.py test events` | |
| Run one test | `python manage.py test events.tests.MyTest.test_x` | dotted path |
| Verbose | `python manage.py test -v 2` | |
| Keep test DB | `python manage.py test --keepdb` | faster reruns once tests exist |
| Check migrations | `python manage.py makemigrations --check --dry-run` | good CI gate |
| Apply migrations | `python manage.py migrate` | |
| Manual scrape check | `python manage.py scrape --list` / `python manage.py scrape example` | exercises the scraper path end-to-end |
| Run the app | `python manage.py runserver` | UI at http://127.0.0.1:8000/, admin at /admin/ |

## Debugging Quick Reference

- **Test database:** Django creates a separate test DB automatically (a temp SQLite DB);
  it does not touch `db.sqlite3`. No `.env.test` or external DB needed.
- **`testserver` host:** already in `ALLOWED_HOSTS`, so the test client works out of the box.
- **Timezone:** `USE_TZ=True`. Use `django.utils.timezone.now()` in tests, not naive
  `datetime`, or comparisons against model datetimes will be wrong.
- **Scraper tests:** since `save_events` writes to the DB, test scrapers with
  `TestCase` (transactional rollback per test). Mock outbound HTTP (`requests.get`) rather
  than hitting live sites; assert on the `{"created", "updated"}` dict and on resulting rows.

## Known Gaps

- **No tests exist yet.** `events/tests.py` is the default placeholder. The highest-value
  first tests: `save_events` upsert/dedup behavior (the `unique_source_external_id`
  constraint), slug uniqueness, and the `scrape` command's unknown-key / `--list` handling.
- **No CI** is configured yet (planned). No coverage measurement.
- **No tests** for the views/search or templates.
