# Bug Analysis

> Scope: `apps/backend/` — correctness bugs, logic errors, and silent failure modes

---

## BUG-1 · HIGH · `_resolve_organizer` performs a full-table scan on every save

**File:** [apps/backend/events/scrapers/base.py:413-415](../../apps/backend/events/scrapers/base.py#L413-L415)

```python
for org in Organizer.objects.filter(website__gt=""):
    if org.website and _norm(data.get("website", "")) == _norm(org.website):
        return org
```

`Organizer.objects.filter(website__gt="")` fetches every organizer with a non-empty website field from the database. The URL normalization and comparison happen in Python. This means:

- **N rows fetched** on every `save_events()` call, for every scraper run
- As the organizer table grows the cost scales linearly
- No index on `website` is used — the filtering is post-fetch

**Root cause:** The intent is to normalize URLs before comparing, which can't be done with a raw SQL `=`. But most normalization (strip trailing slash, lowercase scheme/host) can be applied at write time, allowing an indexed lookup.

**Fix:**

```python
# At write time, store the normalized form alongside the raw URL:
class Organizer(models.Model):
    website = models.URLField(blank=True, default="")
    website_normalized = models.CharField(max_length=500, blank=True, default="", db_index=True)

    def save(self, *args, **kwargs):
        self.website_normalized = _norm(self.website)
        super().save(*args, **kwargs)

# At lookup time:
normalized = _norm(data.get("website", ""))
if normalized:
    return Organizer.objects.filter(website_normalized=normalized).first()
```

---

## BUG-2 · HIGH · `_map_result` stores all event IDs in the `extra_counts` JSON column

**File:** [apps/backend/events/runner.py:120-135](../../apps/backend/events/runner.py#L120-L135)

```python
def _map_result(raw: dict) -> dict:
    ...
    for key, val in extra.items():
        extra_counts[key] = val   # includes event_ids list
```

The scraper result dict includes an `event_ids` key containing the list of primary keys for all saved events. `_map_result` puts every key from `extra` into `extra_counts`, including `event_ids`. `ScraperRun.extra_counts` is a `JSONField`. For a scraper that saves 1000 events, this stores a 1000-integer list in the DB row's JSON column, causing:

- Bloated `ScraperRun` rows
- Slow queries on the `ScraperRun` table (larger row pages)
- Serialization overhead on every read of the run record

**Fix:**

```python
def _map_result(raw: dict) -> dict:
    ...
    EXCLUDE_FROM_EXTRA = {"event_ids"}
    for key, val in extra.items():
        if key not in EXCLUDE_FROM_EXTRA:
            extra_counts[key] = val
    extra_counts["event_ids_count"] = len(extra.get("event_ids", []))
```

---

## BUG-3 · HIGH · `_unique_slug` has a TOCTOU race condition

**File:** [apps/backend/events/scrapers/base.py:344-350](../../apps/backend/events/scrapers/base.py#L344-L350)

```python
def _unique_slug(base: str, model_class, slug_field: str = "slug") -> str:
    slug = base
    counter = 1
    while model_class.objects.filter(**{slug_field: slug}).exists():
        slug = f"{base}-{counter}"
        counter += 1
    return slug
```

This is a classic check-then-act race. Between the `exists()` call and the subsequent `create()`, another concurrent scraper run (scrapers run as subprocesses and can save events in parallel) can insert the same slug, causing an `IntegrityError` that propagates as an unhandled exception and aborts the save.

**Fix:**

```python
import uuid
from django.db import IntegrityError

def _unique_slug(base: str, model_class, slug_field: str = "slug") -> str:
    for suffix in [None] + list(range(1, 10)) + [uuid.uuid4().hex[:8]]:
        candidate = base if suffix is None else f"{base}-{suffix}"
        try:
            # Attempt insert in a savepoint; if it violates unique, try next
            with transaction.atomic():
                if not model_class.objects.filter(**{slug_field: candidate}).exists():
                    return candidate
        except IntegrityError:
            continue
    return f"{base}-{uuid.uuid4().hex[:8]}"
```

Or, simpler: catch `IntegrityError` at the call site and retry with a UUID suffix.

---

## BUG-4 · HIGH · `api_scrapers()` uses PostgreSQL-specific `distinct("scraper_key")` — crashes on SQLite

**File:** [apps/backend/events/views.py:55](../../apps/backend/events/views.py#L55)

```python
qs = ScraperRun.objects.order_by("scraper_key", "-started_at").distinct("scraper_key")
```

`distinct()` with field names is a PostgreSQL extension. On SQLite (the default dev database) this raises:

```
django.db.utils.NotSupportedError: DISTINCT ON fields is not supported by this database backend
```

This means any developer using SQLite cannot open the scraper list view at all.

**Fix (database-agnostic):**

```python
from itertools import groupby

runs = ScraperRun.objects.order_by("scraper_key", "-started_at").values(
    "scraper_key", "status", "started_at", "finished_at", "events_found"
)
seen = {}
for run in runs:
    key = run["scraper_key"]
    if key not in seen:
        seen[key] = run
latest_runs = list(seen.values())
```

Or use a subquery:

```python
from django.db.models import Max, Subquery, OuterRef

latest_ids = ScraperRun.objects.filter(
    pk=Subquery(
        ScraperRun.objects.filter(scraper_key=OuterRef("scraper_key"))
        .order_by("-started_at")
        .values("pk")[:1]
    )
)
```

---

## BUG-5 · MEDIUM · `batch_categorize` ignores non-zero subprocess return code

**File:** [apps/backend/events/ai_categories.py:55-70](../../apps/backend/events/ai_categories.py#L55-L70)

```python
completed = subprocess.run(
    ["claude", "--model", "claude-haiku-4-5-20251001", "--output-format", "json", "-p", prompt],
    capture_output=True, text=True, timeout=120
)
# returncode is never checked
try:
    result = json.loads(completed.stdout)
    ...
except json.JSONDecodeError:
    ...
```

If the `claude` CLI exits with a non-zero code (rate limit, invalid model, API key error, network timeout), `completed.stdout` may be empty or contain an error message. The code then either silently parses empty JSON (returning `{}`) or hits the `JSONDecodeError` fallback. In either case, the event is assigned no categories and no error is surfaced to the caller or logged at a level that would trigger an alert.

**Fix:**

```python
if completed.returncode != 0:
    logger.error(
        "claude CLI failed (exit %d): %s",
        completed.returncode,
        completed.stderr[:500],
    )
    return {}
```

---

## BUG-6 · MEDIUM · `cancel_run` silently swallows `PermissionError`

**File:** [apps/backend/events/runner.py:105-115](../../apps/backend/events/runner.py#L105-L115)

```python
try:
    os.killpg(os.getpgid(pid), signal.SIGTERM)
except (ProcessLookupError, PermissionError):
    pass
```

`ProcessLookupError` (process already gone) is correctly ignored. `PermissionError`, however, means the signal was rejected — the process is still running but Django doesn't have permission to kill it. Silently passing leaves the scraper in a `RUNNING` state in the database with no mechanism to recover. The UI will show the run as cancelling indefinitely.

**Fix:**

```python
try:
    os.killpg(os.getpgid(pid), signal.SIGTERM)
except ProcessLookupError:
    pass  # Already exited
except PermissionError as exc:
    logger.error("Failed to cancel run %s (PID %s): %s", run_id, pid, exc)
    ScraperRun.objects.filter(pk=run_id).update(
        status=ScraperRun.STATUS_ERROR,
        error_message=f"Cancel failed: permission denied for PID {pid}",
    )
```

---

## BUG-7 · MEDIUM · `cancel_run` uses `os.killpg` — POSIX-only, crashes on Windows

**File:** [apps/backend/events/runner.py:103](../../apps/backend/events/runner.py#L103)

```python
os.killpg(os.getpgid(pid), signal.SIGTERM)
```

`os.killpg` and `os.getpgid` do not exist on Windows. Any developer attempting to cancel a scraper run on a Windows machine will hit `AttributeError: module 'os' has no attribute 'killpg'`.

The subprocess is spawned with `start_new_session=True` (which maps to `CREATE_NEW_PROCESS_GROUP` on Windows), so a platform-safe signal exists:

```python
import sys

if sys.platform == "win32":
    import ctypes
    ctypes.windll.kernel32.GenerateConsoleCtrlEvent(1, pid)  # CTRL_BREAK_EVENT to process group
else:
    os.killpg(os.getpgid(pid), signal.SIGTERM)
```

---

## BUG-8 · MEDIUM · `organizer_display_name` property triggers N+1 query

**File:** [apps/backend/events/models.py:185-190](../../apps/backend/events/models.py#L185-L190)

```python
@property
def organizer_display_name(self) -> str:
    if self.organizer_ref:
        return self.organizer_ref.name
    return self.organizer or ""
```

`self.organizer_ref` accesses the `ForeignKey` relationship, which issues a SQL query if `organizer_ref` is not prefetched. Any view or template that iterates a queryset of `Event` objects and calls `organizer_display_name` will fire one extra query per event.

**Fix:** Add `select_related("organizer_ref")` to all event querysets that use this property. Alternatively, annotate the queryset:

```python
from django.db.models import Coalesce, F
events = Event.objects.select_related("organizer_ref").annotate(
    display_name=Coalesce(F("organizer_ref__name"), F("organizer"))
)
```

---

## BUG-9 · MEDIUM · `_dedup_after_save` called with empty lists

**File:** [apps/backend/events/scrapers/base.py:470-475](../../apps/backend/events/scrapers/base.py#L470-L475)

```python
saved_ids, updated_ids = [], []
for item in events:
    ...
    if result == "saved":
        saved_ids.append(event.pk)

self._dedup_after_save(saved_ids, updated_ids)
```

When a scraper produces zero new events (e.g., a keyword search returns nothing, or all events already exist), `_dedup_after_save` is called with two empty lists. The dedup function then runs a queryset over a `pk__in=[]` clause, which is always empty — effectively a no-op that hits the database unnecessarily. While this is low risk, it adds latency on common "no new events" runs.

**Fix:**

```python
if saved_ids or updated_ids:
    self._dedup_after_save(saved_ids, updated_ids)
```

---

## BUG-10 · LOW · `venue_list` evaluates the queryset twice

**File:** [apps/backend/events/views.py:820-835](../../apps/backend/events/views.py#L820-L835)

```python
venues = Venue.objects.filter(...).order_by("name")
count = venues.count()        # first DB query
venues = venues[:page_size]   # re-sliced queryset
data = list(venues)           # second DB query
```

The `venues.count()` call hits the database, then the subsequent `list(venues)` slices and hits it again. This is two round-trips for one logical request. The count can be obtained from the result instead:

```python
venues = list(Venue.objects.filter(...).order_by("name")[:page_size + 1])
has_more = len(venues) > page_size
venues = venues[:page_size]
```

Or use `paginator = Paginator(qs, page_size)` which is smarter about when to count.

---

## BUG-11 · LOW · `psycopg2.extras.RealDictCursor` imported in tests — fails on SQLite

**File:** [apps/backend/events/tests.py:1180](../../apps/backend/events/tests.py#L1180)

```python
import psycopg2.extras
conn = psycopg2.connect(...)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
```

This code appears in the dedup integration tests. It imports and uses `psycopg2` directly, which:

1. Requires `psycopg2` to be installed even on SQLite development setups
2. Fails entirely when the test database is SQLite (no PostgreSQL connection string)

**Fix:** The dedup tests should use Django's test client or Django ORM directly, not a raw `psycopg2` connection. If the dedup script requires PostgreSQL-specific raw SQL, the test should be guarded:

```python
import django.test
from django.db import connection

@django.test.skipUnlessDBFeature("can_return_rows_from_bulk_insert")
class DedupIntegrationTest(django.test.TestCase):
    ...
```

---

## BUG-12 · LOW · Migration numbering has duplicate and conflicting entries

**File:** [apps/backend/events/migrations/](../../apps/backend/events/migrations/)

The migration directory contains:
- Two `0004_*` migrations
- Two `0010_*` migrations
- Three `0013_merge_*` migrations
- Two `0014_*` migrations

Django resolves these via merge migrations, so the schema is correct, but the history is messy. Running `python manage.py migrate --check` on a fresh database will succeed, but `python manage.py showmigrations` shows a confusing non-linear tree. New contributors may be confused about which migration to branch from.

**Recommendation:** After confirming all environments are in sync, squash the migration history:

```bash
python manage.py squashmigrations events 0001 0020
```
