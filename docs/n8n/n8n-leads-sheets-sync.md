# n8n Workflow: FB Scraper to Google Sheets (async events → Sheets sync)

Polls the live `GET /api/events/` endpoint and **upserts** the current database
event rows into a Google Sheets tracker. Does **no scraping** — the scraper writes
to the DB, this workflow only reads the API and syncs to Sheets. The DB is the
shared state between the two systems, so scraping and syncing are fully decoupled.

- **n8n instance:** local self-hosted n8n (v2.27.3), `http://localhost:5678`
  (the global `n8n` install, launched via `apps/n8n` / `pnpm dev`). **Not** n8n.cloud.
- **Workflow name / ID:** `FB Scraper to Google Sheets` / `EzCKmFfmHrYXutx2`
- **Target spreadsheet:** `[EXPERIMENT] Centralized List of Events`
  (`1OFkShy9b2Nt39tgizjd6yYpyFsGDbzLy-lj9JsB8U7A`)
- **Target tab:** `Events Sync` (gid `424242`)
- **API endpoint:** `GET /api/events/` (Django, unauthenticated read endpoint)

> The endpoint and its row shape are documented in
> `process/general-plans/references/leads-api-n8n-handoff.md` (that doc describes
> `/api/leads/`; this workflow uses the richer `/api/events/`, which also exposes
> `search_term`, `fb_post_id`, `summary`, and `raw_text`).

---

## How it works

```
Daily 00:00 UTC Trigger ─┐
Manual Run               ┘→ [Clear Events Sync Range — DISABLED]
                              → Fetch All Events (Paginated)   GET http://127.0.0.1:8000/api/events/?limit=500
                                  │                            pagination: page = {{ $pageCount + 1 }}, halts when page >= pages
                                  ▼
                              Map Events to Sheet Rows         Code node — maps API rows to the n8n-owned columns,
                                  │                            formats event_date, computes event_status
                                  ▼
                              Upsert Event Rows (by db_id)     Google Sheets: Append or Update, match on db_id
```

**Upsert strategy (not Full Replace).** Each sync **updates existing rows in place**
(matched on `db_id`) and **appends new events**. It writes only the n8n-owned
columns and **never clears** the sheet. This is deliberate:

- It preserves human-managed columns that sit anywhere in the sheet — both the
  `event_date` neighbours and the CRM columns on the right (Notes, Added By,
  Reached Out By, Status, Date Reached Out). A clear-and-replace would wipe or
  misalign them.
- Events removed from the DB are **not deleted** from the sheet — correct for a
  lead tracker (you don't lose rows you've annotated). The trade-off: stale rows
  accumulate; purge them manually if ever needed.

The old `Clear Events Sync Range` node is left in the canvas but **disabled** — the
upsert makes clearing unnecessary and unsafe.

Both triggers fan in to the same chain, so a Manual Run and the daily Schedule run
behave identically.

---

## Columns

n8n writes these columns by **header name** (order in the sheet does not matter —
auto-map binds by name):

| Header | Source / transform |
|---|---|
| `db_id` | API `db_id` — **the match key** for upsert |
| `scraped_at` | API `scraped_at` |
| `search_term` | API `search_term` |
| `event` | API `event` |
| `event_date` | API `event_date`, reformatted to `M/D/YYYY H:MM:SS` (see below) |
| `organizer_name` | API `organizer_name` |
| `organizer_email` | API `organizer_email` |
| `organizer_phone` | API `organizer_phone` — written only if the header exists |
| `category` | API `category` |
| `location` | API `location` |
| `post_link` | API `post_link` |
| `fb_post_id` | API `fb_post_id` |
| `post_date` | API `post_date` |
| `summary` | API `summary` |
| `raw_text` | API `raw_text` |
| `event_status` | computed — `Upcoming` / `Past` / `No Date` |

**Never touched by n8n** (safe to add/edit/format freely): any column not in the
list above — e.g. the CRM columns `Notes`, `Added By`, `Reached Out By`, `Status`,
`Date Reached Out`. The Upsert node's `handlingExtraData` is set to `ignoreIt`, so
a column n8n expects but can't find is silently skipped rather than erroring.

### `event_date` formatting

The Map node formats the API's ISO timestamp into `M/D/YYYY H:MM:SS`
(e.g. `2026-06-27T11:00:00+00:00` → `6/27/2026 11:00:00`) using the timestamp's
**UTC wall-clock** (no timezone shift — 11:00 stays 11:00). It is written with the
default `USER_ENTERED` cell format, so Sheets stores it as a real, sortable
date/time that displays in that format. To store the literal string as text
instead, switch the Upsert node's `cellFormat` to `RAW`.

### `event_status` (computed)

| Value | Condition |
|---|---|
| `Upcoming` | `event_date >= now` |
| `Past` | `event_date < now` |
| `No Date` | `event_date` empty/unparseable |

Lets the sheet hold both past and future events while differentiating them.

---

## Configuration / operational notes

### API URL is hardcoded (not an env var)

The Fetch node URL is the literal `http://127.0.0.1:8000/api/events/`.

- **Why not `{{ $env.LEADS_API_BASE_URL }}`?** This n8n instance has
  `N8N_BLOCK_ENV_ACCESS_IN_NODE` enabled, so `$env` access from a node throws
  `access to env vars denied`.
- **Why `127.0.0.1` and not `localhost`?** n8n resolves `localhost` to IPv6 `::1`,
  but Django listens on IPv4 `127.0.0.1:8000` only — `localhost` fails with
  `ECONNREFUSED ::1:8000`.
- **Deploying n8n off this machine?** Change the URL to a reachable tunnel/domain
  (the API must be reachable from wherever n8n runs). For env-var indirection, an
  admin must unset `N8N_BLOCK_ENV_ACCESS_IN_NODE`.

### Google Sheets credential

Both Sheets nodes use the `Google Sheets account` OAuth credential
(`googleSheetsOAuth2Api`, id `2niz9sSp1GmkddsF`). The HTTP node needs **no**
credential — `/api/events/` is unauthenticated.

### Schedule

A daily 00:00 UTC Schedule Trigger exists but the workflow is **run manually** for
now — it won't fire on schedule until toggled **Active**, and (being local) only
runs while the machine + n8n are up. n8n does **not** catch up missed runs.

### Query parameters (Fetch node)

| Param | Default | Effect |
|---|---|---|
| `limit` | `500` | Max rows per page |
| `page` | _(pagination)_ | Auto-incremented until `page >= pages` |
| `scraped_after` | _(unset)_ | Optional ISO 8601 freshness filter |
| `upcoming` | _(unset)_ | Set to `1` to fetch only future events |

---

## ⚠️ Editing the sheet columns — the column-cache caveat

The Upsert (Append/Update) node **caches the sheet's column list** at setup time
and re-validates it against the live sheet on every **UI and scheduled** run
(API-triggered runs skip this check). If a column **n8n writes** is renamed,
removed, or added, that cache goes stale and the run fails with:

> *Column names were updated after the node's setup. Refresh the columns list…
> Missing columns: `<name>`*

Fix: click **"Refresh columns"** in the Upsert node (or rebuild its column list).

Rules of thumb:
- **Safe, no refresh needed:** adding/editing/formatting columns n8n does **not**
  write (CRM columns, any extra columns).
- **Needs a column refresh:** adding, removing, or renaming a column n8n **does**
  write (the list above). Example seen in practice: removing `organizer_phone`, or
  renaming `raw_event_date` → `event_date`.

---

## Verifying the endpoint

Run against the local Django server (use `127.0.0.1`, not `localhost`):

```bash
curl -s "http://127.0.0.1:8000/api/events/?limit=5" | python3 -m json.tool
curl -s "http://127.0.0.1:8000/api/events/?upcoming=1&limit=5" | python3 -m json.tool
curl -s "http://127.0.0.1:8000/api/events/?limit=500&page=1" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(f'total={d[\"total\"]} pages={d[\"pages\"]} page={d[\"page\"]}')"
```

---

## Manual Run verification

(Last verified 2026-06-25: ~2,025 rows, 4 pages, no duplicate `db_id`s.)

1. **Fetch** paginates; page envelopes report matching `total`/`pages`.
2. **Map** emits one item per event with the n8n-owned columns; `event_date` is
   `M/D/YYYY H:MM:SS`; `event_status` matches the date.
3. **Upsert** succeeds; existing rows update in place (no duplication — row count
   equals distinct `db_id` count); CRM columns and any non-n8n columns unchanged.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Column names were updated after the node's setup … Missing columns: X` | A column n8n writes was renamed/removed/added — refresh the Upsert node's column list (see caveat above) |
| HTTP node: `ECONNREFUSED ::1:8000` | `localhost` resolved to IPv6; use `127.0.0.1` |
| HTTP node: `access to env vars denied` | `$env` blocked by `N8N_BLOCK_ENV_ACCESS_IN_NODE`; hardcode the URL |
| HTTP node: connection refused | Django not running, or URL not reachable from the n8n host |
| Duplicate rows appear | `db_id` match key missing/renamed in the sheet, or matching failed — confirm header `db_id` exists and is the match column |
| `event_date` shows as text not a date (or vice-versa) | Controlled by the column's Sheets number format + the node `cellFormat` (`USER_ENTERED` vs `RAW`) |
| Stale events never disappear | Expected — upsert never deletes; purge manually if needed |
| Google Sheets: 401 / permission error | OAuth credential not attached or expired — re-authorize in n8n |
| Workflow does not run on schedule | Workflow not Active, or the machine/n8n was down at the scheduled time (no catch-up) |
