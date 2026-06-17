# Category Normalization — Display-Only (Option A)

**Plan type:** SIMPLE (single session)
**Created:** 2026-06-17
**Status:** COMPLETED
**Completion:** Completed 2026-06-17; commits 451e107, 4e6b359; 12 new tests; 49 total pass.

---

## Overview

The "Events by Category" donut chart on the admin dashboard is currently unusable because
running-event scrapers store comma-joined race distances or ticket tier names in
`Event.category` (e.g. `"10K, 5K, 3K"`, `"SUB1 Elite, SUB1 Competitor, Open Wave"`). Each
unique string becomes its own donut slice, producing dozens of near-meaningless wedges.

This plan fixes the presentation entirely at the API layer: raw `category` values are mapped
to a small canonical set at query time, counts are re-aggregated in Python, and a Top-N +
"Other" rollup caps the slice count. No DB schema is changed, no scraper is modified, and the
stored `category` field is never overwritten. The fix is fully reversible.

---

## Goals

- Reduce the donut to ≤ 9 slices (Top 8 canonical buckets + optional "Other").
- Correctly bucket distance-list values (e.g. `"21KM, 10KM, 5KM"`) as `"Fun Run / Road Race"`.
- Map a small set of obvious keywords to human-readable canonical names.
- Preserve unknown/clean categories as-is (title-cased fallback) so no data is silently lost.
- Keep the `[{category, count}]` API shape unchanged — frontend requires zero changes.

---

## Scope

**In scope:**
- New helper module `apps/backend/events/categories.py` with `normalize_category(raw: str) -> str`.
- Rewrite of `api_events_by_category` in `apps/backend/events/views.py` (lines 247–254).
- Unit tests for the helper and an integration test for the API view.

**Explicitly out of scope (non-goals):**
- No DB schema change — `Event.category` column is untouched.
- No scraper edits — raw values continue to be stored verbatim.
- No migration required.
- No frontend changes — API response shape is identical.
- No admin/UI changes.
- No Option B (canonical `raw_category` field + taxonomy migration) — see Future Work below.

---

## Implementation Steps

### Step 1 — Create `apps/backend/events/categories.py`

Create a new file with a single public function `normalize_category(raw: str) -> str`.

**Logic (ordered — first match wins):**

1. Strip and lowercase the input for matching only; preserve the original for fallback display.
2. **Distance-list detection:** split on commas, strip each part, check whether at least one
   part matches `r'^\d+\s?km?$'` (case-insensitive). If yes → return `"Fun Run / Road Race"`.
   - Matches: `"10K"`, `"21KM"`, `"5K, 10K, 21KM"`, `"42K"`, `"3K, 5K, 10K"`.
   - Also matches single-part distance entries like `"10KM"`.
3. **Wave/tier name detection:** if the raw string contains "wave", "elite", "competitor",
   "finisher", "pacer" (case-insensitive), and does NOT already match the distance pattern →
   return `"Fun Run / Road Race"` (these are run-event tiers masquerading as categories).
4. **Keyword map** (substring match, case-insensitive; first matching key wins):

   | Keyword(s) | Canonical bucket |
   |---|---|
   | `trail` | `"Trail Run"` |
   | `triathlon`, `duathlon` | `"Triathlon / Duathlon"` |
   | `cycling`, `bike`, `biking` | `"Cycling"` |
   | `swim`, `swimming` | `"Swimming"` |
   | `music`, `concert`, `band`, `gig` | `"Music"` |
   | `festival` | `"Festival"` |
   | `conference`, `summit`, `seminar` | `"Conference / Seminar"` |
   | `workshop`, `training`, `class` | `"Workshop / Training"` |
   | `food`, `culinary`, `dining` | `"Food & Dining"` |
   | `art`, `exhibit`, `gallery` | `"Arts & Culture"` |
   | `charity`, `fundrais` | `"Charity / Fundraiser"` |
   | `sport`, `game`, `tournament` | `"Sports"` |

5. **Fallback:** return `raw.strip().title()` — applies consistent title-case normalization
   to unknown categories (transforms the capitalization; does not preserve as-is).

**Design note for Option B:** The function accepts and returns plain strings with no
ORM coupling. When Option B adds a `raw_category` field, this same function can be called
in a data migration or in `save_events` without modification.

**File path:** `apps/backend/events/categories.py`

---

### Step 2 — Rewrite `api_events_by_category` in `apps/backend/events/views.py`

**Location:** lines 247–254 (confirmed).

Replace the current single-query implementation with:

1. Import `normalize_category` from `.categories` at the top of the file (add to existing
   import block).
2. Fetch raw `(category, count)` rows from the ORM exactly as now:
   ```
   Event.objects.exclude(category="").values("category").annotate(count=Count("id"))
   ```
3. Iterate rows in Python; for each row call `normalize_category(row["category"])` and
   accumulate counts into a `dict[str, int]` keyed by canonical bucket name.
4. Apply Top-N cutoff (default `TOP_N = 8`):
   - Sort the aggregated dict by count descending.
   - Keep the top `TOP_N` entries as-is.
   - Sum remaining counts into a single `{"category": "Other", "count": remainder}` entry
     (omit the "Other" entry entirely if the remainder is 0).
5. Return `JsonResponse(result, safe=False)` where `result` is a list of
   `{"category": str, "count": int}` dicts — identical shape to before.

**Optional stretch (note in plan, do not implement now):** accept `?top=N` query param to
override `TOP_N` at runtime. Document as a future nicety; no frontend wiring needed.

**File path:** `apps/backend/events/views.py` (import addition + lines 247–254 replacement)

---

### Step 3 — Add tests to `apps/backend/events/tests.py`

Append a new `TestCase` subclass (e.g. `CategoryNormalizationTests`) with:

**Unit tests for `normalize_category`:**
- `"10K, 5K, 3K"` → `"Fun Run / Road Race"` (distance list)
- `"21KM, 10KM, 5KM"` → `"Fun Run / Road Race"` (distance list, KM suffix)
- `"42K"` → `"Fun Run / Road Race"` (single distance)
- `"SUB1 Elite, SUB1 Competitor, Open Wave"` → `"Fun Run / Road Race"` (wave/tier names)
- `"trail run"` → `"Trail Run"` (keyword map)
- `"Music Festival"` → `"Music"` (music keyword wins over festival because it appears first in map)
  — actually `"festival"` keyword is separate from `"music"`; test both as single-keyword inputs
  too: `"music"` → `"Music"`, `"festival"` → `"Festival"`.
- `"Photography Workshop"` → `"Workshop / Training"` (workshop keyword)
- `"Tech Conference"` → `"Conference / Seminar"` (conference keyword)
- `"Weird Unique Event 2026"` → `"Weird Unique Event 2026"` (fallback title-case passthrough)
- Empty string `""` → `""` (edge case — do not crash)

**Integration test for `api_events_by_category`:**
- Create > 8 `Event` objects with distinct raw category values that map to fewer canonical
  buckets, plus several that map to unique fallback labels.
- GET `/api/events/by-category/`.
- Assert response status 200.
- Assert response JSON is a list.
- Assert `len(response_data) <= 9` (Top 8 + optional "Other").
- Assert at least one entry has `category == "Other"` when more than 8 canonical buckets exist.
- Assert all entries have `count > 0`.

**File path:** `apps/backend/events/tests.py` (append only, no modifications to existing tests)

---

## Touchpoints

| Surface | File | Change type |
|---|---|---|
| New helper module | `apps/backend/events/categories.py` | Create (new file) |
| API view | `apps/backend/events/views.py` lines 1–10 (imports), 247–254 (view body) | Edit |
| Test suite | `apps/backend/events/tests.py` | Append new TestCase class |

No other files are touched.

---

## Blast Radius

- **Backend:** one API view function modified; one new pure-Python helper module added.
- **Frontend:** zero changes. The API response shape `[{category, count}]` is identical.
  `DonutChart.svelte`, `+page.svelte`, `api.ts`, and `types.ts` are all untouched.
- **DB/migrations:** none.
- **Scrapers:** none.
- **Admin:** none.
- **Other API views:** none — `api_events_by_category` is self-contained.

Rollback: delete `categories.py` and revert the two edits in `views.py`. No migration to undo.

---

## Verification

### Automated

```bash
# From the repo root
cd /Volumes/Extreme_SSD/Projects/Python/veent-event-scraper/apps/backend
./venv/bin/python manage.py test events
```

Expected: all pre-existing tests pass + new `CategoryNormalizationTests` passes.
`CategoryNormalizationTests` should add ~10 unit tests and 1 integration test.

### Manual

1. Start the backend:
   ```bash
   cd /Volumes/Extreme_SSD/Projects/Python/veent-event-scraper/apps/backend
   ./venv/bin/python manage.py runserver
   ```
2. Hit the endpoint and inspect output:
   ```bash
   curl -s http://localhost:8000/api/events/by-category/ | python3 -m json.tool
   ```
   Expected: ≤ 9 entries, no entries that look like distance lists or tier names.

3. Start the frontend:
   ```bash
   cd /Volumes/Extreme_SSD/Projects/Python/veent-event-scraper/apps/frontend
   pnpm dev
   ```
   Open the dashboard and visually confirm the donut has ≤ 9 readable slices.

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Normalizer misbuckets a real category | Low-Medium | Map is small and obvious; fallback title-cases unknowns so no data is silently lost; fully reversible |
| A new scraper adds a category pattern we didn't anticipate | Low | Fallback preserves it as-is; the keyword map is easily extended one entry at a time |
| "Other" absorbs too many legitimate categories | Low | `TOP_N=8` is generous; if needed bump the constant or add a keyword row |
| Distance regex misses an unusual format (e.g. "Half Marathon") | Low | Add "marathon", "half marathon", "half" keywords to the keyword map under "Fun Run / Road Race" |

---

## Future Work — Option B (Canonical Taxonomy)

Option B would add a `raw_category = models.CharField(...)` field to `Event` to permanently
preserve the original value, write the canonical name into `Event.category` at scrape time,
and add a data migration to backfill. The `normalize_category` helper created here is
intentionally decoupled from the ORM so it can be reused verbatim in Option B's migration
or `save_events` call. When Option B is ready, the display-layer aggregation in
`api_events_by_category` can be simplified back to a single DB query.

---

## Resume and Execution Handoff

**Pre-conditions:** None — no migrations, no dependencies, no env vars required.

**Execution order:**
1. Create `apps/backend/events/categories.py` (Step 1) — pure Python, no imports from Django.
2. Edit `apps/backend/events/views.py` (Step 2) — add import, replace view body.
3. Append tests to `apps/backend/events/tests.py` (Step 3).
4. Run `./venv/bin/python manage.py test events` from `apps/backend/`.
5. Manual spot-check via curl + browser.

**All three steps can be completed in one session. No phase boundaries.**

**Selected plan file:** `process/general-plans/active/2026-06-17-category-normalization_PLAN_17-06-26.md`
