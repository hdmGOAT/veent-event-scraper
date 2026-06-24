# Location Bounding — Implementation Plan

**Date:** 23-06-26
**Complexity:** SIMPLE (single session, no DB migration, no new model)

---

## Overview

After selecting keywords in the Scraper Center keyword picker modal, the user proceeds to a
second step that shows location checkboxes (Philippines, Singapore). The chosen locations are
passed as a one-time `locations` list to the run trigger — no persistent server-side state.

When the run fires, the Facebook scraper expands each keyword × each selected location into a
separate Facebook search (e.g. "fun run" + ["philippines"] → one search for "fun run philippines").
If no locations are selected, behaviour is identical to today.

---

## Goals

1. `FacebookEventsScraper.run()` accepts a `locations: list[str] | None` parameter and fans out
   queries × locations when provided.
2. `run_scraper_job` management command gains a `--locations` CLI argument.
3. `trigger_scraper_run` and `api_scraper_trigger` accept and forward an optional `locations` list.
4. The keyword picker modal in `/scrapers/+page.svelte` gains a Step 2 — location checkboxes.
   "Run Selected" is replaced by "Next →" which advances to Step 2; Step 2 has a "Run" button.
5. "Run All Keywords" skips keyword selection but still goes to Step 2 for location selection.

---

## Scope

### In Scope
- `apps/backend/events/scrapers/facebook_events.py` — `run()` signature + expansion loop
- `apps/backend/events/management/commands/run_scraper_job.py` — `--locations` arg
- `apps/backend/events/runner.py` — `trigger_scraper_run` gains `locations` param
- `apps/backend/events/views.py` — `api_scraper_trigger` parses `locations` from POST body
- `apps/frontend/src/lib/types.ts` — no change needed (locations are plain `string[]`)
- `apps/frontend/src/lib/api.ts` — `runScraper` body type gains `locations?: string[]`
- `apps/frontend/src/routes/scrapers/+page.svelte` — two-step keyword+location picker modal

### Out of Scope
- No DB model, migration, or schema change
- No `/search-queries` page changes
- No new settings API endpoint
- No persistent location state on the server
- No changes to any other scraper

---

## Touchpoints

| Layer | File | Change |
|---|---|---|
| Scraper | `apps/backend/events/scrapers/facebook_events.py` | `run(locations=None)` + work_items expansion |
| Management cmd | `apps/backend/events/management/commands/run_scraper_job.py` | `--locations` arg |
| Runner | `apps/backend/events/runner.py` | `trigger_scraper_run(locations=None)` + `--locations` CLI arg |
| View | `apps/backend/events/views.py` | `api_scraper_trigger` parses `locations` |
| Frontend API | `apps/frontend/src/lib/api.ts` | `runScraper` body gains `locations?: string[]` |
| Scrapers page | `apps/frontend/src/routes/scrapers/+page.svelte` | Two-step modal |

---

## Public Contracts

### `POST /api/scrapers/<key>/run/` body schema (extended)
```json
{ "query_ids": [1, 2], "locations": ["philippines", "singapore"] }
```
- `locations` is optional. Omitting it (or passing `[]`) means no location expansion.
- `query_ids` remains optional as before.
- Combined: scraper runs the selected keywords, each expanded by the selected locations.

### `trigger_scraper_run` Python signature (extended)
```python
def trigger_scraper_run(
    key: str,
    triggered_by=None,
    query_id: int | None = None,
    query_ids: list[int] | None = None,
    locations: list[str] | None = None,
) -> tuple[ScraperRun | None, bool]:
```

### `FacebookEventsScraper.run()` signature (extended)
```python
def run(
    self,
    query_id: int | None = None,
    query_ids: list[int] | None = None,
    locations: list[str] | None = None,
    **kwargs,
)
```
- If `locations` is None or `[]`: `work_items = [(sq, "") for sq in queries]` — no expansion
- If locations provided: `work_items = [(sq, loc) for sq in queries for loc in locations]`
- Effective search term: `f"{sq.query} {loc}".strip()`

### `run_scraper_job` CLI
Adds `--locations` argument (comma-separated string). Example:
```bash
manage.py run_scraper_job --run-id 71 --query-ids 33,32 --locations philippines,singapore
```

---

## Available Locations (hardcoded in runner/view/frontend)

```python
AVAILABLE_LOCATIONS = ["philippines", "singapore"]
```

Define this constant in `runner.py` for backend validation; repeat as a frontend constant in
the Svelte page.

---

## Implementation Checklist

### Step 1 — `FacebookEventsScraper.run()` — accept and expand locations

File: `apps/backend/events/scrapers/facebook_events.py`

- Add `locations: list[str] | None = None` to the `run()` signature (after `query_ids`).
- After loading `queries = list(qs)` and before the `if not queries:` early-exit, build
  `work_items`:
  ```python
  active_locs = locations or []
  if active_locs:
      work_items = [(sq, loc) for sq in queries for loc in active_locs]
  else:
      work_items = [(sq, "") for sq in queries]
  ```
- Inside the `with sync_playwright()` block, replace `for sq in queries:` with
  `for sq, location_suffix in work_items:`.
- Compute `effective_term = f"{sq.query} {location_suffix}".strip()` and pass it to
  `_fetch_for_query(page, effective_term, ...)` instead of `sq.query`.
- Results accumulation: use `scraped.setdefault(sq.id, []).extend(cards)` so multiple
  location passes for the same `sq` aggregate rather than overwrite.
- Phase 3 persist loop (`for sq in queries:`) is unchanged — it uses `scraped.get(sq.id, [])`.
- **Before editing, read lines 858–900 to verify exact insertion points.**

### Step 2 — Management command `--locations` argument

File: `apps/backend/events/management/commands/run_scraper_job.py`

- In `add_arguments`, add:
  ```python
  parser.add_argument(
      "--locations", type=str, default=None,
      help="Comma-separated location suffixes to append to each search query.",
  )
  ```
- In `handle`, parse:
  ```python
  raw_locs = options.get("locations")
  locations = [x.strip() for x in raw_locs.split(",") if x.strip()] if raw_locs else None
  ```
- Update the scraper call to pass `locations`:
  ```python
  scraper.run(query_ids=query_ids, locations=locations) if query_ids else
  (scraper.run(query_id=query_id, locations=locations) if query_id else
   scraper.run(locations=locations))
  ```

### Step 3 — `trigger_scraper_run` — forward locations

File: `apps/backend/events/runner.py`

- Add `locations: list[str] | None = None` to `trigger_scraper_run` signature.
- After the `--query-ids` block, add:
  ```python
  if locations:
      cmd += ["--locations", ",".join(locations)]
  ```
- No change to `run_key` logic — locations don't affect the concurrency slot.

### Step 4 — `api_scraper_trigger` — parse locations

File: `apps/backend/events/views.py`

- In `api_scraper_trigger`, after parsing `query_ids`, parse `locations`:
  ```python
  locations = body.get("locations") or None
  if locations is not None:
      if not isinstance(locations, list) or not all(isinstance(l, str) for l in locations):
          return JsonResponse({"error": "locations must be a list of strings"}, status=400)
      unknown = [l for l in locations if l not in ("philippines", "singapore")]
      if unknown:
          return JsonResponse({"error": f"Unknown location: '{unknown[0]}'"}, status=400)
  ```
- Pass `locations=locations` to `trigger_scraper_run(...)`.

### Step 5 — Frontend API type

File: `apps/frontend/src/lib/api.ts`

- Update the `runScraper` body type to include `locations?: string[]`:
  ```typescript
  runScraper: (key: string, body?: { query_ids?: number[]; locations?: string[] }) => ...
  ```
  No other change needed — the body is already forwarded via `postJson`.

### Step 6 — Two-step keyword + location picker modal

File: `apps/frontend/src/routes/scrapers/+page.svelte`

**New state variables** (add alongside existing keyword picker state):
```typescript
let pickerStep = $state<1 | 2>(1);           // 1 = keyword selection, 2 = location selection
let selectedLocations = $state<Set<string>>(new Set());
const AVAILABLE_LOCATIONS = ["philippines", "singapore"];
```

**Update `openKeywordPicker(key)`**: also reset `pickerStep = 1` and `selectedLocations = new Set()`.

**Update `closeKeywordPicker()`**: also reset `pickerStep = 1` and `selectedLocations = new Set()`.

**Rename / update `handleRunWithKeywords(key)`** → `handleRunFinal(key, overrideIds?)`:
- Now passes both `query_ids` and `locations` to `api.runScraper`:
  ```typescript
  const ids = overrideIds ?? [...selectedKeywordIds];
  const locs = [...selectedLocations];
  await api.runScraper(key, {
    query_ids: ids,
    ...(locs.length > 0 ? { locations: locs } : {}),
  });
  ```
- After triggering, call `closeKeywordPicker()`.

**Step 1 modal content** (keyword checklist — existing markup):
- Replace the current "Run Selected" button with a **"Next →"** button:
  - Disabled if `selectedKeywordIds.size === 0`
  - `onclick={() => (pickerStep = 2)}`
- Replace the current "Run All Keywords" button with a **"Select All → Next"** button:
  - Selects all active keyword IDs into `selectedKeywordIds`, then sets `pickerStep = 2`
- Keep "Cancel" button unchanged.

**Step 2 modal content** (location checklist — new markup, shown when `pickerStep === 2`):
- Header: "Select locations"
- Subtext: "Each selected keyword will be searched once per location."
- Checklist of `AVAILABLE_LOCATIONS`:
  ```html
  {#each AVAILABLE_LOCATIONS as loc}
    <label class="flex items-center gap-2 text-sm text-text cursor-pointer">
      <input
        type="checkbox"
        checked={selectedLocations.has(loc)}
        onchange={(e) => {
          if (e.currentTarget.checked) selectedLocations.add(loc);
          else selectedLocations.delete(loc);
          selectedLocations = selectedLocations; // trigger reactivity
        }}
        class="accent-accent"
      />
      <span class="capitalize">{loc}</span>
    </label>
  {/each}
  ```
- "Run" button: always enabled (locations are optional — 0 selected = no expansion)
  - `onclick={() => handleRunFinal(keywordPickerKey!)}`
- "← Back" button: `onclick={() => (pickerStep = 1)}`
- "Cancel" button: `onclick={closeKeywordPicker}`
- Show selected keyword count as context: "Running {selectedKeywordIds.size} keyword(s)"

**Modal shell**: use `{#if pickerStep === 1}` / `{:else}` to swap content within the same
overlay `<div>` — no animation needed, same overlay stays visible.

---

## Acceptance Criteria

1. `POST /api/scrapers/facebook_events/run/` with `{"query_ids": [33], "locations": ["philippines"]}` returns 200.
2. Backend log for that run shows `search 'CPD seminar philippines': N cards` — location suffix appended.
3. `POST` with `{"locations": ["mars"]}` returns 400 `{"error": "Unknown location: 'mars'"}`.
4. `POST` with `{"locations": []}` or omitting `locations` entirely — run executes with no expansion (current behaviour).
5. Clicking "Run" on the Facebook card opens Step 1 (keyword checklist).
6. Clicking "Next →" with keywords selected advances to Step 2 (location checklist).
7. Clicking "← Back" returns to Step 1 with keyword selections preserved.
8. Clicking "Run" in Step 2 triggers the run with both `query_ids` and `locations`.
9. Clicking "Run" in Step 2 with no locations checked triggers the run with no expansion.
10. `pnpm --filter frontend check` passes with 0 errors.
11. `manage.py test events` passes with 0 failures.

---

## Verification Evidence

```bash
# Backend API
curl -X POST http://localhost:8000/api/scrapers/facebook_events/run/ \
  -H "Content-Type: application/json" \
  -d '{"query_ids": [33, 32], "locations": ["philippines"]}'
# Expected: 200 {"id": N, "status": "queued"}

# After run completes, check log:
curl -s http://localhost:8000/api/scrapers/runs/N/ | python3 -c "
import json,sys; r=json.load(sys.stdin)
for l in r['log_output'].split('\n'):
    if 'search' in l: print(l)
"
# Expected: lines containing 'CPD seminar philippines' and 'CPD units philippines'

# Bad location
curl -X POST http://localhost:8000/api/scrapers/facebook_events/run/ \
  -H "Content-Type: application/json" \
  -d '{"locations": ["mars"]}'
# Expected: 400

# Frontend type-check
pnpm --filter frontend check
```

---

## Resume Handoff

**Plan path:** `process/general-plans/active/location-bounding_PLAN_23-06-26.md`

Execute steps 1 → 2 → 3 → 4 → 5 → 6 in order.
Steps 1–4 are backend and are independent of steps 5–6.
Step 6 depends on step 5 (api.ts type update).
