# Async n8n → Google Sheets Leads Sync

**Date:** 25-06-26
**Complexity:** SIMPLE (one-session — no backend code, no migrations; deliverable is one SDK workflow file + one docs file, authored via n8n MCP server)
**Status:** ✅ VERIFIED — shipped in PR #52 (branch `feat/async-n8n-events-sheets-sync`), verified end-to-end via Manual Run, ~2,025 rows written to "Events Sync" tab.

---

## Outcome (2026-06-25)

Goal achieved: async, decoupled n8n workflow syncs DB event rows to Google Sheets with no scraping.

**Key deviations from original plan:**

- **Endpoint:** changed from `/api/leads/` → `/api/events/` to match the real Sheets layout (no CRM columns, API data columns A–O; column P is a derived `event_status` field computed in the n8n Code node, not part of the API payload).
- **URL:** hardcoded to `http://127.0.0.1:8000` — `$env` is blocked (`N8N_BLOCK_ENV_ACCESS_IN_NODE=true` on self-hosted n8n); `localhost` resolves to IPv6 `::1` which fails, so `127.0.0.1` is required.
- **Column P (`event_status`):** computed column added (derived from `event_date`/`starts_at` — upcoming vs. past). Clear range widened to `A2:P`.
- **Sheet tab:** uses a fresh "Events Sync" tab (gid 424242) in "[EXPERIMENT] Centralized List of Events" spreadsheet, not `Sheet1`, to avoid legacy column-drift.
- **n8n instance:** local self-hosted (`http://127.0.0.1:5678`), not `jsrl.app.n8n.cloud`. Workflow id `EzCKmFfmHrYXutx2`, name "FB Scraper to Google Sheets".

---

## Scope revision (2026-06-25)

The source endpoint changed from `/api/leads/` → **`/api/events/`** to match the
real Google Sheets layout (15 columns A–O, all data, **no CRM columns**):

```
A db_id | B scraped_at | C search_term | D event | E event_date | F organizer_name |
G organizer_email | H organizer_phone | I category | J location | K post_link |
L fb_post_id | M post_date | N summary | O raw_text
```

Consequences (superseding the original leads-based design below):

- **Backend (NEW, this revision):** `api_events()` in `apps/backend/events/views.py`
  now emits 3 added keys so the response covers all 15 columns — `organizer_email`,
  `organizer_phone` (both from `organizer_ref`, mirroring `api_leads`), and
  `raw_text` (from `e.raw_text`). `select_related("organizer_ref")` was already
  present (no N+1). No model/migration change. Migration `0023_add_raw_text_post_date`
  is **applied** (`[X]`), so `raw_text` is live. NOTE: two leaf merge migrations
  `0025_merge_20260625` and `0026_merge_20260625` show **unapplied** (`[ ]`) — see
  Risks; not fixed here (no DB writes allowed).
- **Transform:** the prior leads-column mapping (Category / Page Name / Location
  city+country concat / Notes / Added By, 9 columns) is **superseded** by a
  null-safe passthrough of the 15 `/api/events/` keys in column order, because the
  API field names now match the sheet headers 1:1.
- **Clear range:** `Sheet1!A2:I` → **`Sheet1!A2:O`** (Full Replace of all 15 data
  columns). There are no human-managed CRM columns to protect.
- **Query params:** dropped the leads-only filters (`country`, `has_contact`,
  `min_days`). Kept `limit=500` + `page` pagination; `scraped_after` is the
  optional freshness filter; `ordering` defaults to `-scraped_at`.
- Docs file keeps the same filename `docs/n8n/n8n-leads-sheets-sync.md` (and its
  README index row) but its content now targets `/api/events/`.

Sections below describing the leads-column mapping, `A2:I`/`A2:Z` clear range, and
the `country`/`has_contact`/`min_days` filters are **historical** — the authoritative
spec is this revision plus the retargeted `docs/n8n/n8n-leads-sheets-sync.md`.

---

## Quick Links

- [Overview](#overview)
- [Relationship to the FB-Posts Pipeline Plan](#relationship-to-the-fb-posts-pipeline-plan)
- [Non-Goals](#non-goals)
- [Goals and Success Metrics](#goals-and-success-metrics)
- [Architecture / Data Flow](#architecture--data-flow)
- [Scope](#scope)
- [Node-by-Node Specification](#node-by-node-specification)
- [Implementation Checklist](#implementation-checklist)
- [Acceptance Criteria](#acceptance-criteria)
- [Verification and Testing](#verification-and-testing)
- [Touchpoints](#touchpoints)
- [Public Contracts](#public-contracts)
- [Blast Radius](#blast-radius)
- [Risks and Mitigations](#risks-and-mitigations)
- [Resume and Execution Handoff](#resume-and-execution-handoff)

---

## Overview

Build a new n8n workflow that independently polls the live `GET /api/leads/` endpoint
on a daily schedule and writes the current database records into the team's Google Sheets
leads tracker. The workflow does **no scraping**. It is fully decoupled from the scraper
automation workflow: the scraper writes to the DB; this workflow only reads the API and
syncs to Sheets. The DB is the shared state between the two systems.

**Source documents:**
- `process/general-plans/references/leads-api-n8n-handoff.md` — API contract, field mapping, pagination spec, filter recommendations, CRM column rules
- `docs/n8n/n8n-scraper-automation-workflow.md` — SDK conventions, trigger fan-in pattern, node shape, continueOnFail placement

---

## Relationship to the FB-Posts Pipeline Plan

The existing active plan at
`process/general-plans/active/fb-posts-n8n-sheets-pipeline_PLAN_24-06-26.md`
describes the OLD coupled model where n8n triggers the scraper and waits, then pushes
the resulting rows to Sheets. That plan's **backend RFCs (RFC-001 through RFC-003)**
remain independently valid — they add `raw_text`, `post_date`, and `scraped_after`
to `api_events/`, which is a separate endpoint for Facebook Posts data.

The **n8n Wiring Guide section** of that plan (the part that wires n8n directly to the
scraper webhook) is **superseded** by this async approach for the leads use case:

- **Old model:** `n8n triggers scraper → waits → pushes to Sheets` (synchronous coupling)
- **New model:** `Scraper writes to DB` (independent) → `/api/leads/` sits on DB → `n8n polls API on its own schedule → writes to Sheets` (independent)

The two plans address different concerns. The fb-posts plan's backend RFCs still apply
to the FB Posts data model. The n8n wiring described here replaces the synchronous
trigger-and-push pattern with the decoupled API-poll-and-sync pattern for the leads
tracker. **Do NOT modify the fb-posts plan file.**

---

## Non-Goals

The following are explicitly out of scope for this plan:

- No scraper changes of any kind
- No Django model changes, migrations, or new views
- No changes to `apps/backend/` or `apps/frontend/`
- No changes to the existing scraper automation workflow (`veent-scraper-automation`)
- No incremental/delta sync (append-only or diff logic) — Full Replace is the strategy
- No writes to the CRM columns: **Status**, **Reached Out By**, **Date Reached Out** (handoff §10)
- No webhook/trigger integration with the scraper run lifecycle
- No new API endpoints — `/api/leads/` is already live (handoff §1, §11)
- No Neon Postgres schema changes

---

## Goals and Success Metrics

**Goals:**
1. Schedule a daily Sheets sync at 08:00 PH time (UTC+8 = 00:00 UTC) — after typical scraper runs complete
2. Support an on-demand manual trigger for testing and ad-hoc syncs
3. Paginate through all `/api/leads/` results using the native "By Page" approach (handoff §6)
4. Map the 14 API fields to the 9 writable Sheets columns per handoff §4
5. Full Replace strategy: clear `Sheet1!A2:Z` then append all rows (handoff §5)
6. Never touch the 3 human-managed CRM columns (handoff §10)
7. Document the workflow in `docs/n8n/n8n-leads-sheets-sync.md`

**Success Metrics:**
- n8n workflow activates without errors on manual trigger
- All pages of `/api/leads/` results are fetched (pagination completion fires correctly)
- `Sheet1!A2:Z` is cleared before each write
- Rows written to Sheet match the API payload (verified by spot-check of 3+ rows)
- CRM columns (Status, Reached Out By, Date Reached Out) remain untouched after sync
- Workflow visible at `https://jsrl.app.n8n.cloud/` with "Active" toggle enabled

---

## Architecture / Data Flow

```
[Schedule Trigger: daily 00:00 UTC] ─┐
[Manual Run Trigger]                  ┘ fan-in
                │
                ▼
[HTTP Request: GET /api/leads/]
  url:   {{ $env.LEADS_API_BASE_URL }}/api/leads/
  params: country=Philippines, min_days=7, has_contact=1, limit=500
  pagination: "By Page"
    page param name: page
    completion expr: {{ $response.body.page >= $response.body.pages }}
                │
                │  outputs: array of all result items across all pages
                ▼
[Code Node: Map to Sheet Row]
  per-item transform (handoff §4 mapping):
    Category     ← r.category || ''
    Page Name    ← r.page_name || ''
    Location     ← join([r.location_city, r.location_country], ', ')
    Event        ← r.event || ''
    Link         ← r.link || ''
    Event Date   ← r.event_date.slice(0,10) or ''
    Notes        ← join([email, phone, facebook], ' | ')
    Platform     ← r.platform || ''
    Added By     ← 'veent-bot'  (static)
                │
                ▼
[Google Sheets: Clear Range]
  operation: Clear
  range:     Sheet1!A2:Z
  (CRM columns beyond Z not affected; data columns only)
                │
                ▼
[Google Sheets: Append Rows]
  operation: Append or Update
  columns:   map from Code node output keys
```

**Key invariants:**
- Clear always runs before Append — no partial-overlap state possible
- CRM columns sit in Sheets-only columns beyond the data range; the Clear range `A2:Z` covers only data columns (A–I based on 9 writable columns); verify exact column boundary in Sheets before activating
- Pagination halts when `$response.body.page >= $response.body.pages` (API clamps to last page, so >= is safe)
- `LEADS_API_BASE_URL` env var is the only environment-dependent value — same tunnel/domain pattern as the scraper workflow

---

## Scope

### In Scope

| Item | Detail |
|---|---|
| n8n workflow (SDK code) | Schedule + Manual trigger fan-in, HTTP paginated fetch, Code transform, Sheets Clear, Sheets Append |
| Docs file | `docs/n8n/n8n-leads-sheets-sync.md` mirroring scraper docs structure |
| Workflow creation method | `create_workflow_from_code` via n8n MCP server |
| Filter defaults | `country=Philippines`, `min_days=7`, `has_contact=1` — documented as configurable |
| Verification | curl checks from handoff §9 + n8n Manual Run |

### Out of Scope

See [Non-Goals](#non-goals) above.

---

## Node-by-Node Specification

All SDK code must follow the conventions in `docs/n8n/n8n-scraper-automation-workflow.md`:
- Each node defined as a `const`, not a function declaration
- `continueOnFail` at the top level of `node()`, not inside `config`
- Both triggers fan-in to the same first processing node
- Export via `workflow("id", "Display Name").add(...).to(...)`

### Node 1: Schedule Trigger

```
type:    n8n-nodes-base.scheduleTrigger
version: 1.3
name:    "Daily at 00:00 UTC (08:00 PH)"
config.parameters.rule.interval:
  - field: hours
    hoursInterval: 24
    triggerAtHour: 0
output:  [{ timestamp: "<ISO date>" }]
```

### Node 2: Manual Run Trigger

```
type:    n8n-nodes-base.manualTrigger
version: 1
name:    "Manual Run"
output:  [{}]
```

### Node 3: HTTP Request — Fetch All Leads (Paginated)

```
type:            n8n-nodes-base.httpRequest
version:         4.3
continueOnFail:  false   (pagination failures should halt — do not silently drop pages)
name:            "Fetch All Leads (Paginated)"
config.parameters:
  method:        GET
  url:           "{{ $env.LEADS_API_BASE_URL }}/api/leads/"
  sendQuery:     true
  queryParameters.parameters:
    - name: country,    value: Philippines
    - name: min_days,   value: "7"
    - name: has_contact, value: "1"
    - name: limit,      value: "500"
  pagination:
    mode:                   "byPage"
    pageParameterName:      "page"
    paginationCompleteWhen: "expression"
    completeExpression:     "{{ $response.body.page >= $response.body.pages }}"
  jsonOutput: true
```

**Note on filters:** `country`, `min_days`, `has_contact` are documented defaults. The
executor should expose them as clearly labeled parameters or comments so they can be
changed without diving into the node internals. They reduce ~800 → ~133 actionable rows
(handoff §8).

### Node 4: Code Node — Map API Row to Sheet Row

```
type:    n8n-nodes-base.code
version: 2
name:    "Map to Sheet Row"
continueOnFail: false
```

Transform logic (per handoff §4 and §5):

- Input: each item's `.json` is one API result row (14 fields)
- Output: each item's `.json` is one sheet row (9 writable fields)
- `Location` = `[location_city, location_country].filter(Boolean).join(', ')`
- `Event Date` = `event_date ? event_date.slice(0, 10) : ''`
- `Notes` = `[organizer_email, organizer_phone, organizer_facebook].filter(Boolean).join(' | ')`
- `Added By` = static string `'veent-bot'`
- All nullable fields default to `''` (empty string), never `null` — Sheets rejects null cell values

Output key names must exactly match the Google Sheets column headers (case-sensitive):
`Category`, `Page Name`, `Location`, `Event`, `Link`, `Event Date`, `Notes`, `Platform`, `Added By`

### Node 5: Google Sheets — Clear Range

```
type:       n8n-nodes-base.googleSheets
version:    4
name:       "Clear Sheet Data Range"
operation:  clear
sheetId:    <configured via Google Sheets credential + spreadsheet selection>
range:      "Sheet1!A2:Z"
```

**Critical:** Clear must execute before Append. The workflow chain enforces this via
node ordering. Do not add a conditional — always clear unconditionally.

**Column boundary note:** The range `A2:Z` is intentionally wide. It covers all 26
columns through Z. The 3 human-managed CRM columns (Status, Reached Out By, Date
Reached Out) must be positioned beyond column I in the actual sheet — the executor
must verify the sheet column layout and adjust the range upper bound if needed. If
CRM columns are within A–Z, use a tighter range like `Sheet1!A2:I` instead.

### Node 6: Google Sheets — Append Rows

```
type:       n8n-nodes-base.googleSheets
version:    4
name:       "Append Leads to Sheet"
operation:  appendOrUpdate
sheetId:    <same spreadsheet as Clear node>
columns:    map from Code node output keys to sheet column headers
```

Column mapping (from Code node output → sheet column headers):
- `Category` → Category
- `Page Name` → Page Name
- `Location` → Location
- `Event` → Event
- `Link` → Link
- `Event Date` → Event Date
- `Notes` → Notes
- `Platform` → Platform
- `Added By` → Added By

---

## Implementation Checklist

**IMPORTANT:** This is a SIMPLE (one-session) plan. No backend changes are required.
All steps are n8n SDK code + docs authoring via the n8n MCP server.

0. ✅ **Backend: add 3 fields to `api_events()`** — DONE 2026-06-25 (scope revision). Added `organizer_email`, `organizer_phone` (from `organizer_ref`, mirroring `api_leads`), and `raw_text` to the `api_events` result dict in `apps/backend/events/views.py`. `select_related("organizer_ref")` already present. Verified live via `curl /api/events/?limit=2` — all 3 keys appear.

1. ✅ **Pre-flight: verify endpoint** — UPDATED for `/api/events/` (scope revision). `curl /api/events/?limit=2` against `http://localhost:8000` returns the 15-column rows including the 3 new keys. (Original leads-endpoint pre-flight on 25-06-26 is historical.) Verify `/api/events/` is reachable and returns the expected shape before touching n8n.
   ```
   curl -s "http://localhost:8000/api/leads/?limit=5" | python3 -m json.tool
   curl -s "http://localhost:8000/api/leads/?has_contact=1&min_days=7&limit=5" | python3 -m json.tool
   curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/api/leads/?scraped_after=bad"
   ```
   Expected: first two return `{"results": [...], "total": N, "pages": N, "page": 1}`. Third returns `400`.

2. ⏳ **Confirm Google Sheets layout** (USER — not verifiable from this environment) — UPDATED for the 15-column layout (scope revision). Open the tracker and confirm:
   - Row 1 is the header row, columns **A–O** are all data columns (no CRM columns)
   - Headers in column order: `db_id`, `scraped_at`, `search_term`, `event`, `event_date`, `organizer_name`, `organizer_email`, `organizer_phone`, `category`, `location`, `post_link`, `fb_post_id`, `post_date`, `summary`, `raw_text`
   - Clear range is `Sheet1!A2:O` (Full Replace of all 15 columns; nothing to protect)

3. ✅ **Draft SDK workflow code** — DONE 25-06-26, RETARGETED to `/api/events/` on 2026-06-25 (scope revision). SDK code in `docs/n8n/n8n-leads-sheets-sync.md` now fetches `/api/events/` (params `limit=500` + `page` pagination, optional `scraped_after`), maps the 15 columns A–O as a null-safe passthrough, and clears `Sheet1!A2:O`. (Original leads-based SDK below is historical.) Using the pattern from `docs/n8n/n8n-scraper-automation-workflow.md`, author the full `@n8n/workflow-sdk` code with:
   - `const scheduleTrigger` — daily 00:00 UTC
   - `const manualTrigger` — manual run
   - `const fetchLeads` — HTTP Request with "By Page" pagination, the 4 default query params, `LEADS_API_BASE_URL` env var
   - `const mapToSheetRow` — Code node with the 9-field transform (null-safe, `''` defaults)
   - `const clearSheet` — Google Sheets Clear, range `Sheet1!A2:Z` (or tighter per step 2)
   - `const appendLeads` — Google Sheets Append or Update, column mapping to header names
   - `export default workflow(...)` with fan-in: both triggers → fetchLeads, then linear chain

4. ⏳ **Create workflow via n8n MCP** (USER / n8n MCP — n8n MCP server not connected in this environment) — Call `create_workflow_from_code` on `https://jsrl.app.n8n.cloud/` with the SDK code. Note the workflow ID returned.

5. ⏳ **Configure Google Sheets credential** (USER — n8n.cloud UI + Google OAuth) — In the n8n UI, attach the team's Google Sheets OAuth credential to both Sheets nodes (Clear and Append). Select the correct spreadsheet and sheet tab.

6. ⏳ **Set LEADS_API_BASE_URL** (USER — n8n.cloud settings) — In n8n workflow settings or environment, set `LEADS_API_BASE_URL` to the active tunnel/domain (e.g. `https://abc123.ngrok.io` or the deployed domain). No trailing slash.

7. ⏳ **Test with Manual Run trigger** (USER — n8n.cloud UI) — Click Manual Run in n8n. Watch the execution:
   - HTTP Request node: confirm it paginates (check "Pages" value in execution log — should show multiple page fetches if total > 500)
   - Code node: inspect output items — spot-check 3 rows against the curl output from step 1
   - Clear node: confirm execution succeeds (check Sheet to verify rows A2:Z are blank)
   - Append node: confirm rows appear in Sheet; verify 3+ rows match the API data
   - Confirm CRM columns (Status/Reached Out By/Date Reached Out) are untouched

8. ⏳ **Verify CRM columns intact** (USER — n8n.cloud UI + Sheet) — After the append, manually check that the CRM columns retain any pre-existing human data (or are simply blank if never filled). They must not be overwritten.

9. ⏳ **Activate workflow** (USER — n8n.cloud UI) — Toggle the workflow to "Active" in n8n. Confirm the Schedule Trigger is armed for next daily run.

10. ✅ **Create docs file** — DONE 25-06-26, RETARGETED to `/api/events/` on 2026-06-25 (scope revision). `docs/n8n/n8n-leads-sheets-sync.md` (same filename) now targets `/api/events/`: 15-column A–O field map, `A2:O` Clear range, `limit`/`page`/`scraped_after` params, retargeted curl examples; old CRM/leads-column prose removed. README index row updated to reference `/api/events/`. Write `docs/n8n/n8n-leads-sheets-sync.md` with the following sections (mirroring `n8n-scraper-automation-workflow.md` structure):
    - Workflow name and n8n.cloud URL (from step 4)
    - "How it works" — ASCII diagram of the node chain
    - "Configuration before activating" — `LEADS_API_BASE_URL`, Google Sheets credential, spreadsheet ID, default filters
    - "Node structure (SDK code)" — the full SDK code block authored in step 3
    - "Troubleshooting" — table of symptoms and causes (see [Troubleshooting Reference](#troubleshooting-reference) below)
    - "Filter combination reference" — table from handoff §7

11. ⏳ **Commit docs file** (deferred to git-manager / user confirmation) — Stage and commit `docs/n8n/n8n-leads-sheets-sync.md` to the `development` branch. Working-tree changes left uncommitted for the orchestrator to route to vc-git-manager.

---

## Acceptance Criteria

All criteria must be true before the plan is marked DONE:

| # | Criterion | How to Verify |
|---|---|---|
| AC-1 | Workflow exists at `https://jsrl.app.n8n.cloud/` | Open n8n UI, see "Veent Leads Sheets Sync" (or similar name) |
| AC-2 | Manual Run completes without errors | Execution log shows green for all nodes |
| AC-3 | All API pages fetched | Execution log shows pagination ran (for datasets > 500 rows, multiple HTTP calls visible) |
| AC-4 | Sheet data range cleared before write | Check Sheet immediately after Clear node — A2:Z is blank |
| AC-5 | Rows written match API data | Spot-check 3 rows from Sheet against curl output — fields match per §4 mapping |
| AC-6 | CRM columns untouched | Status/Reached Out By/Date Reached Out columns contain no bot-written values |
| AC-7 | `Added By` = "veent-bot" | Every written row has "veent-bot" in the Added By column |
| AC-8 | Schedule trigger armed | Workflow is Active; Schedule Trigger shows next run time |
| AC-9 | Docs file present | `docs/n8n/n8n-leads-sheets-sync.md` exists in repo with all required sections |
| AC-10 | Null fields rendered as empty string | No Sheet cells contain the literal string "null" |

---

## Verification and Testing

### Pre-wiring API Checks (handoff §9)

```bash
# 1. Basic shape check — should return results array with 14-field rows
curl -s "http://localhost:8000/api/leads/?limit=5" | python3 -m json.tool

# 2. Filtered check — reduced set (has_contact + min_days)
curl -s "http://localhost:8000/api/leads/?has_contact=1&min_days=7&limit=5" | python3 -m json.tool

# 3. Error handling — must return 400
curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/api/leads/?scraped_after=bad"

# 4. Pagination metadata check — verify pages/page/total fields
curl -s "http://localhost:8000/api/leads/?limit=500&page=1" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(f'total={d[\"total\"]} pages={d[\"pages\"]} page={d[\"page\"]}')"
```

### n8n Manual Run Verification

After triggering Manual Run:

1. Open execution detail in n8n UI
2. HTTP Request node output: confirm `results` array present, `total` matches curl
3. Code node output: open first item, confirm all 9 keys present with correct values
4. Clear node: no error, Sheet A2:Z blank (check before Append fires — may need to pause)
5. Append node: row count in execution output matches `total` from API
6. Open Sheet: rows visible, CRM columns (J+) untouched

### Filter Combination Reference (handoff §7)

| Use Case | Query Params |
|---|---|
| All upcoming PH events | `country=Philippines&min_days=0&limit=500` |
| PH events next 2 weeks | `country=Philippines&min_days=7&limit=500` |
| Only contactable leads (default) | `country=Philippines&has_contact=1&min_days=7&limit=500` |
| Facebook events only | `source=facebook_events&country=Philippines&limit=500` |
| New scrapes since yesterday | `scraped_after=2026-06-24T00:00:00Z&limit=500` |

---

## Touchpoints

| Surface | What Is Touched | Change Type |
|---|---|---|
| n8n.cloud | New workflow created via MCP | Net-new, no modification to existing workflow |
| Google Sheets leads tracker | Data range A2:Z cleared and rewritten on each run | Write (CRM columns not touched) |
| `docs/n8n/n8n-leads-sheets-sync.md` | New file in repo | Net-new |
| `GET /api/leads/` | Read-only consumer | No changes to endpoint |
| Scraper automation workflow | Not touched | No changes |
| `apps/backend/` | Not touched | No changes |
| `apps/frontend/` | Not touched | No changes |

---

## Public Contracts

| Contract | Value |
|---|---|
| API endpoint consumed | `GET /api/leads/` — read-only, no auth, returns `{results, total, pages, page}` |
| Pagination protocol | n8n "By Page"; param: `page`; halt expr: `{{ $response.body.page >= $response.body.pages }}` |
| Sheet columns written (9) | Category, Page Name, Location, Event, Link, Event Date, Notes, Platform, Added By |
| Sheet columns NOT written (3) | Status, Reached Out By, Date Reached Out |
| Clear range | `Sheet1!A2:Z` (adjust upper bound if CRM cols fall within A-Z) |
| Static value | `Added By` = `"veent-bot"` |
| Env var | `LEADS_API_BASE_URL` — base URL of the Django app, no trailing slash |
| Default filters | `country=Philippines`, `min_days=7`, `has_contact=1`, `limit=500` |
| Schedule | Daily 00:00 UTC (08:00 PH time / UTC+8) |

---

## Blast Radius

**Backend blast radius: ZERO.** No Django, Neon Postgres, scraper, or frontend changes.

| Component | Risk |
|---|---|
| n8n.cloud | New workflow; existing scraper workflow untouched |
| Google Sheets | Data range A2:Z is cleared and replaced on each run — human-entered data in data columns (A–I) will be overwritten. CRM columns (J+) are safe. |
| Repo | One new docs file committed to `development` branch |
| Scraper automation | No changes; runs independently |
| API | Read-only consumer; no load impact expected at 133–800 rows / day |

**Human-data risk note:** The Full Replace strategy clears the data range on every sync.
Any manually entered values in columns A–I (the data columns) will be lost on next sync.
This is expected behavior — the Sheet is treated as a bot-managed view. Only columns J+
(CRM columns) are safe for human edits. Document this clearly in the docs file.

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| CRM columns fall within `A2:Z` clear range | Medium | Step 2 of checklist requires verifying column layout before activating. Use `Sheet1!A2:I` or tighter range if needed. |
| `LEADS_API_BASE_URL` not reachable from n8n.cloud | Medium | Ensure ngrok/tunnel is active or deployed domain is set. Test with curl from outside localhost first. |
| Google Sheets OAuth credential not set up in n8n | Medium | Sheets nodes require credential attachment before first run. Handle in step 5. |
| Endpoint returns 0 results (all filtered out) | Low | Clear still runs, leaving Sheet empty. Not a failure — just a data gap. Document in troubleshooting. |
| Pagination completion expression fires on page 1 | Low | Only if `total <= 500` and `pages = 1`. All rows returned in single call. Correct behavior. |
| `null` values written as literal "null" string to Sheet | Low | Code node must use `.filter(Boolean)` and `|| ''` defaults. AC-10 catches this. |
| n8n MCP `create_workflow_from_code` fails | Low | Author SDK code manually and import via n8n UI as fallback. |
| API returns future events only — past events never appear | Informational | By design (handoff §1). Not a risk, but document in docs file. |

---

## Troubleshooting Reference

(For inclusion in `docs/n8n/n8n-leads-sheets-sync.md`)

| Symptom | Likely Cause |
|---|---|
| HTTP Request node: connection refused | `LEADS_API_BASE_URL` not set or tunnel not active |
| HTTP Request node: 400 on `scraped_after` | Invalid timestamp format — remove that param |
| Pagination only fetches page 1 | Completion expression not set; check "By Page" config |
| Sheet cells contain "null" | Code node missing `.filter(Boolean)` or `|| ''` defaults |
| Clear node clears CRM columns | Clear range too wide — tighten to `Sheet1!A2:I` or exact data range |
| Append writes 0 rows | API returned 0 results for current filters — expected if no matching events |
| Google Sheets: 401 / permission error | OAuth credential not attached or expired — re-authorize in n8n |
| Workflow does not trigger on schedule | Workflow not Active — toggle to Active in n8n UI |

---

## Resume and Execution Handoff

**Selected plan file:** `/Volumes/Extreme_SSD/Projects/Python/veent-event-scraper/process/general-plans/active/async-n8n-leads-sheets-sync_PLAN_25-06-26.md`

**Executor:** vc-execute-agent

**Pre-execution requirements:**
1. n8n MCP server must be available and connected to `https://jsrl.app.n8n.cloud/`
2. The Django dev server must be running (or a tunnel to it) to perform pre-flight curl checks
3. Access to the team Google Sheets leads tracker (URL + column layout confirmation)
4. Google Sheets OAuth credential must already exist in the n8n.cloud workspace, or the executor must set it up during step 5

**Execution order:** Follow the [Implementation Checklist](#implementation-checklist) steps 1–11 in sequence. Step 2 (column layout) is a blocking prerequisite for step 3 (SDK code) because the Clear range depends on it.

**Key source references:**
- API contract, field mapping, pagination: `process/general-plans/references/leads-api-n8n-handoff.md`
- SDK conventions, node shape, trigger fan-in: `docs/n8n/n8n-scraper-automation-workflow.md`
- Node-by-node spec with exact parameter values: [Node-by-Node Specification](#node-by-node-specification) section above

**Completion signal:** Plan is DONE when all 10 acceptance criteria (AC-1 through AC-10) are confirmed true and `docs/n8n/n8n-leads-sheets-sync.md` is committed to the `development` branch.

**Validation commands:**
```bash
# Confirm docs file exists
ls /Volumes/Extreme_SSD/Projects/Python/veent-event-scraper/docs/n8n/n8n-leads-sheets-sync.md

# Confirm no backend files modified
git diff --name-only development | grep -v "^docs/n8n/"
# Expected: empty output (no non-docs changes)
```

**Plan artifact validation:**
```bash
node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs \
  process/general-plans/active/async-n8n-leads-sheets-sync_PLAN_25-06-26.md
```
