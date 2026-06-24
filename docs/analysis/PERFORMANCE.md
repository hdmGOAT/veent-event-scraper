# Performance Analysis

> Scope: `apps/backend/` — query efficiency, memory usage, CPU hotspots, and scaling concerns

---

## PERF-1 · HIGH · `_resolve_organizer` O(n) Python scan on every `save_events` call

**File:** [apps/backend/events/scrapers/base.py:410-420](../../apps/backend/events/scrapers/base.py#L410-L420)

```python
for org in Organizer.objects.filter(website__gt=""):
    if org.website and _norm(data.get("website", "")) == _norm(org.website):
        return org
```

Every time a scraper saves a batch of events, `_resolve_organizer` is called once per event. Each call fetches every organizer with a non-empty website and iterates them in Python. This is an O(n_organizers × n_events) operation per scraper run.

**Measured impact estimate:**
- 100 organizers × 200 events saved = 20,000 Python comparisons + 200 SQL fetches of 100 rows each
- At 1ms per query round-trip = 200ms added latency per 200-event batch, growing as the organizer count grows

**Fix:** Store a normalized website field and use an indexed lookup. See [BUG-1](BUGS.md#bug-1--high--_resolve_organizer-performs-a-full-table-scan-on-every-save) for the implementation pattern.

---

## PERF-2 · HIGH · `api_events_by_category` loads all events into Python memory for aggregation

**File:** [apps/backend/events/views.py:350-375](../../apps/backend/events/views.py#L350-L375)

```python
events = Event.objects.filter(is_active=True).values("agent_categories")
counts = {}
for event in events:
    cats = event["agent_categories"] or []
    for cat in cats:
        counts[cat] = counts.get(cat, 0) + 1
```

This loads `agent_categories` (a `JSONField` containing a list of strings) for every active event in the database into Python, then iterates all of them to build a count. As the event table grows this becomes slower:

| Events | Approx memory | Approx time |
|---|---|---|
| 10,000 | ~2 MB | ~50ms |
| 100,000 | ~20 MB | ~500ms |
| 1,000,000 | ~200 MB | ~5s |

**Fix — PostgreSQL JSON aggregation:**

```python
from django.db.models import Count
from django.db.models.expressions import Func

# PostgreSQL only — use jsonb_array_elements_text to unnest
if connection.vendor == "postgresql":
    result = Event.objects.filter(is_active=True).extra(
        select={"category": "jsonb_array_elements_text(agent_categories)"}
    ).values("category").annotate(count=Count("id"))
    counts = {row["category"]: row["count"] for row in result}
else:
    # SQLite fallback — acceptable at dev scale
    events = Event.objects.filter(is_active=True).values_list("agent_categories", flat=True)
    counts = {}
    for cats in events:
        for cat in (cats or []):
            counts[cat] = counts.get(cat, 0) + 1
```

**Alternative (no raw SQL):** Cache the category counts in a `ScraperRun`-keyed cache entry and rebuild it only after a scraper run completes, rather than recomputing on every API request.

---

## PERF-3 · MEDIUM · `_unique_slug` issues N sequential queries for N slug conflicts

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

For a base slug with K existing collisions, this fires K+1 sequential queries. This is typically negligible, but when importing a large event set with many collisions on common names (e.g., "Community Meetup"), it can add meaningful latency.

**Fix:** Fetch all existing collisions in one query:

```python
def _unique_slug(base: str, model_class, slug_field: str = "slug") -> str:
    existing = set(
        model_class.objects.filter(
            **{f"{slug_field}__regex": rf"^{re.escape(base)}(-\d+)?$"}
        ).values_list(slug_field, flat=True)
    )
    if base not in existing:
        return base
    counter = 1
    while f"{base}-{counter}" in existing:
        counter += 1
    return f"{base}-{counter}"
```

---

## PERF-4 · MEDIUM · `api_events_by_category` is called on every request with no caching

**File:** [apps/backend/events/views.py:350-375](../../apps/backend/events/views.py#L350-L375)

The category count endpoint is presumably polled by the frontend on page load or on interval. It performs a full table scan every time (see PERF-2). The result is essentially static between scraper runs — category counts change only when events are saved.

**Fix:** Cache with Django's cache framework, invalidated after each scraper run:

```python
from django.core.cache import cache

CATEGORY_CACHE_KEY = "events:category_counts"
CATEGORY_CACHE_TTL = 300  # 5 minutes

def api_events_by_category(request):
    counts = cache.get(CATEGORY_CACHE_KEY)
    if counts is None:
        counts = _compute_category_counts()
        cache.set(CATEGORY_CACHE_KEY, counts, CATEGORY_CACHE_TTL)
    return JsonResponse(counts)

# In runner.py after a scraper run completes:
cache.delete(CATEGORY_CACHE_KEY)
```

---

## PERF-5 · MEDIUM · CSV export has no upper bound on row count

**File:** [apps/backend/events/views.py:900-930](../../apps/backend/events/views.py#L900-L930)

```python
events = Event.objects.filter(**filters).select_related("venue")
writer.writerows(...)
```

The CSV export queries all matching events with no `LIMIT`. For a broad filter (or no filter), this can return tens of thousands of rows, loading all of them into memory and streaming a very large response. On a production server with limited RAM, a single wide export can exhaust memory.

**Fix:**

```python
MAX_CSV_ROWS = 10_000

events = Event.objects.filter(**filters).select_related("venue")[:MAX_CSV_ROWS]
```

Or use `iterator()` with chunked streaming to avoid loading all rows at once:

```python
response = StreamingHttpResponse(
    _csv_generator(Event.objects.filter(**filters).select_related("venue").iterator(chunk_size=500)),
    content_type="text/csv",
)
```

---

## PERF-6 · MEDIUM · `_dedup_after_save` runs inline within each scraper's subprocess, adding latency to every run

**File:** [apps/backend/events/scrapers/base.py:480-530](../../apps/backend/events/scrapers/base.py#L480-L530)

Deduplication runs synchronously inside the scraper subprocess after saving events. For a large batch it can add several seconds to each run. More importantly, the dedup logic acquires a database-level lock (or relies on the process-local `_DEDUP_LOCK`) and does multi-step queries.

**Recommendation:** Move dedup to a post-run async job (Celery task or Django Q) triggered after the subprocess exits. This makes each scraper run return faster and decouples dedup failures from scrape failures.

If a task queue is not yet available, at minimum defer dedup until after the scraper reports results:

```python
# In runner.py after subprocess exits:
if run.status == ScraperRun.STATUS_SUCCESS and run.events_found > 0:
    trigger_dedup_async(run.pk)
```

---

## PERF-7 · LOW · Proxy election downloads up to 6 proxy list URLs before every scraper that uses free proxies

**File:** [apps/backend/events/scrapers/proxy_manager.py:87-123](../../apps/backend/events/scrapers/proxy_manager.py#L87-L123)

When `_cached_session` is `None` (after a proxy rotation or first call), `get_proxy_session()` downloads all 6 proxy list URLs in parallel, then tests up to all candidates. This is correct but can take 30–60 seconds in practice. The session is cached at the module level, which means:

- Every new subprocess (each scraper run) starts with no cache and must re-elect
- Multiple concurrent scraper runs each independently elect a proxy

**Fix:** Persist the elected proxy to a shared file or database key so child processes can reuse the last working proxy without re-electing from scratch:

```python
# After election in the parent process, write to DB:
Settings.objects.update_or_create(key="proxy_elected", defaults={"value": winner})

# Child process reads before starting election:
cached = Settings.objects.filter(key="proxy_elected").values_list("value", flat=True).first()
if cached and _test_proxy(cached):
    return _build_session(cached)
# Fall through to full election
```

---

## PERF-8 · LOW · `ScraperRun.log_output` grows unboundedly per run

**File:** [apps/backend/events/management/commands/run_scraper_job.py:85-100](../../apps/backend/events/management/commands/run_scraper_job.py#L85-L100)

```python
_MAX_TOTAL_LINES = 2000
```

The `_DBLogHandler` caps log lines at 2000 per run. At typical log verbosity (DEBUG level with Playwright output) a 2000-line cap is often reached within the first few keywords. Later log output is silently dropped. The cap prevents unbounded DB growth but the silent truncation makes debugging long runs harder.

**Fix:** Log a final entry when the cap is hit:

```python
if len(self._lines) >= _MAX_TOTAL_LINES:
    if not self._truncated:
        self._lines.append(f"[LOG TRUNCATED at {_MAX_TOTAL_LINES} lines]")
        self._truncated = True
    return
```
