# n8n Workflow: FB Scraper to Google Sheets (async events → Sheets sync)

Polls the live `GET /api/events/` endpoint and writes the current database event
rows into a Google Sheets tracker. Does **no scraping** — the scraper writes to
the DB, this workflow only reads the API and syncs to Sheets. The DB is the shared
state between the two systems, so scraping and syncing are fully decoupled.

- **n8n instance:** local self-hosted n8n (v2.27.3), `http://localhost:5678`
  (the global `n8n` install, launched via `apps/n8n` / `pnpm dev`). **Not** n8n.cloud.
- **Workflow name / ID:** `FB Scraper to Google Sheets` / `EzCKmFfmHrYXutx2`
- **Target spreadsheet:** `[EXPERIMENT] Centralized List of Events`
  (`1OFkShy9b2Nt39tgizjd6yYpyFsGDbzLy-lj9JsB8U7A`)
- **Target tab:** `Events Sync` (gid `424242`) — a dedicated, bot-managed tab
- **API endpoint:** `GET /api/events/` (Django, unauthenticated read endpoint)

> The endpoint and its 15-field row shape are documented in
> `process/general-plans/references/leads-api-n8n-handoff.md` (that doc describes
> `/api/leads/`; this workflow uses the richer `/api/events/`, which exposes
> `search_term`, `fb_post_id`, `summary`, and `raw_text` as well).

---

## How it works

```
Daily 00:00 UTC Trigger ─┐
Manual Run               ┘→ Clear Events Sync Range   Google Sheets: Clear, range A2:P (keeps header row 1)
                              │
                              ▼
                          Fetch All Events (Paginated)   GET http://127.0.0.1:8000/api/events/?limit=500
                              │                          pagination: "Update a parameter in each request",
                              │                          page = {{ $pageCount + 1 }}, halts when page >= pages
                              ▼
                          Map Events to Sheet Rows       Code node — flatten pages → 16 columns, null-safe,
                              │                          computes event_status (Upcoming / Past / No Date)
                              ▼
                          Append Event Rows              Google Sheets: Append, auto-map by header
```

**Full Replace strategy.** Both triggers fan in to the **Clear** node first, which
blanks the data range `A2:P` (preserving the header row in row 1). Then the fetch
→ map → append runs. Clearing *before* appending means there is never a
partial-overlap state. Because the Clear keeps row 1, the append's auto-map always
binds to a stable header row — this is what prevents column drift (see
[Troubleshooting](#troubleshooting)).

Both triggers share the identical chain (fan-in), so a Manual Run and the daily
Schedule run behave the same.

---

## Sheet columns (16, A–P)

The `Events Sync` tab is **all data, no human-managed columns** — every column is
overwritten on each run.

| Col | Header | Source |
|---|---|---|
| A | `db_id` | API `db_id` |
| B | `scraped_at` | API `scraped_at` |
| C | `search_term` | API `search_term` |
| D | `event` | API `event` |
| E | `event_date` | API `event_date` |
| F | `organizer_name` | API `organizer_name` |
| G | `organizer_email` | API `organizer_email` |
| H | `organizer_phone` | API `organizer_phone` |
| I | `category` | API `category` |
| J | `location` | API `location` |
| K | `post_link` | API `post_link` |
| L | `fb_post_id` | API `fb_post_id` |
| M | `post_date` | API `post_date` |
| N | `summary` | API `summary` |
| O | `raw_text` | API `raw_text` |
| **P** | **`event_status`** | **computed — see below** |

Columns A–O are a **passthrough by key** (the `/api/events/` field names match the
headers 1:1), null-safe — every blank becomes `''` (never the literal string
`"null"`, which Sheets would otherwise display).

### `event_status` (computed)

The Map node compares each row's `event_date` to the run time:

| Value | Condition |
|---|---|
| `Upcoming` | `event_date >= now` |
| `Past` | `event_date < now` |
| `No Date` | `event_date` is empty/unparseable |

This lets the sheet hold **both past and future events** while still
differentiating them (filter/sort on column P).

---

## Configuration / operational notes

### API URL is hardcoded (not an env var)

The Fetch node URL is the literal `http://127.0.0.1:8000/api/events/`.

- **Why not `{{ $env.LEADS_API_BASE_URL }}`?** This n8n instance has
  `N8N_BLOCK_ENV_ACCESS_IN_NODE` enabled, so `$env` access from a node throws
  `access to env vars denied`. The URL is therefore set directly.
- **Why `127.0.0.1` and not `localhost`?** n8n resolves `localhost` to IPv6 `::1`,
  but the Django dev server listens on IPv4 `127.0.0.1:8000` only — using
  `localhost` fails with `ECONNREFUSED ::1:8000`.
- **Deploying n8n off this machine?** Change the Fetch node URL to the reachable
  tunnel/domain (and ensure the API is reachable from wherever n8n runs). If you
  want env-var indirection, an admin must unset `N8N_BLOCK_ENV_ACCESS_IN_NODE`.

### Google Sheets credential

Both Sheets nodes use the `Google Sheets account` OAuth credential
(`googleSheetsOAuth2Api`, id `2niz9sSp1GmkddsF`). The HTTP node needs **no**
credential — `/api/events/` is unauthenticated.

### Schedule

The workflow contains a daily 00:00 UTC Schedule Trigger, but is **run manually**
for now — it will not fire on schedule until toggled **Active** in the n8n UI.

### Query parameters (Fetch node)

| Param | Default | Effect |
|---|---|---|
| `limit` | `500` | Max rows per page |
| `page` | _(pagination)_ | Driven by "update a parameter in each request", starts at 1 |
| `scraped_after` | _(unset)_ | Optional ISO 8601 freshness filter |
| `upcoming` | _(unset)_ | Set to `1` to fetch only future events (otherwise all events, past + future, are synced) |

`ordering` is not set, so the endpoint defaults to `-scraped_at` (newest scrapes first).

---

## Verifying the endpoint

Run against the local Django server (use `127.0.0.1`, not `localhost`):

```bash
# 1. Basic shape — results array of 15-field event rows + pagination envelope
curl -s "http://127.0.0.1:8000/api/events/?limit=5" | python3 -m json.tool

# 2. Freshness filter — only rows scraped after a timestamp
curl -s "http://127.0.0.1:8000/api/events/?scraped_after=2026-06-24T00:00:00Z&limit=5" | python3 -m json.tool

# 3. Upcoming only
curl -s "http://127.0.0.1:8000/api/events/?upcoming=1&limit=5" | python3 -m json.tool

# 4. Pagination metadata
curl -s "http://127.0.0.1:8000/api/events/?limit=500&page=1" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(f'total={d[\"total\"]} pages={d[\"pages\"]} page={d[\"page\"]}')"
```

Each row carries the 15 keys: `db_id`, `scraped_at`, `search_term`, `event`,
`event_date`, `organizer_name`, `organizer_email`, `organizer_phone`, `category`,
`location`, `post_link`, `fb_post_id`, `post_date`, `summary`, `raw_text`.

---

## Manual Run verification

After clicking **Manual Run** (verified working on 2026-06-25, ~2,025 rows across 4 pages):

1. **Clear node** — succeeds; `A2:P` is blanked (header row 1 preserved).
2. **Fetch node** — paginates; execution log shows one HTTP call per page; the page
   envelopes report matching `total`/`pages`.
3. **Map node** — each item has all 16 keys including `event_status`; spot-check
   `Upcoming`/`Past` against `event_date`.
4. **Append node** — row count matches `total`; data lands in columns **A–P**,
   correctly aligned; no cell contains the literal string `"null"`.

---

## Filter combination reference

Change the Fetch node query params to scope the sync:

| Use case | Query params |
|---|---|
| Full sync — all events, past + future (default) | `limit=500` |
| Upcoming events only | `upcoming=1&limit=500` |
| Only recently scraped rows | `scraped_after=2026-06-24T00:00:00Z&limit=500` |

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| HTTP node: `ECONNREFUSED ::1:8000` | `localhost` resolved to IPv6; use `127.0.0.1` in the Fetch URL |
| HTTP node: `access to env vars denied` | `$env` blocked by `N8N_BLOCK_ENV_ACCESS_IN_NODE`; hardcode the URL or have an admin unset the flag |
| HTTP node: connection refused | Django not running, or URL not reachable from the n8n host |
| HTTP node: 400 on `scraped_after` | Invalid timestamp — remove it or use ISO 8601 |
| Pagination only fetches page 1 | Completion expression missing — `{{ $response.body.page >= $response.body.pages }}` |
| **All data collapses into one column / shifts to columns past O** | The target tab had a **legacy/mismatched header row or used-range**, so auto-map mis-bound. Fix: use a clean dedicated tab (here, `Events Sync`) and clear `A2:P` (keep the header row) — never clear the whole tab, since wiping headers makes auto-map re-create drifting columns |
| Sheet cells contain `"null"` | Map node missing the null-safe default (`(v === null || v === undefined) ? '' : v`) |
| Clear leaves stale rows | Clear range too narrow — keep it at `A2:P` |
| Append writes 0 rows | API returned 0 results for the current filters |
| Google Sheets: 401 / permission error | OAuth credential not attached or expired — re-authorize in n8n |
| Workflow does not run on schedule | Workflow not Active — toggle Active in the n8n UI |
