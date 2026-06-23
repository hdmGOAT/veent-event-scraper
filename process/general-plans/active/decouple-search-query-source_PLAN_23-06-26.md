# Decouple SearchQuery from Hardcoded Scraper Source

**Date:** 23-06-26
**Complexity:** SIMPLE (one-session)
**Status:** PLANNED

---

## Overview

`SearchQuery` rows currently carry a required `source` field that locks each keyword
to a specific scraper (e.g. `"facebook_events"`). This prevents keywords from being
reused across scrapers and makes the Scraper Center unable to show a keyword picker at
run time. The goal is to make `source` optional so keywords become scraper-agnostic,
update `FacebookEventsScraper` to load all active keywords (or a caller-supplied list),
add a keyword multi-select to the Scraper Center "Run" button for the Facebook scraper,
and clean the Add-Query form on `/search-queries` of the now-unnecessary source input.

A reusability hook is included so other scrapers can opt into keyword selection in future
with a single attribute.

---

## Goals

1. `SearchQuery.source` becomes optional — existing rows keep their values for provenance;
   new rows get `source=""` by default.
2. `UniqueConstraint` changes from `["source", "query"]` to `["query"]` so the same
   keyword cannot be added twice regardless of source.
3. `FacebookEventsScraper.run()` loads all active `SearchQuery` rows (no source filter) or
   a caller-supplied list of `query_ids`.
4. `POST /api/scrapers/<key>/run/` accepts an optional `query_ids: list[int]` body param and
   forwards it to `trigger_scraper_run`.
5. `trigger_scraper_run` accepts `query_ids: list[int] | None` alongside the existing scalar
   `query_id`; when `query_ids` is given, a single `ScraperRun` is created whose subprocess
   receives `--query-ids <id1>,<id2>,...`.
6. `POST /api/search-queries/` makes `source` optional (returns 400 only if `query` is missing).
7. Scraper Center (`/scrapers`): "Run" button on the `facebook_events` card opens a keyword
   multi-select modal; only selected IDs are passed in `query_ids` when triggering the run.
8. `/search-queries` Add form: remove the source text input. Existing source column in the
   table stays read-only.
9. Reusability hook: scrapers declare `supports_keywords = True` on their class; the Scraper
   Center reads this flag from a new `supports_keywords` field on `/api/scrapers/` to decide
   whether to show the keyword picker.

---

## Scope

**In-scope:**
- Django migration 0022 (make `source` blank/default, update unique constraint)
- `FacebookEventsScraper.run()` keyword loading change
- `runner.py` `trigger_scraper_run` — add `query_ids` list parameter
- `run_scraper_job` management command — add `--query-ids` argument
- `api_scraper_trigger` view — accept `query_ids` from POST body
- `api_search_queries` POST — make `source` optional
- `/api/scrapers/` response — add `supports_keywords` per key
- `apps/frontend/src/lib/api.ts` — update `runScraper` signature
- `apps/frontend/src/lib/types.ts` — update `Scraper` type
- `/scrapers/+page.svelte` — keyword picker modal for facebook_events
- `/search-queries/+page.svelte` — remove source input from Add form
- Backend tests for changed view logic and migration safety
- Frontend type-check (`pnpm --filter frontend check`)

**Out-of-scope:**
- Dropping the `source` column
- Migrating existing `SearchQuery.source` values to blank
- Other scrapers actually using keywords (the hook is present; usage is future work)
- Auth changes

---

## Touchpoints

| Layer | File | What changes |
|---|---|---|
| DB schema | `apps/backend/events/migrations/0022_*.py` | `source` blank+default, new unique constraint |
| Model | `apps/backend/events/models.py` lines 241–258 | `source` field options, `Meta.constraints`, `ordering`, `__str__` |
| Scraper | `apps/backend/events/scrapers/facebook_events.py` line 848 | Remove `source=self.source` filter; accept `query_ids` list |
| Runner | `apps/backend/events/runner.py` lines 47–102 | `trigger_scraper_run` gains `query_ids` param; builds `--query-ids` CLI arg |
| Management cmd | `apps/backend/events/management/commands/run_scraper_job.py` lines 98–155 | Add `--query-ids` arg; pass list to `scraper.run()` |
| Views | `apps/backend/events/views.py` lines 660–678, 901–931 | `api_scraper_trigger` reads `query_ids`; `api_search_queries` POST makes source optional; `api_scrapers` adds `supports_keywords` |
| Scrapers base | `apps/backend/events/scrapers/base.py` | Add `supports_keywords = False` class attribute |
| Scrapers init | `apps/backend/events/scrapers/facebook_events.py` | Add `supports_keywords = True` |
| Frontend types | `apps/frontend/src/lib/types.ts` | `Scraper` gets `supports_keywords: boolean` |
| Frontend API | `apps/frontend/src/lib/api.ts` | `runScraper` accepts optional `{ query_ids?: number[] }` body |
| Scrapers page | `apps/frontend/src/routes/scrapers/+page.svelte` | Keyword picker modal; updated `handleRun` |
| Search queries page | `apps/frontend/src/routes/search-queries/+page.svelte` | Remove source input; update `handleAdd` guard |
| Backend tests | `apps/backend/events/tests.py` | New/updated test cases for view changes |

---

## Public Contracts

**`SearchQuery.source`:** becomes `blank=True, default=""`. Existing rows are unchanged.
Old API clients that send `source` in POST still work; it is stored if present.

**`POST /api/scrapers/<key>/run/` body schema:**
```json
{ "query_ids": [1, 2, 3] }   // optional; omit for a full run
```
Response is unchanged: `{ "id": ..., "status": ... }`.

**`GET /api/scrapers/` per-item shape** gains `"supports_keywords": true|false`.
Existing fields are unchanged.

**`POST /api/search-queries/` validation:** `source` is no longer required.
`query` alone is sufficient to create a row. `get_or_create` lookup key changes
from `(query, source)` to `(query,)`.

**`trigger_scraper_run` Python signature:**
```python
def trigger_scraper_run(
    key: str,
    triggered_by=None,
    query_id: int | None = None,   # kept for single-query-run backwards compat
    query_ids: list[int] | None = None,  # new; takes precedence over query_id
) -> tuple[ScraperRun | None, bool]:
```

**`FacebookEventsScraper.run()` signature:**
```python
def run(self, query_id: int | None = None, query_ids: list[int] | None = None, **kwargs)
```
When `query_ids` is given, the ORM filter is `pk__in=query_ids`.
When `query_id` is given (single), the ORM filter is `pk=query_id` (backwards compat).
When neither is given, all active rows are loaded (no source filter).

**`run_scraper_job` CLI:**
Adds `--query-ids` argument (comma-separated int list). When present, the command calls
`scraper.run(query_ids=[...])`. The existing `--query-id` scalar argument is kept for
backwards compat (single-query runs from `/search-queries` page).

---

## Blast Radius

- **DB:** Migration removes the old `unique_source_query` constraint and adds
  `unique_query`. Any duplicate `(query,)` rows in existing data would block this. Must
  audit before applying. `source` column stays; no data is lost.
- **Backend:** `api_search_queries` POST currently 400s if `source` is blank — changing
  this is intentional. Tests for that 400 must be updated.
- **Runner:** `trigger_scraper_run` scalar `query_id` path is unchanged. `query_ids`
  list is additive. The `ScraperRun.scraper_key` for a multi-query run is plain `key`
  (not `key:q:N`) so it uses the full-scraper concurrency slot — intentional, because
  this is a targeted-subset run of the full scraper.
- **Frontend:** `api.runScraper` call sites in `/scrapers` page change to pass
  `query_ids`. The `/search-queries` page `handleRunAll` still calls `api.runScraper(src)`
  without `query_ids` — this now triggers a full run of all active queries, which is
  correct behaviour.
- **Other scrapers:** unaffected. `supports_keywords = False` is the default on
  `BaseScraper`, so no existing scraper card shows the keyword picker.

---

## Implementation Checklist

### Phase A — DB and Model

1. **Check for duplicate `query` values in existing data** (pre-migration safety check).
   Run in Django shell: `SearchQuery.objects.values('query').annotate(c=Count('id')).filter(c__gt=1)`.
   If any duplicates exist, resolve them before proceeding (manual merge or deactivate).

2. **Create migration 0022** via `makemigrations` (do not hand-write):
   - In `apps/backend/events/models.py` lines 241–258:
     - Change `source = CharField(max_length=120, ...)` to add `blank=True, default=""`.
     - Remove `help_text` referencing a specific scraper (update to generic: `"Scraper key that found this query, if any. Legacy field."`).
     - Update `Meta.ordering` from `["source", "query"]` to `["query"]`.
     - Update `Meta.constraints`: replace `UniqueConstraint(fields=["source", "query"], name="unique_source_query")` with `UniqueConstraint(fields=["query"], name="unique_query")`.
     - Update `__str__` to return `self.query` (drop source prefix, since source is now optional).
   - Run `cd apps/backend && ./venv/bin/python manage.py makemigrations --name decouple_search_query_source`.
   - Verify the generated migration alters `source` (blank+default) and replaces the unique constraint.
   - Run `cd apps/backend && ./venv/bin/python manage.py migrate` and confirm it applies cleanly.

### Phase B — Scraper Base and FacebookEventsScraper

3. **Add `supports_keywords` class attribute to `BaseScraper`** in
   `apps/backend/events/scrapers/base.py`:
   - Add `supports_keywords: bool = False` as a class-level attribute on `BaseScraper`.
   - This is the opt-in flag. No behaviour change to the base `run()` method.

4. **Update `FacebookEventsScraper`** in
   `apps/backend/events/scrapers/facebook_events.py`:
   - Add `supports_keywords = True` to the class body.
   - In `run()` (currently line 848), change the ORM load block:
     - Current: `qs = SearchQuery.objects.filter(source=self.source, is_active=True)`
     - New: `qs = SearchQuery.objects.filter(is_active=True)` (no source filter).
     - The existing `if query_id: qs = qs.filter(pk=query_id)` line stays for backward compat.
     - Add a new branch: `if query_ids: qs = qs.filter(pk__in=query_ids)` (takes precedence;
       place this before the `query_id` check or make them mutually exclusive — prefer
       `query_ids` when both are supplied).
   - Update the `run()` method signature from `run(self, query_id=None, **kwargs)` to
     `run(self, query_id=None, query_ids=None, **kwargs)`.

### Phase C — Runner

5. **Update `trigger_scraper_run`** in `apps/backend/events/runner.py` lines 47–102:
   - Add `query_ids: list[int] | None = None` parameter.
   - When `query_ids` is provided:
     - Use plain `run_key = key` (not `key:q:N`) so it occupies the scraper's main concurrency slot.
     - Append `["--query-ids", ",".join(str(i) for i in query_ids)]` to `cmd` when building the subprocess command.
   - When only `query_id` is provided (existing single-query path): behaviour is unchanged.
   - When neither is provided: behaviour is unchanged (full run).
   - Update the docstring to document `query_ids`.

### Phase D — Management Command

6. **Update `run_scraper_job`** in
   `apps/backend/events/management/commands/run_scraper_job.py`:
   - In `add_arguments`, add:
     ```python
     parser.add_argument(
         "--query-ids", type=str, default=None,
         help="Comma-separated SearchQuery PKs to restrict this run.",
     )
     ```
   - In `handle`, after `query_id = options.get("query_id")`, add:
     ```python
     raw_ids = options.get("query_ids")
     query_ids = [int(x) for x in raw_ids.split(",") if x.strip()] if raw_ids else None
     ```
   - Update the scraper call at line 155 from:
     `result = scraper.run(query_id=query_id) if query_id else scraper.run()`
     to:
     `result = scraper.run(query_ids=query_ids) if query_ids else (scraper.run(query_id=query_id) if query_id else scraper.run())`

### Phase E — Views

7. **Update `api_scraper_trigger`** in `apps/backend/events/views.py` lines 658–678:
   - Parse `query_ids` from the POST body:
     ```python
     body = {}
     if request.body:
         try:
             body = json.loads(request.body)
         except (json.JSONDecodeError, ValueError):
             pass
     query_ids = body.get("query_ids") or None
     if query_ids is not None and not (isinstance(query_ids, list) and all(isinstance(i, int) for i in query_ids)):
         return JsonResponse({"error": "query_ids must be a list of integers"}, status=400)
     ```
   - Pass `query_ids=query_ids` to `trigger_scraper_run(key, triggered_by=triggered_by, query_ids=query_ids)`.
   - `json` is already imported in the module; confirm at the top of `views.py`.

8. **Update `api_search_queries` POST** in `apps/backend/events/views.py` lines 910–929:
   - Change validation from `if not query or not source:` to `if not query:`.
   - Change `get_or_create` lookup from `(query=query, source=source)` to `(query=query)`.
   - Keep `source` as an optional stored value: if `source` is present in the body,
     include it in `defaults={"is_active": ..., "source": source}`. If absent, it
     defaults to `""` (the model default).
   - Update the conflict message from `"Query already exists for this source"` to
     `"Query already exists"`.

9. **Update `api_scrapers`** in `apps/backend/events/views.py` lines 826–878:
   - Import or reference `SCRAPERS` (already done inside the function via local import).
   - When building each result dict (line 870), add:
     ```python
     "supports_keywords": getattr(SCRAPERS[key], "supports_keywords", False),
     ```

### Phase F — Frontend Types and API Client

10. **Update `Scraper` type** in `apps/frontend/src/lib/types.ts` line 147:
    - Add `supports_keywords: boolean;` to the `Scraper` interface.

11. **Update `api.runScraper`** in `apps/frontend/src/lib/api.ts` line 126:
    - Change from:
      `runScraper: (key: string) => post<{ id: number; status: ScraperRunStatus }>(...)`
    - To a new helper that accepts an optional body:
      ```typescript
      runScraper: (key: string, body?: { query_ids?: number[] }) =>
        body && Object.keys(body).length > 0
          ? postJson<{ id: number; status: ScraperRunStatus }>(`/scrapers/${key}/run/`, body)
          : post<{ id: number; status: ScraperRunStatus }>(`/scrapers/${key}/run/`),
      ```
    - Both `post` and `postJson` already exist in the module.

### Phase G — Scrapers Page (keyword picker)

12. **Add state variables** to `apps/frontend/src/routes/scrapers/+page.svelte` script block:
    - `let keywordPickerKey = $state<string | null>(null)` — which scraper card is showing the picker.
    - `let allKeywords = $state<SearchQuery[]>([])` — fetched once when picker opens.
    - `let selectedKeywordIds = $state<Set<number>>(new Set())` — user selections.
    - `let keywordsLoading = $state(false)`.
    - `let keywordPickerError = $state<string | null>(null)`.

13. **Add `openKeywordPicker(key)` function** in the script block:
    - Sets `keywordPickerKey = key`, clears `selectedKeywordIds`.
    - Sets `keywordsLoading = true`, fetches `await api.searchQueries()`, stores in
      `allKeywords`, sets `keywordsLoading = false`.
    - Handles fetch error into `keywordPickerError`.

14. **Add `closeKeywordPicker()` function**: sets `keywordPickerKey = null`,
    clears `allKeywords`, `selectedKeywordIds`, `keywordPickerError`.

15. **Add `handleRunWithKeywords(key)` function**:
    - Calls existing `handleRun(key)` path but passes `query_ids: [...selectedKeywordIds]`
      to `api.runScraper(key, { query_ids: [...selectedKeywordIds] })`.
    - After triggering, calls `closeKeywordPicker()`.
    - Reuse existing `triggering` and `errors` state maps.

16. **Update `handleRun(key)` call site** in each scraper card's "Run" button:
    - For scrapers where `scraper.supports_keywords === true`, replace the direct
      `handleRun(key)` call with `openKeywordPicker(key)`.
    - For all other scrapers, keep `handleRun(key)` unchanged.

17. **Add keyword picker modal markup** in the page template (after the scraper cards section):
    - Render a modal overlay `{#if keywordPickerKey}`.
    - Show a loading spinner while `keywordsLoading`.
    - Show a scrollable checklist of `allKeywords` rows (checkbox per row, label = `sq.query`,
      disabled if `!sq.is_active`); bind checked state to `selectedKeywordIds`.
    - "Run Selected" button: disabled if `selectedKeywordIds.size === 0`; calls
      `handleRunWithKeywords(keywordPickerKey)`.
    - "Run All Keywords" button: selects all active keyword IDs, then calls
      `handleRunWithKeywords(keywordPickerKey)`.
    - "Cancel" button: calls `closeKeywordPicker()`.
    - Display `keywordPickerError` if present.
    - Style: dark overlay, centered card, consistent with existing surface/border/text tokens.

### Phase H — Search Queries Page

18. **Update `/search-queries/+page.svelte`** Add form (lines 220–261):
    - Remove the `<div class="sm:w-48">` block containing the source input
      (`id="new-source"`, `bind:value={newSource}`).
    - Remove `let newSource = $state('facebook_events')` from the script block (line 15).
    - Update `handleAdd` guard (line 94) from `if (!newQuery.trim() || !newSource.trim())` to
      `if (!newQuery.trim())`.
    - **Bulk insertion:** `handleAdd` should split `newQuery` on commas, trim each token, and
      filter out empty strings. If the result has more than one token, iterate and call
      `api.createSearchQuery({ query: token })` for each. Accumulate created/skipped counts
      and show a single summary toast (e.g. "3 added, 1 already existed"). If only one token,
      behaviour is identical to today.
    - Update `api.createSearchQuery` call from
      `{ query: newQuery.trim(), source: newSource.trim() }` to
      `{ query: token.trim() }` (inside the loop).
    - Update the `api.createSearchQuery` type in `api.ts` line 137:
      Change `body: { query: string; source: string; is_active?: boolean }` to
      `body: { query: string; source?: string; is_active?: boolean }`.
    - The source column in the table (line 327–331) stays as-is (read-only display).
    - The source filter tabs (line 265–278) remain; they still work for rows that have a
      source value.
    - Update the input placeholder from `"e.g. events in CDO"` to
      `"e.g. events in CDO, tech events, startup"` to hint at comma-separated support.

### Phase I — Tests

19. **Update backend tests** in `apps/backend/events/tests.py`:
    - Find and update any test that POSTs to `/api/search-queries/` with both `query` and
      `source` in the body and asserts 400 when `source` is absent — change the assertion
      to expect 201 (creation succeeds without source).
    - Add a test: POST `/api/search-queries/` with only `{ "query": "test keyword" }` →
      201, `source` is `""` in response.
    - Add a test: POST `/api/search-queries/` with same query twice → 409 (unique_query
      constraint enforced at view layer).
    - Add a test: POST `/api/scrapers/facebook_events/run/` with body
      `{ "query_ids": [1, 2] }` creates a `ScraperRun` with `scraper_key="facebook_events"`
      (not a `":q:"` keyed run).
    - Add a test: POST `/api/scrapers/facebook_events/run/` with `{ "query_ids": "bad" }` →
      400.
    - Add a test: GET `/api/scrapers/` response includes `"supports_keywords": true` for
      `facebook_events` and `false` for another scraper key.
    - Run full test suite and confirm no regressions: 97 → ≥ 97 tests passing.

---

## Acceptance Criteria

1. `cd apps/backend && ./venv/bin/python manage.py migrate` applies migration 0022 without error.
2. `SearchQuery.objects.create(query="test")` succeeds with `source=""`.
3. A second `SearchQuery.objects.create(query="test")` raises `IntegrityError` (unique_query).
4. `SearchQuery.objects.create(query="test", source="facebook_events")` and then
   `SearchQuery.objects.create(query="test", source="other_source")` — second call raises
   `IntegrityError` (source no longer differentiates uniqueness).
5. All 97+ backend tests pass.
6. `pnpm --filter frontend check` passes with zero TypeScript errors.
7. In dev: clicking "Run" on the `facebook_events` card opens the keyword picker modal.
8. Selecting 2 keywords and clicking "Run Selected" triggers a `ScraperRun` and the run
   appears in the run history with `scraper_key = "facebook_events"`.
9. Clicking "Run" on any non-facebook scraper card triggers the run immediately (no picker).
10. `/search-queries` Add form has only the "Search term" input; submitting without a source
    creates a row with `source = ""`.
10b. Entering `"events in CDO, tech events, startup"` and submitting creates 3 rows and shows
     a summary toast. Re-submitting the same value shows "0 added, 3 already existed".
11. Existing rows in the `source` column still display correctly in the table.

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Existing data has duplicate `query` values across sources | Low (small dataset) | Step 1 audits for dupes before migration |
| `api_scraper_trigger` did not previously parse a JSON body — adding `json.loads` on a POST that may have an empty body | Medium | Guard with `if request.body:` before parsing; default `body = {}` |
| `FacebookEventsScraper.run()` called without any active SearchQuery rows (e.g. all deactivated) — existing early-return handles this correctly | No change | No mitigation needed; early-return at line 853 covers it |
| `query_ids` list with non-existent PKs silently returns zero results | Acceptable | ORM `pk__in` with unknown PKs simply returns empty — log "no active search queries" handles it |
| Frontend keyword picker adds a blocking fetch before the run dialog shows | UX acceptable | Add loading state (`keywordsLoading`) and show spinner |
| `unique_query` constraint is too strict if the same keyword is genuinely needed for two scrapers in future | Low (YAGNI) | Future work can add a `scraper_key` field or a ManyToMany; current scope just decouples |

---

## Dependencies

- Migration 0022 must be applied before any backend code change is deployed.
- Steps 3–4 (scraper changes) depend on step 2 (model change applied).
- Steps 5–6 (runner + management command) can be done in parallel with steps 3–4.
- Steps 7–9 (views) depend on steps 5–6 (runner signature finalized).
- Steps 10–11 (frontend types + API) can be done in parallel with steps 7–9.
- Steps 12–17 (scrapers page) depend on steps 10–11.
- Step 18 (search-queries page) depends on step 11 (api.ts type update for optional source).
- Step 19 (tests) should be written/updated after steps 7–9 are in place.

---

## Verification Evidence

| Check | Command | Expected |
|---|---|---|
| Migration applies | `cd apps/backend && ./venv/bin/python manage.py migrate` | "OK" with no errors |
| Migration dry-run shows no pending changes after applying | `./venv/bin/python manage.py makemigrations --check --dry-run` | "No changes detected" |
| Full test suite | `cd apps/backend && ./venv/bin/python manage.py test events` | ≥ 97 tests, 0 failures |
| Frontend type-check | `pnpm --filter frontend check` | 0 errors |
| Django shell sanity | `SearchQuery(query="kw").full_clean()` | No ValidationError |
| `/api/scrapers/` response | `curl http://localhost:8000/api/scrapers/` | `facebook_events` has `"supports_keywords": true` |
| Run trigger with query_ids | `curl -X POST .../api/scrapers/facebook_events/run/ -d '{"query_ids":[1]}'` | Returns `{id, status}` 200 |
| Search-queries POST without source | `curl -X POST .../api/search-queries/ -d '{"query":"test"}'` | 201, `source: ""` |

---

## Integration Notes

- `api_scraper_trigger` is `@csrf_exempt` — the existing CSRF posture applies; no auth change needed.
- The `ScraperRun.scraper_key` for a `query_ids` run is plain `key` (not `key:q:N`). This means
  the concurrency guard at the DB level (`unique_active_scraper_run`) will block a second
  targeted-keyword run of the same scraper if one is already queued/running. This is intentional
  and consistent with the full-run concurrency model.
- The existing `api_search_query_run` endpoint (single-query run from `/search-queries` page)
  continues to use the `trigger_scraper_run(sq.source, query_id=sq.pk)` path unchanged.
  Since `sq.source` may now be `""` for new rows, this will fail to find the right scraper.
  **Resolution:** `api_search_query_run` should fall back to `"facebook_events"` (or any scraper
  that declares `supports_keywords = True`) when `sq.source` is blank. Update that view to:
  ```python
  scraper_key = sq.source or "facebook_events"
  ```
  This is a necessary addition to step 7's scope; document it in the checklist as step 7b.

---

## Integration Note Addendum — Step 7b

**7b. Update `api_search_query_run`** in `apps/backend/events/views.py` lines 934–950:
- Current: `run, already_active = trigger_scraper_run(sq.source, triggered_by=triggered_by, query_id=sq.pk)`
- Change to: `scraper_key = sq.source or "facebook_events"` then use `scraper_key` in the call.
- This ensures rows created without a source can still be run individually from the
  `/search-queries` page. The fallback to `"facebook_events"` is safe because the only
  query-capable scraper today is `facebook_events`; when other scrapers opt in, they will
  set `source` on creation or a more sophisticated lookup will be added.

---

## Resume and Execution Handoff

**Plan path:** `process/general-plans/active/decouple-search-query-source_PLAN_23-06-26.md`

Execute steps in order A → B → C → D → E (including 7b) → F → G → H → I.

Phases C and D (runner + management command) may be done simultaneously as they touch
separate files. Phases F and G (frontend types + scrapers page) may begin as soon as
phase E is complete.

If execution is interrupted after step 2 (migration applied), the backend must be
consistent: ensure steps 3–9 are complete before restarting the Django dev server,
because the old `source` validation in the POST view will still reject sourceless bodies
until step 8 is applied.

**Validator:**
```bash
node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs \
  process/general-plans/active/decouple-search-query-source_PLAN_23-06-26.md
```

---

## Cursor + RIPER-5 Guidance

**RIPER-5 Mode (SIMPLE — one session):**
- RESEARCH: complete (provided as context above)
- INNOVATE: complete (approach chosen)
- PLAN: complete — this document
- EXECUTE: next — implement steps 1–19 in order, verify after step 2 (migration), after step 9
  (backend), and after step 18 (frontend) using the Verification Evidence table above
- No approval gates between steps — implement continuously within one session

**Next step:** Say "ENTER EXECUTE MODE" and pass this plan path to `vc-execute-agent`.
