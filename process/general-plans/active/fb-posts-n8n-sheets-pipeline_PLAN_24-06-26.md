# FB Posts → n8n → Google Sheets Pipeline

**Date**: 24-06-26
**Complexity**: COMPLEX (standard — one execution stream, 3 sequential RFCs)
**Status**: ⏳ PLANNED

---

## Overview

Enable the full n8n automation pipeline: trigger the `facebook_posts` scraper via HTTP, wait for
completion, pull newly scraped posts from a dedicated API response, and write every row to a Google
Sheet. Three backend changes are required before n8n can be wired up:

1. **Model migration** — add `raw_text` (the original FB caption) and `post_date` (when the post
   was published on Facebook) to the `Event` table.
2. **Scraper update** — capture both fields from the DOM inside `_EXTRACT_POSTS_JS` and persist
   them through `ScrapedEvent` → `save_events`.
3. **API expansion** — expose all 11 Google Sheets columns in the `/api/events/` response and add
   a `scraped_after` filter so n8n can pull only rows created in the current run.

The Ollama processing pipeline already exists and already uses the raw caption as the only source
of truth. No LLM wiring changes are needed.

---

## Quick Links

- [Phase Completion Rules](#phase-completion-rules)
- [Execution Brief](#execution-brief)
- [Phased Execution Workflow](#phased-execution-workflow)
- [Non-Goals](#non-goals)
- [Architecture Decisions](#architecture-decisions)
- [Data Flow](#data-flow)
- [Phased Delivery Plan](#phased-delivery-plan)
- [RFCs](#rfcs)
- [n8n Wiring Guide](#n8n-wiring-guide)
- [Touchpoints](#touchpoints)
- [Public Contracts](#public-contracts)
- [Blast Radius](#blast-radius)
- [Verification Evidence](#verification-evidence)
- [Resume and Execution Handoff](#resume-and-execution-handoff)

---

## Phase Completion Rules

A phase is NOT complete until:

1. **Integration Test** — Works with the surrounding system (migration applied + scraper runs + API returns data).
2. **Manual Test** — Developer can perform the action end-to-end (curl, Django shell, or n8n test call).
3. **Data Verification** — DB query confirms the expected row state.
4. **Error Handling** — Failure cases handled gracefully (null datetime, missing caption, bad filter param).
5. **User Confirmation** — User says "it works."

Status meanings:
- ⏳ PLANNED — Not started
- 🔨 CODE DONE — Written but not E2E tested
- 🧪 TESTING — Currently being tested
- ✅ VERIFIED — Tested AND confirmed working
- 🚧 BLOCKED — Has issues

After each RFC, document:
- [ ] What was tested manually
- [ ] Data verified in DB (show query + result)
- [ ] Errors encountered and fixed
- [ ] User confirmation received

---

## Execution Brief

### RFC-001: Model + Migration
**What happens:** Two new nullable columns are added to the `events_event` table via Django
migration `0023`. No scraper or API behaviour changes yet.

**Integration points:** `models.py` → migration file → Neon Postgres.

**Test:** Apply migration, run `SELECT id, raw_text, post_date FROM events_event LIMIT 1;` — both
columns exist, both NULL for existing rows.

**Verify:** `manage.py showmigrations events` shows `0023` applied.

**Done when:** Migration is green, existing test suite still passes (97 tests).

---

### RFC-002: Scraper Capture
**What happens:** `_EXTRACT_POSTS_JS` is extended to extract `post_date_raw` from the post card's
`time[datetime]` attribute. `ScrapedEvent` gains `raw_text` and `post_date` fields. `save_events`
in `base.py` writes both to the Event row. The `run()` loop in `facebook_posts.py` passes
`raw_caption` and parsed `post_date` through.

**Integration points:** JS extraction → Python `raw` dict → `ScrapedEvent` → `save_events` → DB row.

**Test:** Run `manage.py scrape facebook_posts` against one active search query. Query DB:
```sql
SELECT id, url, raw_text IS NOT NULL AS has_raw, post_date
FROM events_event WHERE source = 'facebook_posts'
ORDER BY scraped_at DESC LIMIT 5;
```

**Verify:** `has_raw = true` for freshly scraped rows. `post_date` is a valid timestamp for posts
that have a `time[datetime]` element, NULL for posts where FB omits the timestamp.

**Done when:** At least 3 of 5 most-recent facebook_posts rows have `raw_text` populated.

---

### RFC-003: API Expansion
**What happens:** `api_events()` in `views.py` exposes the following fields per event:
`db_id`, `scraped_at`, `search_term`, `event`, `organizer_name`, `category`, `location`,
`post_link`, `fb_post_id`, `post_date`, `event_date`, `summary`, `slug`, `name`, `starts_at`,
`ends_at`, `agent_categories`, `source`, `price`, `venue`, `venue_slug`, `organizer`,
`organizer_slug`, `url`. A `scraped_after` query param (`?scraped_after=<ISO 8601>`) filters
results to rows scraped after that timestamp — returns 400 on invalid input. `search_query__query`
is added via `select_related` on `search_query`.

**Integration points:** `views.py` → frontend (no breaking changes — new fields are additive) → n8n
HTTP Request node.

**Test:**
```http
GET /api/events/?source=facebook_posts&ordering=-scraped_at&limit=5
GET /api/events/?source=facebook_posts&scraped_after=2026-06-24T00:00:00Z
```

**Verify:** Response includes `db_id`, `scraped_at`, `search_term`, `organizer_name`, `category`,
`location`, `post_link`, `fb_post_id`, `post_date`, `event_date`, `summary` for every item.
Malformed `scraped_after` returns HTTP 400.

**Done when:** curl returns all 11 fields and `scraped_after` correctly filters rows.

---

### Expected Outcome

- `events_event` table has `raw_text` and `post_date` columns.
- Every new `facebook_posts` scrape populates both (where FB provides the data).
- `/api/events/?source=facebook_posts&scraped_after=<ts>` returns the exact row set n8n needs.
- n8n can: trigger scraper → poll run to completion → fetch new rows → append to Google Sheets.

---

## Phased Execution Workflow

This plan uses a phase-by-phase execution model with built-in approval gates.

### Phase Workflow Pattern

**Step 1: Pre-Phase Research** — Read relevant code, identify blockers, present findings. STOP and wait for approval before Step 2.

**Step 2: Detailed Planning** — Specify exact files and lines. Get approval.

**Step 3: Implementation** — Execute as approved. No deviations.

**Step 4: Testing & Verification** — Run the verification steps from the RFC.

**Step 5: User Confirmation** — Present a post-phase summary; user approves before next RFC begins.

### Example Phase Execution

```
User: "Begin RFC-001"

Assistant (Pre-Phase Research):
- Reading apps/backend/events/models.py — Event model has 22 fields, last migration is 0022.
- Two new fields needed: raw_text (TextField blank=True) and post_date (DateTimeField null=True).
- No index needed on raw_text (full-text search not planned).
- post_date could usefully be indexed for date-range queries; proposing db_index=True.
- Proceed with this approach?

User: "Yes"

Assistant (Implementation):
[Edits models.py, runs makemigrations, reviews generated SQL]

Assistant (Testing):
✓ manage.py migrate — applied 0023_add_raw_text_post_date cleanly
✓ manage.py test events — 97 tests pass
✓ SELECT raw_text, post_date FROM events_event LIMIT 1 — columns exist, NULL for old rows

RFC-001 complete. Proceed to RFC-002?
```

---

## Non-Goals

- No changes to the Ollama prompt or structuring logic.
- No new search query management.
- No frontend (SvelteKit) changes.
- No authentication added to existing endpoints (same security posture as today).
- No backfill of `raw_text` / `post_date` for rows already in the DB.
- No Google Sheets API integration in the backend (n8n handles that).

---

## Architecture Decisions

### AD-001: Store raw_text on Event, not a separate table

**Decision:** Add `raw_text` directly to `events_event` rather than a `post_raw_text` join table.

**Rationale:** One query, no join, matches the flat row shape n8n consumes. Raw text is 1:1 with
each event. The column is blank-able so the migration is zero-downtime on existing rows.

### AD-002: post_date via DOM time[datetime], not LLM

**Decision:** Extract post publish date from `<time datetime="...">` attributes in the JS DOM
extractor, not from the LLM-structured output.

**Rationale:** The `time[datetime]` attribute is an ISO 8601 string directly from FB's markup —
reliable and no hallucination risk. The LLM extracts `start_datetime` (the event date, potentially
weeks in the future), which is a different concept from when the post was published.

### AD-003: Extend ScrapedEvent dataclass, not a side-channel dict

**Decision:** Add `raw_text` and `post_date` as proper fields on `ScrapedEvent` and update
`save_events` to persist them.

**Rationale:** Keeps all scraper output typed and discoverable. `save_events` is the single
persistence point for all scrapers; adding fields there means future scrapers can also populate them.

### AD-004: scraped_after filter via query param on existing endpoint

**Decision:** Add `?scraped_after=<ISO 8601>` to the existing `/api/events/` endpoint, not a
new dedicated endpoint.

**Rationale:** Minimal surface area. The existing endpoint already supports `source=facebook_posts`
filtering. n8n stores the run's start timestamp and passes it as `scraped_after` on the next call.

---

## Data Flow

```
n8n Schedule Trigger
      ↓
POST /api/scrapers/facebook_posts/run/
      ↓ { id: <run_id>, status: "queued" }
      ↓
Loop every 30s:
  GET /api/scrapers/runs/<run_id>/
      ↓ { status: "completed" | "failed" }
      ↓
GET /api/events/?source=facebook_posts
                &scraped_after=<run_start_ts>
                &ordering=-scraped_at
      ↓ { results: [ { id, scraped_at, search_term, organizer_name,
                        category, location, post_link, fb_post_id,
                        post_date, summary, raw_text }, ... ] }
      ↓
[Code node] map fields to sheet columns
      ↓
Google Sheets — Append rows
```

---

## Phased Delivery Plan

| RFC | Scope | Status | Depends On |
|-----|-------|--------|------------|
| RFC-001 | Model fields + migration | ⏳ PLANNED | — |
| RFC-002 | Scraper capture | ⏳ PLANNED | RFC-001 |
| RFC-003 | API expansion | ⏳ PLANNED | RFC-001 |

---

## RFCs

---

### RFC-001: Event Model Extension (raw_text + post_date)

**Summary:** Add two new columns to the `Event` model and generate the Django migration.

**Context consulted:** `process/context/all-context.md` (architecture, Django conventions, migration patterns).

**Dependencies:** None.

**Files touched:**
- `apps/backend/events/models.py`
- `apps/backend/events/migrations/0023_add_raw_text_post_date.py` (generated)

---

#### Stage 0: Pre-Phase Research

1. Read `apps/backend/events/models.py` — confirm Event field list and last migration number.
2. Confirm latest migration: `manage.py showmigrations events | tail -5`.
3. Verify no pending unmigrated changes: `manage.py makemigrations --check --dry-run`.
4. Present findings (field list, migration number) and proposed additions before proceeding.

#### Stage 1: Add Fields to models.py

Add to `class Event(models.Model)` after the `scraped_at` field:

```python
# Raw FB post caption captured at scrape time — source of truth for Ollama processing.
raw_text = models.TextField(blank=True, default="")
# Timestamp when the FB post was published (from <time datetime="..."> in DOM).
# Null when FB does not expose the datetime attribute (e.g. older posts).
post_date = models.DateTimeField(null=True, blank=True, db_index=True)
```

#### Stage 2: Generate and Review Migration

```bash
cd apps/backend
./venv/bin/python manage.py makemigrations events --name add_raw_text_post_date
```

Review generated SQL before applying:
```bash
./venv/bin/python manage.py sqlmigrate events 0023
```

Expected: two `ALTER TABLE "events_event" ADD COLUMN` statements — one `text DEFAULT ''` (NOT NULL), one `timestamp with time zone NULL`.

#### Stage 3: Apply Migration

```bash
./venv/bin/python manage.py migrate
./venv/bin/python manage.py showmigrations events | tail -5
```

#### Post-Phase Testing

```bash
# All 97 tests still pass
cd apps/backend && ./venv/bin/python manage.py test events -v 1

# Columns exist in DB
./venv/bin/python manage.py shell -c "
from events.models import Event
e = Event.objects.first()
print(getattr(e, 'raw_text', 'MISSING'))
print(getattr(e, 'post_date', 'MISSING'))
"
```

#### Verification Checklist

- [ ] Migration `0023` appears in `showmigrations` as `[X]`
- [ ] `manage.py test events` — all 97 tests pass
- [ ] `Event.objects.first().raw_text` returns `""` (not AttributeError)
- [ ] `Event.objects.first().post_date` returns `None` (not AttributeError)
- [ ] `manage.py makemigrations --check --dry-run` exits cleanly (no pending changes)

**What's Functional Now:** DB schema ready; scraper and API still unaware of new fields.

**Ready For:** RFC-002 and RFC-003 (can proceed in parallel after RFC-001 is ✅ VERIFIED).

---

### RFC-002: Scraper Capture (raw_text + post_date)

**Summary:** Extend the JS DOM extractor to capture the post publish timestamp, thread `raw_text`
and `post_date` through `ScrapedEvent`, and update `save_events` to write both to the DB.

**Dependencies:** RFC-001 ✅ VERIFIED.

**Files touched:**
- `apps/backend/events/scrapers/facebook_posts.py`
- `apps/backend/events/scrapers/base.py`

---

#### Stage 0: Pre-Phase Research

1. Read `apps/backend/events/scrapers/base.py` — confirm `ScrapedEvent` dataclass fields and `save_events` signature.
2. Read `_EXTRACT_POSTS_JS` in `facebook_posts.py` — confirm current `posts.push({...})` shape.
3. Read the `run()` method loop (lines ~1016-1082) — trace how `raw` dict fields map to `ScrapedEvent`.
4. Present exact lines to change before proceeding.

#### Stage 1: Extend _EXTRACT_POSTS_JS

Inside `_EXTRACT_POSTS_JS`, in the `posts.push({...})` block, add:

```js
// Capture post publish timestamp from the time[datetime] attribute.
// Returns null when FB omits the attribute (older posts, search results).
post_date_raw: (() => {
    const t = card.querySelector('time[datetime]');
    return t ? t.getAttribute('datetime') : null;
})(),
```

Full updated push becomes:
```js
posts.push({
    post_url:       href,
    author_name:    findAuthorName(card),
    raw_caption:    rawCaption.substring(0, 2000),
    raw_links:      findRegistrationLinks(card, rawCaption),
    post_date_raw:  (() => {
        const t = card.querySelector('time[datetime]');
        return t ? t.getAttribute('datetime') : null;
    })(),
});
```

#### Stage 2: Extend ScrapedEvent Dataclass

In `apps/backend/events/scrapers/base.py`, add two new fields to `ScrapedEvent`:

```python
@dataclasses.dataclass
class ScrapedEvent:
    # ... existing fields ...
    raw_text: str = ""
    post_date: datetime | None = None
```

(Use `from datetime import datetime` — already imported in base.py.)

#### Stage 3: Update save_events to Persist New Fields

In `save_events` in `base.py`, in the `Event` upsert/create block, add:

```python
# Persist raw caption and post publish date when provided.
if event.raw_text:
    defaults["raw_text"] = event.raw_text
if event.post_date is not None:
    defaults["post_date"] = event.post_date
```

**Note:** Only overwrite if non-empty/non-None so existing records scraped by other scrapers
are not accidentally cleared.

#### Stage 4: Thread Fields Through facebook_posts.py run()

In the `run()` method loop, after `caption = raw.get("raw_caption", "")`:

```python
post_date_raw = raw.get("post_date_raw")
post_date     = _parse_post_date(post_date_raw) if post_date_raw else None
```

In `scraped_events.append(ScrapedEvent(...))`:

```python
scraped_events.append(ScrapedEvent(
    name=title,
    description=fields.get("short_description") or caption[:500],
    starts_at=_parse_post_date(fields.get("start_datetime")),
    url=post_url,
    registration_url=registration_url,
    external_id=external_id,
    source_url=sq.query,
    organizer=organizer_name,
    venue=venue,
    raw_text=caption,          # ← new
    post_date=post_date,       # ← new
))
```

#### Post-Phase Testing

```bash
# Trigger one scrape manually (ensure active search queries exist)
cd apps/backend && ./venv/bin/python manage.py scrape facebook_posts

# Check results in DB shell
./venv/bin/python manage.py shell -c "
from events.models import Event
qs = Event.objects.filter(source='facebook_posts').order_by('-scraped_at')[:5]
for e in qs:
    print(e.id, bool(e.raw_text), e.post_date, e.url[:50])
"
```

Expected output: at least 3 rows with `True` for `raw_text`, and a mix of datetime / None for `post_date`.

#### Verification Checklist

- [ ] `_EXTRACT_POSTS_JS` includes `post_date_raw` in posts.push
- [ ] `ScrapedEvent` dataclass has `raw_text` and `post_date` fields
- [ ] `save_events` writes both fields on upsert
- [ ] `facebook_posts.py` passes `raw_caption` as `raw_text` and parsed `post_date`
- [ ] After a scrape run, freshly created Event rows have `raw_text` != `""`
- [ ] `post_date` is a valid datetime for posts where FB exposes `time[datetime]`
- [ ] Existing 97 tests still pass (run `manage.py test events`)

**What's Functional Now:** New scrape runs populate `raw_text` and `post_date`.

**Ready For:** RFC-003.

---

### RFC-003: API Expansion (all 11 columns + scraped_after filter)

> **Note (2026-06-25):** The 3 organizer/raw_text fields (`organizer_email`, `organizer_phone`, `raw_text`) and the `scraped_after` filter were partially delivered by PR #52 (`feat/async-n8n-events-sheets-sync` — see `process/general-plans/completed/completed_async-n8n-leads-sheets-sync_PLAN_25-06-26.md`). Verify current `api_events()` shape before implementing this RFC to avoid double-adds.

**Summary:** Update `api_events()` in `views.py` to return all 11 Google Sheets columns.
Add `?scraped_after=<ISO 8601>` for incremental n8n sync. Add `select_related("search_query")`
to avoid N+1 on the new `search_term` field.

**Dependencies:** RFC-001 ✅ VERIFIED.

**Files touched:**
- `apps/backend/events/views.py`

---

#### Stage 0: Pre-Phase Research

1. Read `api_events()` in `views.py` (lines ~297–352) — confirm current queryset, filter params, and response dict shape.
2. Confirm `select_related` already includes `"venue"` and `"organizer_ref"` — need to add `"search_query"`.
3. Check existing `ordering` and `page` params — confirm `scraped_after` won't conflict.
4. Present exact diff before proceeding.

#### Stage 1: Add scraped_after Filter Param

In `api_events()`, after the existing `ordering` param extraction:

```python
scraped_after = request.GET.get("scraped_after", "").strip()
```

In the queryset filter block:

```python
if scraped_after:
    try:
        from django.utils.dateparse import parse_datetime
        ts = parse_datetime(scraped_after)
        if ts:
            events = events.filter(scraped_at__gt=ts)
    except (ValueError, TypeError):
        pass  # Ignore malformed timestamp — return unfiltered
```

#### Stage 2: Add search_query to select_related

Change:
```python
events = Event.objects.select_related("venue", "organizer_ref")
```
To:
```python
events = Event.objects.select_related("venue", "organizer_ref", "search_query")
```

#### Stage 3: Expand Response Dict

Replace the existing `results` list comprehension with the full 11-column shape:

```python
results = [
    {
        # ── Google Sheets columns ────────────────────────────────
        "db_id":          e.id,
        "scraped_at":     e.scraped_at.isoformat() if e.scraped_at else None,
        "search_term":    e.search_query.query if e.search_query_id else None,
        "organizer_name": e.organizer_display_name,
        "category":       e.agent_categories[0] if e.agent_categories else e.category,
        "location":       e.venue.city if e.venue_id and e.venue.city else None,
        "post_link":      e.url,
        "fb_post_id":     e.external_id or None,
        "post_date":      e.post_date.isoformat() if e.post_date else None,
        "summary":        e.description or None,
        "raw_text":       e.raw_text or None,
        # ── Legacy fields (keep for backward compat with existing frontend) ──
        "slug":           e.slug,
        "name":           e.name,
        "starts_at":      e.starts_at.isoformat() if e.starts_at else None,
        "ends_at":        e.ends_at.isoformat() if e.ends_at else None,
        "agent_categories": e.agent_categories,
        "source":         e.source,
        "price":          e.price,
        "venue":          e.venue.name if e.venue_id else None,
        "venue_slug":     e.venue.slug if e.venue_id else None,
        "organizer":      e.organizer_display_name,
        "organizer_slug": e.organizer_ref.slug if e.organizer_ref_id else None,
        "url":            e.url,
    }
    for e in page_obj
]
```

**Note:** The frontend currently uses `slug`, `name`, `starts_at`, `ends_at`, `source`, `price`,
`venue`, `venue_slug`, `organizer`, `organizer_slug`, `url`, `category`, `agent_categories`. All
are preserved; new fields are additive. No breaking changes.

#### Stage 4: Add page size param (optional but recommended for n8n)

n8n will want to pull all new rows in one call. Add:

```python
try:
    limit = max(1, min(int(request.GET.get("limit", 50)), 500))
except ValueError:
    limit = 50
paginator = Paginator(events, limit)
```

This lets n8n call `?source=facebook_posts&scraped_after=<ts>&limit=500` to get up to 500 rows
in a single request.

#### Post-Phase Testing

```bash
# Basic call — confirm new fields present
curl -s "http://localhost:8000/api/events/?source=facebook_posts&ordering=-scraped_at&limit=3" \
  | python3 -m json.tool | grep -E '"(db_id|scraped_at|search_term|raw_text|post_date|summary|fb_post_id)"'

# scraped_after filter — should return only rows newer than the timestamp
curl -s "http://localhost:8000/api/events/?source=facebook_posts&scraped_after=2026-06-24T00:00:00Z" \
  | python3 -m json.tool | python3 -c "import sys,json; d=json.load(sys.stdin); print('total:', d['total'])"

# Malformed scraped_after — should return unfiltered (not 500)
curl -s "http://localhost:8000/api/events/?source=facebook_posts&scraped_after=notadate" \
  | python3 -m json.tool | python3 -c "import sys,json; d=json.load(sys.stdin); print('total:', d['total'])"
```

#### Verification Checklist

- [ ] Response includes all 11 `db_id`…`raw_text` fields
- [ ] `search_term` is populated for events linked to a SearchQuery, `null` otherwise
- [ ] `location` is the venue city string (not the full venue object)
- [ ] `scraped_after` correctly filters to only newer rows
- [ ] Malformed `scraped_after` returns unfiltered results (no 500 error)
- [ ] Legacy fields (`slug`, `name`, `starts_at`, `venue`, etc.) still present
- [ ] `limit` param works (default 50, max 500)
- [ ] SvelteKit frontend still renders the events list correctly after the change
- [ ] All 97 backend tests still pass

**What's Functional Now:** n8n can pull the exact row set it needs in one HTTP call.

**Ready For:** n8n wiring.

---

## n8n Wiring Guide

Once all three RFCs are ✅ VERIFIED, configure the n8n workflow as follows.

### Nodes

```text
1. [Schedule Trigger]           — cron or manual
        ↓
2. [HTTP Request] Trigger run
   Method:  POST
   URL:     http://<your-server>:8000/api/scrapers/facebook_posts/run/
   Capture: run_id = {{ $json.id }}
   Start timestamp: startTs = {{ new Date().toISOString() }}
        ↓
3. [Wait] 30 seconds
        ↓
4. [HTTP Request] Poll run status
   Method:  GET
   URL:     http://<your-server>:8000/api/scrapers/runs/{{ $('Trigger run').item.json.id }}/
        ↓
5. [IF] status == "completed"
   → Yes: continue
   → No:  loop back to [Wait] (use n8n Loop node or If + Go-back)
        ↓
6. [HTTP Request] Fetch new events
   Method:  GET
   URL:     http://<your-server>:8000/api/events/
   Params:
     source        = facebook_posts
     scraped_after = {{ $('Trigger run').item.json.startTs }}
     ordering      = -scraped_at
     limit         = 500
        ↓
7. [Code] Map columns
   Return items[].json.results.map(e => ({
     json: {
       db_id:          e.db_id,
       scraped_at:     e.scraped_at,
       search_term:    e.search_term ?? "",
       organizer_name: e.organizer_name ?? "",
       category:       e.category ?? "",
       location:       e.location ?? "",
       post_link:      e.post_link ?? "",
       fb_post_id:     e.fb_post_id ?? "",
       post_date:      e.post_date ?? "",
       summary:        e.summary ?? "",
       raw_text:       e.raw_text ?? "",
     }
   }));
        ↓
8. [Google Sheets] Append rows
   Spreadsheet: <your sheet>
   Sheet:       FB Posts
   Columns:     db_id, scraped_at, search_term, organizer_name, category,
                location, post_link, fb_post_id, post_date, summary
```

### Storing the start timestamp

n8n HTTP Request nodes don't natively expose when the request was made. Workaround: add a
**[Set]** node before the trigger call that sets `startTs = {{ new Date().toISOString() }}` and
reference it downstream as `{{ $('Set startTs').item.json.startTs }}`.

### Polling loop pattern

n8n's native loop: use a **[Wait]** node (30s) + **[IF]** (status == "completed") + connect the
"false" branch back to the **[Wait]** node. Set a max iteration guard (e.g. 20 loops = 10 min
timeout) to avoid infinite loops if a scraper run hangs.

---

## Touchpoints

| File | Change type | Why |
|---|---|---|
| `apps/backend/events/models.py` | Modify — add 2 fields | Core model change |
| `apps/backend/events/migrations/0023_*.py` | Create | Schema migration |
| `apps/backend/events/scrapers/base.py` | Modify — ScrapedEvent + save_events | Scraper data contract |
| `apps/backend/events/scrapers/facebook_posts.py` | Modify — JS + run() loop | Capture new fields |
| `apps/backend/events/views.py` | Modify — api_events() | Expose new fields |

No frontend files change. No new dependencies. No schema changes to other models.

---

## Public Contracts

### api_events() response shape (additive — no removals)

New top-level keys added to every item:
```
db_id          integer
scraped_at     ISO 8601 string | null
search_term    string | null
organizer_name string | null
category       string | null
location       string | null        (venue city)
post_link      string | null        (FB post URL, same as existing "url")
fb_post_id     string | null        (same as existing external_id)
post_date      ISO 8601 string | null
summary        string | null        (same as existing description)
raw_text       string | null
```

All existing keys (`slug`, `name`, `starts_at`, `ends_at`, `source`, `price`, `venue`,
`venue_slug`, `organizer`, `organizer_slug`, `url`, `category`, `agent_categories`) are preserved.

### ScrapedEvent dataclass (additive)

Two new optional fields: `raw_text: str = ""` and `post_date: datetime | None = None`.
Existing callers that don't pass these fields are unaffected (defaults apply).

### save_events() (additive)

Only writes `raw_text` and `post_date` when they are non-empty / non-None. Existing callers
(all other scrapers) are unaffected.

---

## Blast Radius

| Component | Risk | Mitigation |
|---|---|---|
| All existing Event rows | `raw_text` defaults to `""`, `post_date` defaults to `NULL` — no data loss | Migration is purely additive |
| SvelteKit frontend | New JSON keys are ignored by existing code | Confirmed additive; legacy keys preserved |
| Other scrapers (eventbrite, luma, etc.) | None — `save_events` only writes new fields when provided | Defaults prevent null writes |
| Test suite (97 tests) | Migration adds columns; no logic changes until RFC-002 | Run `manage.py test events` after each RFC |
| Ollama processing | Unchanged | Not touched |
| `scraped_after` filter | Malformed input ignored (returns unfiltered) | Try/except in view |

---

## Verification Evidence

After all three RFCs are ✅ VERIFIED, run these in order to confirm end-to-end:

```bash
# 1. Migration applied
cd apps/backend && ./venv/bin/python manage.py showmigrations events | grep 0023

# 2. Test suite green
./venv/bin/python manage.py test events -v 1

# 3. New fields populated after a scrape
./venv/bin/python manage.py shell -c "
from events.models import Event
qs = Event.objects.filter(source='facebook_posts', raw_text__gt='').order_by('-scraped_at')[:3]
for e in qs: print(e.id, e.post_date, e.raw_text[:60])
"

# 4. API returns all 11 columns
curl -s 'http://localhost:8000/api/events/?source=facebook_posts&limit=1' \
  | python3 -m json.tool \
  | grep -E '"(db_id|scraped_at|search_term|organizer_name|category|location|post_link|fb_post_id|post_date|summary|raw_text)"'

# 5. scraped_after filter works
curl -s 'http://localhost:8000/api/events/?source=facebook_posts&scraped_after=2099-01-01T00:00:00Z' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['total'] == 0, 'filter broken'"
echo "scraped_after filter OK"
```

---

## Resume and Execution Handoff

**If resuming after compaction or a new session, read these files first:**

1. `apps/backend/events/models.py` — check if `raw_text` and `post_date` fields exist on `Event`.
2. `apps/backend/events/migrations/` — run `manage.py showmigrations events | tail -5` to see which RFC-001 migration was applied.
3. `apps/backend/events/scrapers/base.py` — check if `ScrapedEvent` has `raw_text` and `post_date` fields.
4. `apps/backend/events/views.py` (api_events function) — check if `db_id` key is in the results dict.

**Current status entry point:**
- If `Event.raw_text` does not exist → start at RFC-001.
- If `Event.raw_text` exists but `ScrapedEvent` does not have it → start at RFC-002 Stage 2.
- If `ScrapedEvent` has it but `api_events` doesn't return `db_id` → start at RFC-003.
- If all fields are present → proceed directly to n8n wiring guide.

**Approved plan path:** `process/general-plans/active/fb-posts-n8n-sheets-pipeline_PLAN_24-06-26.md`

---

## Acceptance Criteria

All of the following must be true before this work is considered complete:

**RFC-001 — Model + Migration**
- [ ] `Event.raw_text` (TextField, blank=True) exists in `models.py` and in the DB
- [ ] `Event.post_date` (DateTimeField, null=True, db_index=True) exists in `models.py` and in the DB
- [ ] Migration `0023_add_raw_text_post_date` is applied (`[X]` in showmigrations)
- [ ] All 97 existing Django tests pass after migration

**RFC-002 — Scraper Capture**
- [ ] `_EXTRACT_POSTS_JS` extracts `post_date_raw` from `time[datetime]` attribute
- [ ] `ScrapedEvent` dataclass in `base.py` has `raw_text` and `post_date` fields with safe defaults
- [ ] `save_events` writes `raw_text` and `post_date` when non-empty/non-None
- [ ] After a `facebook_posts` scrape run, freshly created Event rows have `raw_text != ""`
- [ ] `post_date` is a valid timezone-aware datetime for posts that expose `time[datetime]`; NULL otherwise
- [ ] All 97 existing Django tests pass

**RFC-003 — API Expansion**
- [ ] `GET /api/events/?source=facebook_posts` response includes all 11 Google Sheets columns: `db_id`, `scraped_at`, `search_term`, `organizer_name`, `category`, `location`, `post_link`, `fb_post_id`, `post_date`, `summary`, `raw_text`
- [ ] All legacy response keys (`slug`, `name`, `starts_at`, `venue`, `organizer`, `url`, etc.) still present — no breaking changes
- [ ] `?scraped_after=<ISO 8601>` returns only rows with `scraped_at > ts`
- [ ] Malformed `scraped_after` silently ignored (returns unfiltered, no 500)
- [ ] `?limit=500` supported (up to 500 rows in one call)
- [ ] `select_related("search_query")` prevents N+1 on `search_term`
- [ ] SvelteKit frontend events list renders correctly (no regression)
- [ ] All 97 existing Django tests pass

**End-to-end (n8n)**
- [ ] n8n HTTP trigger starts a facebook_posts scrape run and receives `run_id`
- [ ] Polling loop correctly detects `status == "completed"`
- [ ] `GET /api/events/?source=facebook_posts&scraped_after=<ts>` returns only the newly scraped rows
- [ ] All 11 columns map correctly to Google Sheets columns with no null pointer errors

---

## Cursor + RIPER-5 Guidance

### Cursor Plan Mode

Import RFC implementation checklists directly. Execute RFC-001 → RFC-002 → RFC-003 in order. After
each RFC, update the status strip and run the Verification Checklist before continuing.

### RIPER-5 Mode

- **RESEARCH**: ✅ Complete (all files reviewed, gaps identified, migration state confirmed).
- **INNOVATE**: ✅ Complete (architecture decisions recorded above).
- **PLAN**: ✅ Complete — this document.
- **EXECUTE**: Begin with RFC-001. Pass this plan file to `vc-execute-agent`. Execute EXACTLY as specified. Mid-implementation check-in after RFC-002.
- **VERIFY**: After each RFC, stop and run the Verification Checklist. Do NOT proceed until ✅ VERIFIED.

**Next step:** Review this plan, then say `ENTER EXECUTE MODE` to begin RFC-001.

> **Reminder:** Each RFC requires verification before proceeding to the next. Do not batch RFCs into one execution.
