# Leads API → n8n → Google Sheets Handoff

**Branch:** `feat/leads-api` (PR #48, target: `development`)  
**Endpoint live on:** development server (`http://localhost:8000/api/leads/`)  
**Author:** Hans Del Mundo  

---

## 1. What Was Built

`GET /api/leads/` is a read-only endpoint that reshapes scraped event data into a
CRM-ready row format matching the team's Google Sheets leads tracker. It replaces
manual data pulls and is intended as the single source of truth for the n8n →
Sheets pipeline.

**Key properties:**
- Returns **future events only** (`starts_at ≥ now`). Past events are never returned.
- Default ordering: `starts_at` ascending (soonest-first).
- Paginated, max 500 rows per page.
- No authentication required (same as all other `/api/` read endpoints).

---

## 2. Why This Is Better Than the Previous Approach

### The old model: semi-synchronous

Before this endpoint, the path from scraper to Sheets was tightly coupled:

```
Scraper run completes → n8n triggered immediately → push to Sheets
```

This is semi-synchronous because the Sheets write is a side effect of the scraper
run. If n8n was down, timing was off, or the Sheets API rate-limited, the window
was missed and data was lost or stale until the next scraper run. A failed sync
meant manually re-triggering — and you had no way to pull just the data you needed
without re-running the full scraper.

### The new model: fully decoupled

```
Scraper runs  →  writes to DB  (independent)
                                    ↓
                     /api/leads/ sits on top of DB
                                    ↓
n8n polls on its own schedule  →  reads API  →  writes to Sheets  (independent)
```

The scraper and the Sheets sync no longer know about each other. The DB is the
shared state. This gives you:

**Retry safety without data loss.** If the Sheets sync fails mid-run, n8n retries
against the same stable API. The scraper doesn't need to run again — the data is
already in the DB waiting to be read.

**Independent scheduling.** Scraper runs and Sheets syncs can be on completely
different cadences. Run the scraper every 6 hours, sync to Sheets every morning at
08:00, or trigger the sync manually at any time — none of these depend on each other.

**On-demand pulls.** Anyone can hit `GET /api/leads/` at any time with any filter
combination and get the current view of the data. The n8n workflow is just one
consumer; a future dashboard, export script, or another automation can read the same
endpoint without touching the scraper.

**Parameterized syncs.** The old pipeline pushed everything. Now you can run
country-scoped syncs (`?country=Philippines`), contact-only syncs
(`?has_contact=1`), or freshness-scoped syncs (`?scraped_after=<last-run-timestamp>`)
without changing any scraper code.

**Failure isolation.** A scraper failure doesn't affect Sheets (the existing data
stays). A Sheets API outage doesn't affect scraping. Each system fails and recovers
independently.

---

## 3. API Reference

### Endpoint

```
GET /api/leads/
```

### Query Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `country` | string | — | Filter by venue country, case-insensitive (e.g. `Philippines`) |
| `source` | string | — | Filter by scraper source (e.g. `facebook_events`, `eventbrite`) |
| `scraped_after` | ISO 8601 datetime | — | Only events scraped after this timestamp. Invalid value → 400. |
| `has_contact` | `"1"` | — | Only events where organizer has an email or phone on record |
| `min_days` | int ≥ 0 | `0` | Minimum days from now before event starts. `0` = any future event, `7` = events more than a week out |
| `page` | int ≥ 1 | `1` | Page number |
| `limit` | int 1–500 | `100` | Rows per page |

### Response Envelope

```json
{
  "results": [...],
  "total": 808,
  "pages": 162,
  "page": 1
}
```

`page` reflects the **actual served page** (clamps to last page for out-of-range requests).

### Result Row Shape (14 fields)

```json
{
  "db_id":              1747,
  "category":           "Art",
  "page_name":          "Easy Diving Dauin",
  "location_city":      "Dauin",
  "location_country":   "Philippines",
  "event":              "Dive Dauin Photo Festival",
  "link":               "https://www.facebook.com/events/3486384844861796/",
  "event_date":         "2026-07-15T02:00:00+00:00",
  "post_date":          null,
  "organizer_email":    "dauin@easydiving.ph",
  "organizer_phone":    "0905 230 5272",
  "organizer_facebook": "https://www.facebook.com/divesocietydauin",
  "platform":           "facebook_events",
  "scraped_at":         "2026-06-24T02:46:18.934186+00:00"
}
```

**Nullable fields:** `location_city`, `location_country`, `post_date`, `organizer_email`,
`organizer_phone`, `organizer_facebook`, `link`, `platform` — all return `null` when
not available.

### Error Responses

| Scenario | Status | Body |
|---|---|---|
| Invalid `scraped_after` | 400 | `{"error": "Invalid scraped_after timestamp"}` |
| Non-GET request | 403 | Django CSRF rejection (same as all read-only views) |

---

## 4. Google Sheets Column Mapping

Recommended mapping from API fields to the existing leads tracker columns:

| Sheets Column | API Field | Notes |
|---|---|---|
| Category | `category` | First agent-classified category, falls back to raw `event.category` |
| Page Name | `page_name` | Organizer display name |
| Location | `location_city` + `location_country` | Concatenate: `"Cebu City, Philippines"` |
| Event | `event` | Event name |
| Link | `link` | Event URL |
| Event Date | `event_date` | ISO 8601 — reformat in n8n to `YYYY-MM-DD` or locale string |
| Notes | `organizer_email` + `organizer_phone` + `organizer_facebook` | Concatenate available contact info |
| Platform | `platform` | Source scraper identifier |
| Added By | _(static)_ | Set to `"veent-bot"` or leave for manual entry |
| Reached Out By | _(blank)_ | CRM field — stays in Sheets, not in API |
| Status | _(blank)_ | CRM field — stays in Sheets, not in API |
| Date Reached Out | _(blank)_ | CRM field — stays in Sheets, not in API |

---

## 5. Recommended n8n Workflow Design

### Sync strategy: Full Replace

Clear the data range each run and rewrite all rows. Simpler than incremental
diffing and safe because the dataset is small (< 1000 rows per country filter).

### Node Layout

```
[Schedule Trigger] → [Loop: Fetch All Pages] → [Flatten Items] → [Clear Sheet Range] → [Google Sheets: Append Rows]
```

### Node Configs

#### Schedule Trigger
- Interval: daily at a time after scraper runs complete (e.g. 08:00 PH time)

#### HTTP Request — Fetch Page
- Method: GET
- URL: `http://<your-backend>/api/leads/`
- Query parameters:
  - `country`: `Philippines` (or leave blank for all countries)
  - `min_days`: `7` (leads at least a week out)
  - `has_contact`: `1` (only rows with contact info — optional, reduces noise)
  - `limit`: `500`
  - `page`: `{{ $json.page }}` (from loop variable)

#### Loop Logic (using n8n's Loop Over Items or a Code node)

```javascript
// Initialise
const firstPage = await fetch('/api/leads/?limit=500&page=1&min_days=7');
const data = await firstPage.json();
const totalPages = data.pages;
let allResults = [...data.results];

// Subsequent pages
for (let p = 2; p <= totalPages; p++) {
  const res = await fetch(`/api/leads/?limit=500&page=${p}&min_days=7`);
  const d = await res.json();
  allResults = allResults.concat(d.results);
}
```

In n8n, implement this as a **Split In Batches** loop with a counter expression,
or use the native HTTP Request pagination (set "Pagination" → "Response Contains
Next URL" or "By Page"). See Section 5 for the pagination approach.

#### Transform / Code Node — Map to Sheet Row

```javascript
return items.map(item => {
  const r = item.json;
  const location = [r.location_city, r.location_country].filter(Boolean).join(', ');
  const eventDate = r.event_date ? r.event_date.slice(0, 10) : '';
  const notes = [r.organizer_email, r.organizer_phone, r.organizer_facebook]
    .filter(Boolean).join(' | ');

  return {
    json: {
      Category:       r.category || '',
      'Page Name':    r.page_name || '',
      Location:       location,
      Event:          r.event || '',
      Link:           r.link || '',
      'Event Date':   eventDate,
      Notes:          notes,
      Platform:       r.platform || '',
      'Added By':     'veent-bot',
    }
  };
});
```

#### Google Sheets — Clear Range
- Operation: **Clear**
- Range: `Sheet1!A2:Z` (everything below the header row)

#### Google Sheets — Append Rows
- Operation: **Append or Update**
- Sheet: your target sheet
- Column mapping: match key names from the transform node to sheet column headers

---

## 6. Pagination in n8n (Native Approach)

n8n's HTTP Request node supports automatic pagination. Use **"Response Contains
Next URL"** mode is not ideal here because the API uses page numbers. Instead:

1. Set **Pagination** → **"By Page"**
2. Page parameter name: `page`
3. Pagination complete expression: `{{ $response.body.page >= $response.body.pages }}`

This automatically increments `page` until the last page is reached.

---

## 7. Useful Filter Combinations

| Use case | Query string |
|---|---|
| All upcoming PH events | `?country=Philippines&min_days=0&limit=500` |
| PH events next 2 weeks | `?country=Philippines&min_days=7&limit=500` |
| Only contactable leads | `?country=Philippines&has_contact=1&min_days=7&limit=500` |
| Facebook events only | `?source=facebook_events&country=Philippines&limit=500` |
| New scrapes since yesterday | `?scraped_after=2026-06-24T00:00:00Z&limit=500` |

---

## 8. Known Data Gaps

These are data coverage issues, not bugs. The API returns what is in the DB.

| Field | Gap | Cause |
|---|---|---|
| `organizer_email` / `organizer_phone` | Null on most Eventbrite/allevents rows | `organizer_ref` FK only populated after deduplication step runs |
| `organizer_facebook` | Null on recently scraped rows | Same as above |
| `location_city` / `location_country` | Sparse on `facebook_posts` source | Venue extraction depends on LLM pipeline completing |
| `post_date` | Null on all non-`facebook_posts` rows | Field only populated by the FB Posts scraper |
| `category` | Null on freshly scraped rows | LLM categorization (`categorize-events` command) must run first |

**Recommendation for Sheets:** use `has_contact=1` to filter to rows with at least
one contact field populated. This reduces output from ~800 to ~133 rows but ensures
every row is actionable.

---

## 9. Testing the Endpoint

Before wiring n8n, verify the endpoint manually:

```bash
# Basic check — should return 808 total (or similar)
curl -s "http://localhost:8000/api/leads/?limit=5" | python3 -m json.tool

# Contactable leads only, 1 week+ ahead
curl -s "http://localhost:8000/api/leads/?has_contact=1&min_days=7&limit=5" | python3 -m json.tool

# Invalid scraped_after → must return 400
curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/api/leads/?scraped_after=bad"
```

---

## 10. What's Not in the API (stays in Sheets)

The following CRM workflow columns are intentionally absent from the API and must
remain managed in Google Sheets:

- **Status** (e.g. Not Contacted / Reached Out / Converted)
- **Reached Out By**
- **Date Reached Out**

These fields are human-managed and would be overwritten on every sync if included
in the API. The n8n workflow should only write to the data columns (A–H in the
recommended mapping) and leave the CRM columns (I–L) untouched by using
**Append** (not overwrite) or by clearing only the data range.

---

## 11. Contacts / Repo

- **Backend repo:** `hdmGOAT/veent-event-scraper`
- **PR:** #48 (`feat/leads-api` → `development`)
- **Endpoint file:** `apps/backend/events/views.py` → `api_leads()` (line 498)
- **URL route:** `apps/backend/events/urls.py` (line 25)
