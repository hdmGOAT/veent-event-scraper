# Technical Debt Analysis

> Scope: `apps/backend/` and `apps/frontend/` — code quality, maintainability, and architectural concerns

---

## TD-1 · HIGH · `views.py` is a 1233-line god object mixing HTML, API, and webhook concerns

**File:** [apps/backend/events/views.py](../../apps/backend/events/views.py) (1233 lines)

All 30+ view functions live in one file, serving three different concerns:

| Concern | Examples |
|---|---|
| HTML page rendering | `event_list`, `venue_list`, `scraper_list` |
| JSON API endpoints | `api_events`, `api_scrapers`, `api_organizers` |
| Webhook handlers | `scraper_webhook`, `n8n_webhook` |
| Admin actions | `api_settings_proxy`, `api_scripts` |

This makes the file:
- Hard to navigate (finding a specific endpoint requires scrolling through 1200 lines)
- Hard to test in isolation (all views share module-level state like `_DEDUP_LOCK`)
- Hard to version (changing any view requires a full diff of the monolith)

**Recommended split:**

```
events/
├── views/
│   ├── __init__.py      (imports for backwards compat)
│   ├── pages.py         (HTML rendering views)
│   ├── api/
│   │   ├── events.py
│   │   ├── scrapers.py
│   │   ├── organizers.py
│   │   ├── venues.py
│   │   └── settings.py
│   └── webhooks.py
```

---

## TD-2 · HIGH · `base.py` is a 557-line mixed-responsibility module

**File:** [apps/backend/events/scrapers/base.py](../../apps/backend/events/scrapers/base.py) (557 lines)

`base.py` conflates three responsibilities:
1. **BaseScraper interface** — the abstract class scrapers inherit from
2. **Persistence helpers** — `save_events`, `save_venues`, `_resolve_organizer`
3. **Dedup helpers** — `_dedup_after_save`, `_dedup_events_by_title`
4. **Dataclasses** — `ScrapedEvent`, `ScrapedVenue`, `ScrapedOrganizer`

**Recommended split:**

```
events/scrapers/
├── base.py          (~100 lines) — BaseScraper ABC only
├── types.py         (~80 lines)  — ScrapedEvent, ScrapedVenue dataclasses
├── persistence.py   (~200 lines) — save_events, save_venues, _resolve_organizer
└── dedup.py         (~120 lines) — _dedup_after_save, _dedup_events_by_title
```

---

## TD-3 · HIGH · `tests.py` is a 1927-line monolithic test file

**File:** [apps/backend/events/tests.py](../../apps/backend/events/tests.py) (1927 lines)

All tests — unit, integration, model, view, scraper — live in one file. This causes:
- Long test runs where only a subset of tests are relevant to the change
- Difficult navigation when debugging failures
- `sys.path` manipulation at the top to import the standalone `scripts/deduplicate.py`
- `psycopg2` direct imports that fail on SQLite (see [BUG-11](BUGS.md#bug-11--low--psycopg2extrarealdictcursor-imported-in-tests--fails-on-sqlite))

**Recommended split:**

```
events/tests/
├── __init__.py
├── test_models.py
├── test_views.py
├── test_scrapers/
│   ├── test_base.py
│   ├── test_dedup.py
│   └── test_facebook_events.py
└── test_ai_categories.py
```

---

## TD-4 · MEDIUM · No task queue — all long-running work blocks the request or spawns unmanaged subprocesses

**Files:** [apps/backend/events/runner.py](../../apps/backend/events/runner.py), [apps/backend/events/views.py](../../apps/backend/events/views.py)

Scraper runs are triggered via HTTP POST and executed as OS subprocesses managed by `runner.py`. Deduplication is triggered via another HTTP POST. AI categorization is triggered synchronously within the scraper subprocess. There is no task queue (Celery, Django Q, RQ, etc.), which means:

- **No retry on failure** — a subprocess crash leaves the run in RUNNING state
- **No scheduling** — scrapers can only be triggered manually or via n8n webhook
- **No concurrency control** — the `unique_active_scraper_run` constraint is the only guard
- **No visibility** — there's no queue depth, position, or ETA for pending runs
- **Process leaks** — if Django crashes, orphaned subprocess PIDs are never cleaned up

**Recommendation:** Introduce Celery + Redis (or Django Q for simpler setup) for all long-running operations. This is a significant architectural change but unlocks scheduling, retries, progress reporting, and reliable failure handling.

Short-term mitigation: Add a startup hook in `AppConfig.ready()` that scans for `ScraperRun` records stuck in `RUNNING` state from a previous Django process and marks them `ERROR`.

---

## TD-5 · MEDIUM · Webhook handler is synchronous — blocks Django worker thread for the full scraper duration

**File:** [apps/backend/events/views.py:1060-1100](../../apps/backend/events/views.py#L1060-L1100)

The n8n webhook endpoint triggers a scraper, waits for it to complete, then returns the result in the HTTP response. Scraper runs can take minutes. During this time the Django worker thread is blocked:

- Under `runserver` (single-threaded): no other requests are served
- Under `gunicorn --workers 1`: same problem
- Under `gunicorn --workers N`: N-1 workers remain available, but a single long webhook call depletes one worker for minutes

**Fix:** Return `202 Accepted` immediately with a `run_id`, and let the caller poll `GET /api/scrapers/runs/<id>/` for status:

```python
def scraper_webhook(request):
    run = trigger_scraper_run(key)
    return JsonResponse({"run_id": str(run.pk), "status": "accepted"}, status=202)
```

---

## TD-6 · MEDIUM · Custom `.env` loader instead of `python-dotenv`

**File:** [apps/backend/config/settings.py:1-30](../../apps/backend/config/settings.py#L1-L30)

```python
def _load_dotenv():
    env_file = BASE_DIR / ".env"
    ...
    for line in f:
        if "=" in line and not line.startswith("#"):
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())
```

The custom loader:
- Does not handle quoted values (`KEY="value with spaces"`)
- Does not handle multiline values
- Does not handle escaped characters
- Does not search parent directories (standard behavior in `python-dotenv`)
- Is untested

**Fix:**

```bash
pip install python-dotenv
```

```python
# settings.py
from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")
```

---

## TD-7 · MEDIUM · Inline JavaScript strings in `facebook_events.py` are hard to maintain

**File:** [apps/backend/events/scrapers/facebook_events.py](../../apps/backend/events/scrapers/facebook_events.py)

Four large JavaScript payloads are embedded as Python string literals:
- `_DISMISS_MODAL_JS` — closes cookie/login dialogs
- `_EXTRACT_SEARCH_JS` — extracts event cards from search results
- `_EXTRACT_DETAIL_JS` — extracts detail from an event page
- `_EXTRACT_ORGANIZER_JS` — extracts organizer info

These strings:
- Have no syntax highlighting in editors
- Cannot be independently tested
- Cannot be linted by JS tooling
- Are difficult to diff in code review

**Fix:** Extract each to a `.js` file in `events/scrapers/js/`, loaded at import time:

```python
import importlib.resources

def _load_js(name: str) -> str:
    return (importlib.resources.files("events.scrapers.js") / name).read_text()

_DISMISS_MODAL_JS = _load_js("dismiss_modal.js")
_EXTRACT_SEARCH_JS = _load_js("extract_search.js")
```

---

## TD-8 · MEDIUM · `Organizer` uses plain string constants; `Venue` uses `TextChoices` — inconsistent patterns

**File:** [apps/backend/events/models.py:50-80](../../apps/backend/events/models.py#L50-L80)

```python
# Venue — correct pattern
class StatusChoices(models.TextChoices):
    ACTIVE = "active", "Active"
    PENDING = "pending", "Pending"

# Organizer — legacy pattern
STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_REJECTED = "rejected"
status = models.CharField(max_length=20, default=STATUS_PENDING)
```

The `Organizer` model's plain constants do not integrate with Django admin dropdown rendering, form validation, or `get_FOO_display()`.

**Fix:**

```python
class Organizer(models.Model):
    class StatusChoices(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        REJECTED = "rejected", "Rejected"

    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.PENDING,
    )
```

---

## TD-9 · MEDIUM · Process-local `_DEDUP_LOCK` provides no protection across multiple Django workers

**File:** [apps/backend/events/views.py:45](../../apps/backend/events/views.py#L45)

```python
_DEDUP_LOCK = threading.Lock()
```

This lock serializes dedup calls within a single Django process. With multiple workers (gunicorn `--workers N`), two simultaneous dedup requests from different workers are not serialized. The dedup operation is not idempotent under concurrent execution — two processes running dedup at the same time can both observe the same duplicates and both try to delete/keep them, leading to inconsistent results.

**Fix:** Use a database-level advisory lock (PostgreSQL) or `SELECT ... FOR UPDATE` on a sentinel row rather than a threading lock:

```python
from django.db import connection

def _dedup_with_db_lock():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(42)")  # PostgreSQL
    try:
        _run_dedup()
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(42)")
```

---

## TD-10 · MEDIUM · No structured logging — all logs are unformatted strings

**File:** Multiple scrapers and `runner.py`

All log output uses `logger.info("Scraper %s: saved %d events", key, n)` — unstructured text. This makes it impossible to:
- Filter logs by scraper key, run ID, or event count in a log aggregation system
- Build dashboards or alerts on scraper performance
- Parse historical run data from log files

**Fix:** Use structured logging with `structlog` or Django's built-in `extra` parameter:

```python
logger.info(
    "Events saved",
    extra={"scraper_key": self.key, "run_id": self.run_id, "count": n},
)
```

Or configure a JSON log formatter for production:

```python
LOGGING = {
    "formatters": {
        "json": {"()": "pythonjsonlogger.jsonlogger.JsonFormatter"},
    },
    ...
}
```

---

## TD-11 · LOW · Dead `nodeApi` client in the frontend — no Node.js backend exists

**File:** [apps/frontend/src/lib/api.ts:45-60](../../apps/frontend/src/lib/api.ts#L45-L60)

```typescript
export const nodeApi = {
  get: (path: string) => fetch(`/node-api${path}`).then(...),
  post: (path: string, body: unknown) => fetch(`/node-api${path}`, ...).then(...),
}
```

There is no Node.js API server in the monorepo. The `/node-api/*` prefix is not proxied anywhere in `vite.config.ts`. All these calls would result in 404s. This is likely a leftover from an earlier architectural plan.

**Fix:** Delete `nodeApi` and any call sites that reference it.

---

## TD-12 · LOW · `DJANGO_ALLOW_ASYNC_UNSAFE=true` set globally in the scraper worker subprocess

**File:** [apps/backend/events/management/commands/run_scraper_job.py:35](../../apps/backend/events/management/commands/run_scraper_job.py#L35)

```python
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
```

This flag suppresses Django's runtime check that prevents ORM calls from async contexts. It is set because Playwright's synchronous API internally uses an event loop, which confuses Django's async safety detection. Setting it globally suppresses warnings for all code running in that process, masking legitimate async-safety violations that might be introduced in the future.

**Fix:** Identify the exact Playwright call that triggers the warning and wrap it with `async_unsafe()` locally, rather than disabling the check globally:

```python
from asgiref.sync import async_unsafe

@async_unsafe("Playwright sync API within Django")
def _run_playwright_scrape(self):
    ...
```

---

## TD-13 · LOW · No API versioning

**File:** [apps/backend/events/urls.py](../../apps/backend/events/urls.py)

All API endpoints are at `/api/<resource>/` with no version prefix. Adding a breaking change to an API shape requires coordinating the frontend and backend releases simultaneously. With a `/api/v1/` prefix, the old and new shapes can coexist during migration.

**Fix:** Add versioning now while the API surface is small:

```python
# urls.py
urlpatterns = [
    path("api/v1/", include("events.urls_v1")),
    # Keep old /api/ routes for backwards compat during migration
]
```

---

## TD-14 · LOW · Messy migration history with duplicate numbering

See [BUG-12](BUGS.md#bug-12--low--migration-numbering-has-duplicate-and-conflicting-entries) for details. The schema is correct but the linear numbering has gaps and duplicates that indicate parallel development without branch coordination.

**Recommendation:** After all environments are in sync, squash to a clean linear history.

---

## TD-15 · INFO · `facebook_events.py` at 1267 lines is approaching unmaintainable size

**File:** [apps/backend/events/scrapers/facebook_events.py](../../apps/backend/events/scrapers/facebook_events.py) (1267 lines)

The file handles browser session lifecycle, proxy management, CDP bandwidth tracking, modal dismissal, search result extraction, event detail extraction, organizer extraction, retry logic, and keyword iteration. These are separable concerns.

**Recommended split:**

```
events/scrapers/facebook/
├── __init__.py          (registers FacebookEventsScraper)
├── scraper.py           (~300 lines) — main scraper class + keyword loop
├── browser.py           (~150 lines) — browser/page lifecycle, CDP setup
├── extractors.py        (~200 lines) — JS extraction helpers
└── js/
    ├── dismiss_modal.js
    ├── extract_search.js
    ├── extract_detail.js
    └── extract_organizer.js
```
