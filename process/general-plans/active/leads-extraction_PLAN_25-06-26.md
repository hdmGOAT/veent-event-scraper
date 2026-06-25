# leads-extraction PLAN

**Type:** SIMPLE  
**Date:** 25-06-26  
**Branch:** development  
**Files changed:** 2 (`events/views.py`, `events/urls.py`)  
**Migration required:** No  
**New dependencies:** None

---

## 1. Overview

Add a read-only `GET /api/leads/` endpoint to `apps/backend/events/views.py` that
reshapes scraped event rows into the field layout used by the team's Google Sheets
leads tracker. Unlike `api_events`, which exposes raw model fields plus legacy
frontend fields, `api_leads` presents a clean, CRM-adjacent projection: one row per
event, covering organizer contact details (email/phone from `organizer_ref`), venue
location (city/country), a single canonical category, and the event/post dates. CRM
workflow columns (Status, Reached Out By, etc.) remain exclusively in Google Sheets;
this endpoint is the data-side only. The endpoint returns **only future events by
default** — events whose `starts_at` is greater than or equal to the current UTC
time at request time. Past events are permanently excluded; there is no opt-out
parameter for this filter. Filtering follows the same patterns already established in
`api_events`: `scraped_after` uses `parse_datetime` with a 400 fast-fail, `country`
uses `iexact` on `venue__country`, and pagination is clamped 1–500.

---

## 2. Files to Change

### `apps/backend/events/views.py`

Append a new function `api_leads(request)` after the existing `api_organizers_export`
function (line 442 in the current file is a safe insertion point — it is after the
last organizer-related view and before `api_organizer_detail`). No existing function
is modified.

Import additions required: none. All imports used by `api_leads`
(`parse_datetime`, `Paginator`, `JsonResponse`, `Q`, `timezone`) are already present
in the module header.

### `apps/backend/events/urls.py`

Add one line inside `urlpatterns`, after the `api/organizers/export/` entry and before
the `api/organizers/<slug:slug>/` entry, so more-specific organizer paths stay ordered
correctly. The leads path carries no slug or type converter, so ordering relative to
other `api/` paths does not matter beyond that.

```python
path("api/leads/", views.api_leads, name="api_leads"),
```

---

## 3. Implementation Spec

### 3.1 Function signature and entry guard

```python
def api_leads(request):
```

No decorator. The endpoint is GET-only; non-GET methods should return a 405.

At the top of the function, guard:

```python
if request.method != "GET":
    return JsonResponse({"error": "Method not allowed"}, status=405)
```

### 3.2 Query-parameter parsing

Parse all params at the top, before touching the ORM.

| Variable        | Source                                     | Type | Default | Constraints                                        |
|-----------------|--------------------------------------------|------|---------|----------------------------------------------------|
| `country`       | `request.GET.get("country", "")`           | str  | `""`    | strip()                                            |
| `source`        | `request.GET.get("source", "")`            | str  | `""`    | strip()                                            |
| `scraped_after` | `request.GET.get("scraped_after", "")`     | str  | `""`    | strip(); parse below                               |
| `has_contact`   | `request.GET.get("has_contact", "")`       | str  | `""`    | truthy when value == "1"                           |
| `min_days`      | `request.GET.get("min_days", 0)`           | int  | 0       | `max(0, int(...))`, ValueError → 0                 |
| `page`          | `request.GET.get("page", 1)`               | int  | 1       | `max(1, int(...))`, ValueError → 1                 |
| `limit`         | `request.GET.get("limit", 100)`            | int  | 100     | `max(1, min(int(...), 500))`, ValueError → 100     |

`scraped_after` parsing (identical to `api_events` pattern):

```python
scraped_after_ts = None
if scraped_after:
    from django.utils.dateparse import parse_datetime
    try:
        scraped_after_ts = parse_datetime(scraped_after)
    except (ValueError, TypeError):
        scraped_after_ts = None
    if scraped_after_ts is None:
        return JsonResponse({"error": "Invalid scraped_after timestamp"}, status=400)
```

`parse_datetime` is already imported in `api_events` via a local import; use the same
local import pattern here to remain consistent with the existing file style.

### 3.3 Base queryset

```python
events = (
    cutoff = timezone.now() + timedelta(days=min_days)  # min_days=0 → now (default)
    Event.objects
    .select_related("venue", "organizer_ref")
    .filter(starts_at__gte=cutoff)
    .order_by("starts_at")
)
```

Key decisions:

- `starts_at__gte=cutoff` uses `cutoff = timezone.now() + timedelta(days=min_days)`.
  When `min_days=0` (default) this is equivalent to `timezone.now()`. Events with
  `starts_at=NULL` are excluded by this filter (NULL comparisons in SQL are never true),
  which is the correct behaviour — an event with no known date cannot be confirmed as upcoming.
- Ordering is `starts_at` ascending (soonest-first) rather than `-scraped_at`. This
  matches the natural consumption pattern for a leads sheet: the most imminent events
  are most actionable.
- `search_query` is NOT joined — it is not needed for leads output and would waste a
  join. `organizer_ref` is needed for email/phone. `venue` is needed for city/country.

### 3.4 Filter chain (apply in order, after the base queryset)

```python
if country:
    events = events.filter(venue__country__iexact=country)

if source:
    events = events.filter(source=source)

if scraped_after_ts is not None:
    events = events.filter(scraped_at__gt=scraped_after_ts)

if has_contact == "1":
    events = events.filter(
        organizer_ref__isnull=False
    ).filter(
        Q(organizer_ref__email__gt="") | Q(organizer_ref__phone__gt="")
    )
```

Note on `country` filter: `venue__country__iexact` naturally excludes events that
have no venue FK set (NULL venue). This is the intended behaviour — events without a
venue have no country data and should not appear in a country-scoped query.

Note on `has_contact`: two separate `.filter()` calls are used deliberately. The
first ensures the FK is not NULL (guards the Q lookup from returning events whose
`organizer_ref` is NULL). The second applies the OR condition on the related fields.
Using a single `.filter(organizer_ref__isnull=False, ...)` with the Q object would
also be correct here, but the two-call pattern is more readable and consistent with
how similar guards appear elsewhere in the file.

### 3.5 Pagination

```python
paginator = Paginator(events, limit)
page_obj = paginator.get_page(page)
```

Identical to the `api_events` pattern. `get_page` clamps out-of-range page numbers
silently (returns last page for too-high values, first page for too-low values).

### 3.6 Row serialisation

Iterate over `page_obj` and build one dict per event. Every nullable field must use
an explicit `or None` guard or a conditional expression — never rely on Django
returning `None` implicitly for blank CharFields (blank CharFields return `""`).

```python
results = []
for e in page_obj:
    # Derive category: agent_categories[0] wins, then event.category, then null
    if e.agent_categories:
        category = e.agent_categories[0]
    elif e.category:
        category = e.category
    else:
        category = None

    # Organizer contact — only available when organizer_ref FK is resolved
    organizer_email = None
    organizer_phone = None
    organizer_facebook = None
    if e.organizer_ref_id:
        organizer_email = e.organizer_ref.email or None
        organizer_phone = e.organizer_ref.phone or None
        organizer_facebook = e.organizer_ref.facebook_url or None

    # Venue location — only available when venue FK is set
    location_city = None
    location_country = None
    if e.venue_id:
        location_city = e.venue.city or None
        location_country = e.venue.country or None

    results.append({
        "db_id":             e.id,
        "category":          category,
        "page_name":         e.organizer_display_name,
        "location_city":     location_city,
        "location_country":  location_country,
        "event":             e.name,
        "link":              e.url or None,
        "event_date":        e.starts_at.isoformat() if e.starts_at else None,
        "post_date":         e.post_date.isoformat() if e.post_date else None,
        "organizer_email":    organizer_email,
        "organizer_phone":    organizer_phone,
        "organizer_facebook": organizer_facebook,
        "platform":           e.source or None,
        "scraped_at":         e.scraped_at.isoformat() if e.scraped_at else None,
    })
```

Key derivation notes:

- `page_name` uses the model property `organizer_display_name`, which returns
  `organizer_ref.name` when the FK is set, else the `organizer` CharField fallback.
  This property is already defined on the `Event` model and is used by `api_events`.
- `e.organizer_ref_id` (not `e.organizer_ref`) is checked first to avoid hitting the
  DB for a NULL FK. The related object is already cached by `select_related` when the
  FK is non-NULL.
- `e.venue_id` is similarly checked before accessing `e.venue.city` to avoid
  attribute errors on a NULL FK.
- `e.url or None` converts the blank-string case to `null` in the JSON output.
  `e.source or None` does the same for source.
- `agent_categories` is a JSONField that stores a list. When the scraper has not yet
  run LLM classification, the field stores `[]` (empty list), not `null`. The
  truthiness check `if e.agent_categories:` correctly handles both `[]` and `null`
  (stored as `None` in Python).
- `event_date` will always be non-null in results because the base queryset requires
  `starts_at__gte=timezone.now()`, which excludes NULL `starts_at` rows. The
  conditional `if e.starts_at else None` is kept for defensive correctness.

### 3.7 Response shape

```python
return JsonResponse({
    "results": results,
    "total":   paginator.count,
    "pages":   paginator.num_pages,
    "page":    page_obj.number,
})
```

Identical envelope to `api_events` and `api_organizers`. This ensures the SvelteKit
frontend pagination helper (if ever wired up) can reuse the same response parser.

### 3.8 Complete function skeleton (pseudocode summary)

```text
def api_leads(request):
    if request.method != "GET":
        return 405

    parse: country, source, scraped_after, has_contact, min_days, page, limit
    if scraped_after present and not parseable → return 400

    cutoff = now() + timedelta(days=min_days)   # min_days=0 → now (default behaviour)
    events = Event.objects
        .select_related("venue", "organizer_ref")
        .filter(starts_at__gte=cutoff)
        .order_by("starts_at")                   # soonest first

    if country      → filter(venue__country__iexact=country)
    if source       → filter(source=source)
    if scraped_after_ts → filter(scraped_at__gt=scraped_after_ts)
    if has_contact == "1" → filter(organizer_ref__isnull=False)
                             .filter(Q(email__gt="") | Q(phone__gt=""))

    paginator = Paginator(events, limit)
    page_obj = paginator.get_page(page)

    results = [serialize each event as leads row]   # 14 fields incl. organizer_facebook

    return JsonResponse({results, total, pages, page: page_obj.number})
```

---

## 4. Verification

Replace `localhost:8000` with the actual dev server address if different.

### 4.1 Baseline — no filters, confirm future-only results

```bash
curl -s "http://localhost:8000/api/leads/" | python3 -m json.tool | head -60
```

Expected: `{"results": [...], "total": <int>, "pages": <int>, "page": 1}`. Each
result object must contain exactly 14 keys defined in Section 3.6. Then confirm
all `event_date` values are in the future:

```bash
curl -s "http://localhost:8000/api/leads/" | python3 -c "
import sys, json
from datetime import datetime, timezone
now = datetime.now(timezone.utc)
d = json.load(sys.stdin)
past = [r for r in d['results'] if r['event_date'] and r['event_date'] < now.isoformat()]
print('PAST ROWS (must be 0):', len(past))
"
```

Expected: `PAST ROWS (must be 0): 0`.

### 4.2 Country filter

```bash
curl -s "http://localhost:8000/api/leads/?country=Philippines" | python3 -c "import sys,json; d=json.load(sys.stdin); print(set(r['location_country'] for r in d['results']))"
```

Expected output: `{'Philippines'}` (or empty set if no upcoming PH events with venue
in DB). No result should have `location_country` other than `"Philippines"`.

### 4.3 Source filter

```bash
curl -s "http://localhost:8000/api/leads/?source=facebook_posts" | python3 -c "import sys,json; d=json.load(sys.stdin); print(set(r['platform'] for r in d['results']))"
```

Expected output: `{'facebook_posts'}`.

### 4.4 scraped_after — valid timestamp

```bash
curl -s "http://localhost:8000/api/leads/?scraped_after=2026-06-01T00:00:00Z" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['total'])"
```

Expected: integer count. All returned `scraped_at` values must be after
`2026-06-01T00:00:00Z`.

### 4.5 scraped_after — invalid timestamp → 400

```bash
curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/api/leads/?scraped_after=not-a-date"
```

Expected: `400`.

### 4.6 has_contact filter

```bash
curl -s "http://localhost:8000/api/leads/?has_contact=1" | python3 -c "import sys,json; d=json.load(sys.stdin); bad=[r for r in d['results'] if not r['organizer_email'] and not r['organizer_phone']]; print('BAD ROWS:', len(bad))"
```

Expected: `BAD ROWS: 0`. Every result must have a non-null `organizer_email` or
`organizer_phone`.

### 4.7 Pagination

```bash
curl -s "http://localhost:8000/api/leads/?limit=5&page=2" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['results']), d['page'])"
```

Expected: `5 2` (or fewer results if total < 10).

### 4.8 Method guard

```bash
curl -s -X POST -o /dev/null -w "%{http_code}" "http://localhost:8000/api/leads/"
```

Expected: `403`. Django's CSRF middleware intercepts the unauthenticated,
token-less POST before the view body runs, so the request is rejected with 403
rather than reaching the `request.method != "GET"` guard (which would otherwise
return 405). This is consistent with the existing read-only GET views in this
file (`api_events`, `api_organizers`, `api_organizers_export`), all of which
return 403 on POST for the same reason.

### 4.9 Combined filters

```bash
curl -s "http://localhost:8000/api/leads/?country=Philippines&source=facebook_posts&limit=10" | python3 -m json.tool
```

Expected: results that satisfy both filters simultaneously and all have future
`event_date` values.

---

## 5. Done When

1. `GET /api/leads/` responds with HTTP 200 and a JSON envelope matching
   `{"results": [...], "total": int, "pages": int, "page": int}`.
2. Each result object contains exactly 14 keys: `db_id`, `category`, `page_name`,
   `location_city`, `location_country`, `event`, `link`, `event_date`, `post_date`,
   `organizer_email`, `organizer_phone`, `organizer_facebook`, `platform`, `scraped_at`.
3. Every result has `event_date >= now` — no past events are ever returned. This is
   unconditional; no query param can override it.
4. `?country=` returns only events whose `venue.country` case-insensitively matches.
5. `?source=` returns only events with that exact `source` value.
6. `?scraped_after=<invalid>` returns HTTP 400 with `{"error": "Invalid scraped_after timestamp"}`.
7. `?scraped_after=<valid ISO 8601>` returns only events scraped after that timestamp.
8. `?has_contact=1` returns only events where `organizer_ref` is non-null AND has a
   non-blank email or phone. Every result row has at least one of `organizer_email`
   or `organizer_phone` non-null.
9. `?limit=` and `?page=` paginate correctly; `limit` is clamped to 1–500.
10. Non-GET requests return HTTP 403 (CSRF middleware rejects the token-less POST
    before the view body's 405 guard runs — consistent with all other read-only
    GET views in this file).
11. No migration was run, no new model was created, no new Python package was
    installed.

---

## Known Data Gaps (not code issues)

- `organizer_email` and `organizer_phone` are null for the majority of events because
  `organizer_ref` FK is only populated after the organizer deduplication/resolution
  step runs. Events scraped but not yet linked will show null contact fields.
- `location_city` and `location_country` are sparse for Facebook Posts source events
  because venue extraction depends on LLM pipeline output. Low fill rate is expected
  for recently scraped rows.
- `agent_categories` is `[]` on freshly scraped rows until the `categorize-events`
  script runs; these rows will fall back to `event.category` (or null if
  `event.category` is also blank).
- Events with no `starts_at` value are excluded by the future-only filter regardless
  of any other field values. This is intentional.

---

## Touchpoints

- `apps/backend/events/views.py` — `api_leads` function added
- `apps/backend/events/urls.py` — one `path()` entry added

## Public Contracts

- `GET /api/leads/` → `{"results": [...], "total": int, "pages": int, "page": int}`
- Always returns future events only (`starts_at >= now`). No override available.
- Default ordering: `starts_at` ascending (soonest first).
- Query params: `country`, `source`, `scraped_after`, `has_contact`, `min_days`, `page`, `limit`
- Error responses: `{"error": "<message>"}` with appropriate HTTP status code

## Blast Radius

- No existing view or URL is modified
- No model changes
- No migration
- No other endpoint or frontend route is touched
- The only risk is a name collision in `urlpatterns` if a future `api/leads/`-prefixed
  path is added without awareness of this route; not applicable today

## Verification Evidence

All curl commands in Section 4 must pass before marking DONE. Specifically:
- 4.1 second command must print `PAST ROWS (must be 0): 0`
- 4.5 must return HTTP 400 (not 500)
- 4.6 must print `BAD ROWS: 0`
- 4.8 must return HTTP 403 (CSRF rejection, consistent with sibling GET views)

## Resume and Execution Handoff

Execute agent must:
1. Open `apps/backend/events/views.py`
2. Append the `api_leads` function as specified in Section 3 (after `api_organizers_export`, before `api_organizer_detail`)
3. Open `apps/backend/events/urls.py`
4. Insert `path("api/leads/", views.api_leads, name="api_leads"),` after the `api/organizers/export/` line (currently line 24)
5. Run the verification curl commands from Section 4 against the running dev server
6. Report results per Section 5 acceptance criteria
