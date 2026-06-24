# fb-posts-smart-scroll — Implementation Plan

**Date**: 23-06-26
**Complexity**: SIMPLE (single-session, one file)
**Status**: PLANNED

> Context consulted: `process/context/all-context.md` (repo overview, scraper architecture).
> No test framework changes — behaviour is verified via `manage.py scrape` manual runs.
> See Post-Phase Testing section under each Execution Brief phase.

---

## Overview

Upgrade `FacebookPostsScraper._fetch_raw_posts` in `apps/backend/events/scrapers/facebook_posts.py`
to mirror the scroll mechanics, "See more" handling, and Recent-filter clicking of the Chrome
extension `fb-events-tool`. The existing architecture (auth, per-query iteration, LLM structuring)
is unchanged; only the browser-automation behavior inside `_fetch_raw_posts` and the supporting JS
constants/scroll function are added or modified.

---

## Quick Links

- [Goals and Success Metrics](#goals-and-success-metrics)
- [Phase Completion Rules](#phase-completion-rules)
- [Execution Brief](#execution-brief)
- [Scope](#scope)
- [Assumptions and Constraints](#assumptions-and-constraints)
- [Functional Requirements](#functional-requirements)
- [Acceptance Criteria](#acceptance-criteria)
- [Implementation Checklist](#implementation-checklist)
- [Risks and Mitigations](#risks-and-mitigations)
- [Integration Notes](#integration-notes)
- [Touchpoints](#touchpoints)
- [Public Contracts](#public-contracts)
- [Blast Radius](#blast-radius)
- [Verification Evidence](#verification-evidence)
- [Resume and Execution Handoff](#resume-and-execution-handoff)

---

## Goals and Success Metrics

- FB post scraping loops up to 20 scroll rounds instead of one fixed scroll pass.
- Each round auto-clicks "See more results" / "See more posts" buttons to load additional content.
- Caption "See more" expansion uses humanised mouse events (no bare `.click()`).
- `/search/posts` queries click the "Recent posts" sort tab before scrolling.
- Scroll terminates early when 15+ fresh (not-yet-in-DB) posts are found OR when 4 consecutive
  rounds detect no new content (idle).
- `run()` passes each query's existing post URLs to `_fetch_raw_posts` so the early-exit works.
- Log messages show round count and the stop reason (`IDLE`, `MIN_FRESH_TARGET`, or `MAX_ROUNDS`).

---

## Phase Completion Rules

A phase is NOT complete until:

1. **Integration Test** — Works with the existing Playwright + Django ORM pipeline end-to-end.
2. **Manual Test** — `manage.py scrape facebook_posts` runs without error; log shows scroll rounds.
3. **Data Verification** — New events appear in DB; no duplicate rows introduced.
4. **Error Handling** — Missing extension / selector fallbacks degrade gracefully (no crash).
5. **User Confirmation** — User sees scroll-round log lines and confirms early-exit triggers.

Status meanings:
- ⏳ PLANNED — Not started
- 🔨 CODE DONE — Written but not E2E tested
- 🧪 TESTING — Currently being tested
- ✅ VERIFIED — Tested AND confirmed working
- 🚧 BLOCKED — Has issues

---

## Execution Brief

### Phase A — New JS constants (Steps 1–4)

**What happens:** Three new module-level JS string constants are added directly after the existing
`_EXPAND_SEE_MORE_JS` block, and `_EXPAND_SEE_MORE_JS` itself is updated to use `humanClick`.
No Python logic changes yet.

**Post-Phase Testing:**
- Manual test: `python -c "from events.scrapers.facebook_posts import _CLICK_RECENT_FILTER_JS, _CLICK_SEE_MORE_RESULTS_JS, _COUNT_FRESH_ANCHORS_JS"` exits 0.
- Manual test: Paste `_CLICK_RECENT_FILTER_JS` into browser DevTools on `/search/posts?q=test` — returns `true` or `false` (no JS error).
- Manual test: `grep -n "el.click()" apps/backend/events/scrapers/facebook_posts.py` returns no lines.

**Verify:** No Python import errors; bare `el.click()` absent from file.

**Done when:** All constants importable and syntactically valid JS; user confirms grep shows 0 bare clicks.

---

### Phase B — `_smart_scroll` Python function (Step 5)

**What happens:** Module-level helper function `_smart_scroll(page, known_urls, max_rounds)`
added before the `FacebookPostsScraper` class. Uses the four JS constants internally.

**Post-Phase Testing:**
- Manual test: `manage.py scrape facebook_posts` against a live keyword query.
- Observe: log lines contain `_smart_scroll` round numbers.
- Observe: log terminates with one of: `IDLE stop`, `MIN_FRESH_TARGET reached`, or `MAX_ROUNDS`.

**Verify:** Function completes without uncaught exceptions; stop reason logged.

**Done when:** Scroll loop runs, logs rounds, and terminates correctly.

---

### Phase C — `_fetch_raw_posts` and `run()` updates (Steps 6–8)

**What happens:** `_fetch_raw_posts` gains a `known_urls` parameter and integrates the recent
filter click and `_smart_scroll` call. `run()` pre-loads per-query existing post URL sets and
passes them in.

**Post-Phase Testing:**
- Manual test: Full scrape with a keyword query that has existing events in DB.
- Observe: log shows "MIN_FRESH_TARGET reached" or "IDLE stop".
- Data verification: `Event.objects.filter(source='facebook_posts').count()` grows (or stays same if no new posts); no duplicates.
- Data verification: `Event.objects.values('external_id').annotate(c=Count('id')).filter(c__gt=1).count()` returns `0`.

**Done when:** User confirms early-exit log message appears and event count is non-decreasing.

---

**Expected Outcome:**
- One modified file: `apps/backend/events/scrapers/facebook_posts.py`
- `_CLICK_RECENT_FILTER_JS`, `_CLICK_SEE_MORE_RESULTS_JS`, `_COUNT_FRESH_ANCHORS_JS` constants added
- `_EXPAND_SEE_MORE_JS` updated to use inline `humanClick`
- `_smart_scroll()` function present and exercised on every scrape run
- `_fetch_raw_posts` and `run()` updated; existing 97 tests unaffected

---

## Scope

**In scope:**
- `apps/backend/events/scrapers/facebook_posts.py` — all changes
- JS constant additions and updates within that file
- New `_smart_scroll` module-level Python function within that file
- `_fetch_raw_posts` method update
- `run()` method update (known-URL pre-load only)

**Out of scope:**
- `facebook_events.py`, `base.py`, `proxy_manager.py`, `social_proxy.py` — no changes
- Model / migration files
- View / URL files
- Frontend files
- Any test file creation or modification (behaviour is verified manually via the scraper command)

---

## Assumptions and Constraints

- The extension source files (`extension/content/content-posts.js`) are reference-only; this plan
  contains the exact ported logic inline. Execute does not need to read the extension files.
- `humanClick` is defined as an inline JS helper inside both `_CLICK_SEE_MORE_RESULTS_JS` and
  the updated `_EXPAND_SEE_MORE_JS` — it is NOT a shared module or import.
- `_human_scroll` (imported from `facebook_events`) is removed from `_fetch_raw_posts` and
  replaced entirely by `_smart_scroll`. The import line for `_human_scroll` must be removed;
  it is not used anywhere else in `facebook_posts.py`.
- `known_urls` uses normalised `external_id` strings (output of `_post_external_id()`), not raw
  full URLs. The `_COUNT_FRESH_ANCHORS_JS` must apply the same normalisation on the JS side.
- Playwright `page.evaluate` with a JS function string (not a lambda) is the existing pattern in
  this file; maintain that pattern throughout.
- `_pause` is already imported from `facebook_events`; use it for all sleep calls in
  `_smart_scroll`.
- Django ORM access is never inside the Playwright block; the known-URL pre-load happens before
  `sync_playwright()` opens.

---

## Functional Requirements

1. **`_CLICK_RECENT_FILTER_JS`** — JS constant (IIFE returning boolean).
   - Strategy 1: `document.querySelector('[aria-label="Recent posts"], [aria-label="Recent"]')` — click if found.
   - Strategy 2: Iterate `document.querySelectorAll('[role="tab"], [role="button"]')`, match `el.innerText` against `/^recent\s*(posts)?$/i`, click first match.
   - Strategy 3: Iterate `document.querySelectorAll('span, div')`, match `el.innerText` against `/^recent posts$/i` (case-insensitive), ensure `el.offsetParent !== null`, click first match.
   - Returns `true` if any strategy clicked, `false` if not found.

2. **`_CLICK_SEE_MORE_RESULTS_JS`** — JS constant (IIFE returning integer count).
   - Defines inline `humanClick(el)` helper that dispatches `mouseover`, `mousedown`, `mouseup`,
     `click` `MouseEvent`s with randomised coordinates inside the element's bounding rect.
   - Queries `[role="button"], button` elements; filters to those whose trimmed `innerText` matches
     `/^(see more results|see more posts|more results|see more)$/i`.
   - Excludes any element that has a `div[dir="auto"]` ancestor (those are caption "See more" links,
     not pagination buttons).
   - Calls `humanClick(el)` on each match and increments a counter.
   - Returns the integer count of buttons clicked.

3. **Updated `_EXPAND_SEE_MORE_JS`** — replaces bare `el.click()` with inline `humanClick(el)`.
   - Same `humanClick` definition as in `_CLICK_SEE_MORE_RESULTS_JS` (copy-paste inside the string
     — these are isolated JS scopes, not shared module code).
   - Keep the IIFE synchronous (no async/await). The humanClick dispatch adds realism without
     requiring per-click sleep.

4. **`_COUNT_FRESH_ANCHORS_JS`** — JS constant accepting `knownIds` argument (array of strings).
   - Signature when evaluated: `page.evaluate(_COUNT_FRESH_ANCHORS_JS, list(known_urls))`
     which maps to JS `(knownIds) => { ... }` receiving the array.
   - Iterates `document.querySelectorAll('a[href]')`.
   - For each anchor, checks `isPostHref(href)` (same inline helper as in `_EXTRACT_POSTS_JS`,
     copied inline).
   - Normalises each post href to its `external_id` equivalent:
     `href.split('facebook.com/').pop().replace(/\/$/, '').replace(/[?#].*$/, '').replace(/\//g, '_')`
     — must match the Python `_post_external_id()` logic exactly (split on `facebook.com/`,
     strip trailing slash, strip query/fragment, replace `/` with `_`).
   - Counts anchors whose normalised id is NOT in a `Set(knownIds)`.
   - Returns integer count.

5. **`_smart_scroll(page, known_urls=frozenset(), max_rounds=20)`** — module-level Python function.
   - Constants defined at top of function body:
     - `MAX_IDLE = 4`
     - `MIN_FRESH_TARGET = 15`
     - `SCROLL_SLEEP_MIN, SCROLL_SLEEP_MAX = 0.6, 1.0` (within-round scroll pause)
     - `ROUND_SLEEP_MIN, ROUND_SLEEP_MAX = 1.5, 2.5` (between-round pause)
   - Initialise `idle_rounds = 0` before the loop.
   - Each round (loop index `i` from 0 to `max_rounds - 1`):
     1. Capture `prev_height = page.evaluate("document.body.scrollHeight")`.
     2. Capture `prev_count = page.evaluate("document.querySelectorAll('div[dir=\"auto\"]').length")`.
     3. `page.evaluate("window.scrollTo(0, document.body.scrollHeight)")`.
     4. `_pause(SCROLL_SLEEP_MIN, SCROLL_SLEEP_MAX)`.
     5. `see_more_clicked = page.evaluate(_CLICK_SEE_MORE_RESULTS_JS)` — if > 0: `logger.debug("[facebook_posts] _smart_scroll round %d: clicked %d see-more-results", i, see_more_clicked)`.
     6. `expanded = page.evaluate(_EXPAND_SEE_MORE_JS)` — if > 0: `logger.debug("[facebook_posts] _smart_scroll round %d: expanded %d captions", i, expanded)`.
     7. `new_height = page.evaluate("document.body.scrollHeight")`.
     8. `new_count = page.evaluate("document.querySelectorAll('div[dir=\"auto\"]').length")`.
     9. `changed = (new_height != prev_height) or (new_count != prev_count)`.
     10. If `not changed`: `idle_rounds += 1`; else: `idle_rounds = 0`.
     11. If `idle_rounds >= MAX_IDLE`: `logger.info("[facebook_posts] _smart_scroll: IDLE stop after %d rounds", i + 1)` and `return`.
     12. If `known_urls` is non-empty: `fresh = page.evaluate(_COUNT_FRESH_ANCHORS_JS, list(known_urls))`. If `fresh >= MIN_FRESH_TARGET`: `logger.info("[facebook_posts] _smart_scroll: MIN_FRESH_TARGET reached (%d fresh) at round %d", fresh, i + 1)` and `return`.
     13. `_pause(ROUND_SLEEP_MIN, ROUND_SLEEP_MAX)`.
   - After loop exits: `logger.info("[facebook_posts] _smart_scroll: MAX_ROUNDS (%d) reached", max_rounds)`.

6. **`_fetch_raw_posts(self, page, query, max_posts=None, known_urls=frozenset())`** — updated.
   - Add `known_urls: set = frozenset()` to signature.
   - After the `wait_for_selector` block and before `_EXPAND_SEE_MORE_JS`:
     insert `if "/search/posts" in page.url:` block that evaluates `_CLICK_RECENT_FILTER_JS`
     and calls `_pause(1.0, 2.0)`.
   - Replace `_human_scroll(page)` call with `_smart_scroll(page, known_urls)`.
   - All other lines remain unchanged.
   - Exact new sequence:
     ```text
     navigate → _pause(3.0, 5.0)
     → _DISMISS_MODAL_JS → _pause(1.0, 2.0)
     → wait_for_selector('[role="article"] div[dir="auto"]', 12s)
     → IF /search/posts in url: _CLICK_RECENT_FILTER_JS → _pause(1.0, 2.0)
     → _EXPAND_SEE_MORE_JS → _pause(0.5, 1.0)
     → _smart_scroll(page, known_urls)          ← replaces _human_scroll
     → _DISMISS_MODAL_JS → _pause(1.0, 2.0)
     → _EXPAND_SEE_MORE_JS → _pause(0.3, 0.7)
     → log + _EXTRACT_POSTS_JS
     ```

7. **`run()` update** — known-URL pre-load before `sync_playwright()`.
   - After `queries = list(qs)` and before `raw_by_query: dict[int, list[dict]] = {}`:
     ```python
     known_urls_by_query: dict[int, set[str]] = {}
     for sq in queries:
         ids = Event.objects.filter(
             source=self.source, search_query=sq
         ).values_list("external_id", flat=True)
         known_urls_by_query[sq.id] = set(ids)
     ```
   - Inside the Playwright loop, replace the `_fetch_raw_posts` call to also pass
     `known_urls=known_urls_by_query.get(sq.id, set())`.
   - `Event` is already imported inside `run()` via `from events.models import Event, SearchQuery`.

---

## Acceptance Criteria

1. `python -c "from events.scrapers.facebook_posts import _CLICK_RECENT_FILTER_JS, _CLICK_SEE_MORE_RESULTS_JS, _COUNT_FRESH_ANCHORS_JS"` exits with code 0.
2. `manage.py scrape facebook_posts` completes without uncaught exceptions.
3. Log output contains at least one line matching `_smart_scroll.*round` for a keyword query.
4. Log output contains one of: `IDLE stop`, `MIN_FRESH_TARGET reached`, or `MAX_ROUNDS` as the stop reason.
5. For a `/search/posts` query, the `_CLICK_RECENT_FILTER_JS` code path executes without error.
6. `grep -n "el\.click()" apps/backend/events/scrapers/facebook_posts.py` returns no matches.
7. `Event.objects.filter(source='facebook_posts').count()` does not decrease after a scrape run.
8. `Event.objects.values('external_id').annotate(c=Count('id')).filter(c__gt=1).count()` returns `0`.
9. `grep -n "_human_scroll" apps/backend/events/scrapers/facebook_posts.py` returns no matches.
10. Code inspection: `known_urls_by_query` block appears before the `with sync_playwright()` line.

---

## Implementation Checklist

- [ ] **Step 1 — Update `_EXPAND_SEE_MORE_JS`**
  - File: `apps/backend/events/scrapers/facebook_posts.py`, lines 79–89
  - Replace bare `el.click()` with inline `humanClick(el)` helper
  - `humanClick(el)`: get `rect = el.getBoundingClientRect()`; dispatch `mouseover`, `mousedown`,
    `mouseup`, `click` as `new MouseEvent(type, {bubbles:true, cancelable:true, clientX: rect.left + Math.random()*rect.width, clientY: rect.top + Math.random()*rect.height})`
  - Keep the IIFE synchronous (no async/await)
  - Verify: `python -c "from events.scrapers.facebook_posts import _EXPAND_SEE_MORE_JS"` exits 0;
    `grep "el\.click()" apps/backend/events/scrapers/facebook_posts.py` returns no lines

- [ ] **Step 2 — Add `_CLICK_RECENT_FILTER_JS` constant**
  - File: `apps/backend/events/scrapers/facebook_posts.py`
  - Insert immediately after the `_EXPAND_SEE_MORE_JS` block (before `_EXTRACT_POSTS_JS`)
  - Three-strategy selector fallback as specified in FR-1
  - Returns boolean
  - Verify: `python -c "from events.scrapers.facebook_posts import _CLICK_RECENT_FILTER_JS"` exits 0

- [ ] **Step 3 — Add `_CLICK_SEE_MORE_RESULTS_JS` constant**
  - File: `apps/backend/events/scrapers/facebook_posts.py`
  - Insert after `_CLICK_RECENT_FILTER_JS`
  - Inline `humanClick` helper (same pattern as Step 1)
  - Excludes elements with `div[dir="auto"]` ancestor
  - Returns integer count
  - Verify: `python -c "from events.scrapers.facebook_posts import _CLICK_SEE_MORE_RESULTS_JS"` exits 0

- [ ] **Step 4 — Add `_COUNT_FRESH_ANCHORS_JS` constant**
  - File: `apps/backend/events/scrapers/facebook_posts.py`
  - Insert after `_CLICK_SEE_MORE_RESULTS_JS`
  - JS function signature: `(knownIds) => { ... }` (array argument from `page.evaluate`)
  - Inline `isPostHref` helper (exact copy from `_EXTRACT_POSTS_JS`)
  - Normalisation: `split('facebook.com/').pop()`, strip trailing `/`, strip `?#` and beyond,
    replace `/` with `_` — must match `_post_external_id()` output character-for-character
  - Returns integer count of anchors not in `Set(knownIds)`
  - Verify: `python -c "from events.scrapers.facebook_posts import _COUNT_FRESH_ANCHORS_JS"` exits 0

- [ ] **Step 5 — Add `_smart_scroll()` module-level function**
  - File: `apps/backend/events/scrapers/facebook_posts.py`
  - Insert between the JS constants block and the `FacebookPostsScraper` class definition
  - Signature: `def _smart_scroll(page, known_urls: set = frozenset(), max_rounds: int = 20) -> None:`
  - Constants block at top: `MAX_IDLE = 4`, `MIN_FRESH_TARGET = 15`, sleep bounds
  - Loop body exactly as specified in FR-5 (13 substeps)
  - Use `_pause` for all sleeps; use `logger` for all log calls
  - Verify: `python -c "from events.scrapers.facebook_posts import _smart_scroll"` exits 0

- [ ] **Step 6 — Remove `_human_scroll` from import line**
  - File: `apps/backend/events/scrapers/facebook_posts.py`, line ~42
  - Remove `_human_scroll` from the `from .facebook_events import ...` list
  - Verify: `grep -n "_human_scroll" apps/backend/events/scrapers/facebook_posts.py` returns 0 lines;
    `python -c "from events.scrapers import facebook_posts"` exits 0

- [ ] **Step 7 — Update `_fetch_raw_posts` method**
  - File: `apps/backend/events/scrapers/facebook_posts.py`, method at line ~716
  - Add `known_urls: set = frozenset()` to signature
  - After `wait_for_selector` block, insert `if "/search/posts" in page.url:` guard calling
    `page.evaluate(_CLICK_RECENT_FILTER_JS)` then `_pause(1.0, 2.0)`
  - Replace `_human_scroll(page)` with `_smart_scroll(page, known_urls)`
  - Verify: method signature updated; `grep "_human_scroll" facebook_posts.py` returns 0 lines

- [ ] **Step 8 — Update `run()` to pre-load known URLs**
  - File: `apps/backend/events/scrapers/facebook_posts.py`, `run()` method
  - After `queries = list(qs)`, before `raw_by_query: dict = {}`, insert `known_urls_by_query`
    pre-load block (ORM query per `sq` using `Event.objects.filter(...).values_list(...)`)
  - Update `_fetch_raw_posts` call-site to pass `known_urls=known_urls_by_query.get(sq.id, set())`
  - Verify: `known_urls_by_query` block is before `with sync_playwright()` line (code inspection)

- [ ] **Step 9 — Manual E2E verification**
  - Run: `cd apps/backend && python manage.py scrape facebook_posts`
  - Confirm: log shows `_smart_scroll` round lines and one stop-reason message
  - Confirm: DB event count non-decreasing
  - Confirm: duplicate-external_id query returns 0
  - User confirmation received before marking plan complete

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `_COUNT_FRESH_ANCHORS_JS` normalisation differs from `_post_external_id()` | Medium | Cross-check JS string char-by-char against Python function during Step 4 |
| FB DOM changes break Recent filter selectors | Medium | Three-fallback strategy degrades gracefully (returns `false`, scrape continues) |
| `humanClick` fires on detached elements | Low | Add `el.offsetParent !== null` guard in both `humanClick` usages |
| `page.evaluate(_COUNT_FRESH_ANCHORS_JS, list(known_urls))` slow for large sets | Low | `known_urls` is per-query; no query will have >10k existing posts |
| Removing `_human_scroll` breaks other usage | Low | Confirm with `grep -n "_human_scroll" facebook_posts.py` before and after removal |

---

## Integration Notes

- **No model/migration changes.** `Event.external_id` is already a stable field.
- **No view/URL changes.** Scraper interface (`manage.py scrape` / `/api/scrapers/`) unchanged.
- **`_pause` import:** Already present in `facebook_posts.py` from `.facebook_events`. No new import.
- **JS constant ordering in file after changes:**
  1. `_EXPAND_SEE_MORE_JS` (updated)
  2. `_CLICK_RECENT_FILTER_JS` (new)
  3. `_CLICK_SEE_MORE_RESULTS_JS` (new)
  4. `_COUNT_FRESH_ANCHORS_JS` (new)
  5. `_EXTRACT_POSTS_JS` (unchanged)
- **ORM pre-load placement:** Consistent with existing pattern — all ORM outside `sync_playwright()`.

---

## Touchpoints

| Surface | File | Change |
|---------|------|--------|
| JS constant `_EXPAND_SEE_MORE_JS` | `facebook_posts.py` | Updated — humanClick replaces bare click |
| JS constant `_CLICK_RECENT_FILTER_JS` | `facebook_posts.py` | New |
| JS constant `_CLICK_SEE_MORE_RESULTS_JS` | `facebook_posts.py` | New |
| JS constant `_COUNT_FRESH_ANCHORS_JS` | `facebook_posts.py` | New |
| Python function `_smart_scroll` | `facebook_posts.py` | New module-level function |
| Method `_fetch_raw_posts` | `facebook_posts.py` | Signature + body updated |
| Method `run` | `facebook_posts.py` | Pre-load block + call-site updated |
| Import line | `facebook_posts.py` | `_human_scroll` removed from import |

---

## Public Contracts

- **`_fetch_raw_posts(self, page, query, max_posts=None, known_urls=frozenset())`** — `known_urls`
  defaults to `frozenset()`, so existing callers without the argument continue to work unchanged.
- **`run()`** — signature unchanged; internal behaviour enhanced.
- **`_smart_scroll`** — module-level but not part of the public scraper API; no external callers.
- **JS constant names** — preserved; only the content of `_EXPAND_SEE_MORE_JS` changes.

---

## Blast Radius

- **Only `facebook_posts.py` changes.** No other repo file is modified.
- The `run()` ORM pre-load adds N extra DB queries (N = number of active `SearchQuery` rows for
  this scraper) before the Playwright block — negligible impact.
- Existing 97 passing tests are not expected to be affected (no unit tests exist for
  `facebook_posts.py`; scraper is tested via manual runs).

---

## Verification Evidence

After implementation, all of the following must be true:

1. `python -c "from events.scrapers.facebook_posts import _CLICK_RECENT_FILTER_JS, _CLICK_SEE_MORE_RESULTS_JS, _COUNT_FRESH_ANCHORS_JS, _smart_scroll"` exits 0.
2. `grep -n "el\.click()" apps/backend/events/scrapers/facebook_posts.py` — zero matches.
3. `grep -n "_human_scroll" apps/backend/events/scrapers/facebook_posts.py` — zero matches.
4. `manage.py scrape facebook_posts` log contains `_smart_scroll` and one of the three stop reasons.
5. Django shell duplicate check: `Event.objects.values('external_id').annotate(c=Count('id')).filter(c__gt=1).count()` returns `0`.

---

## Resume and Execution Handoff

**Execute agent must:**

1. Read `apps/backend/events/scrapers/facebook_posts.py` in full before making any changes.
2. Follow the Implementation Checklist steps in order (Steps 1–9).
3. After Step 6 (import removal), confirm zero `_human_scroll` references remain before continuing.
4. After Step 8, confirm the `known_urls_by_query` block is inside `run()` but before `with sync_playwright()`.
5. Run the manual E2E check in Step 9 as the final verification gate.

**Selected plan file for EXECUTE:** `process/general-plans/active/fb-posts-smart-scroll_PLAN_23-06-26.md`

**No supporting phase files.** This is a single-file, single-session implementation.

---

## Cursor + RIPER-5 Guidance

- **Cursor Plan mode:** Import the Implementation Checklist above. Work through Steps 1–9 in order.
  After Step 5 (`_smart_scroll` added), run a quick smoke import before continuing.
- **RIPER-5:** This plan is the output of PLAN mode. Say `ENTER EXECUTE MODE` to begin.
- If a FB DOM change breaks a selector during testing, treat it as an in-scope fix (update the
  relevant JS constant) without scope escalation.
- After each checklist step, verify the step's own "Verify" bullet before moving to the next.
- **After Step 9 (E2E), stop and confirm user says "it works" before marking plan complete.**
