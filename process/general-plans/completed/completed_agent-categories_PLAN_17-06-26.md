# AI-Powered Event Category Standardization (`agent_categories`)

**Date**: 2026-06-17
**Complexity**: COMPLEX (multi-phase)
**Status**: ✅ COMPLETED (2026-06-17)

**Completion notes:**
- All 4 phases delivered
- 915 events backfilled with canonical categories via Claude Haiku
- Auto-categorization wired into scraper pipeline
- Events page and Dashboard donut chart updated
- 58 backend tests pass, frontend type-check clean

**Context**: `process/context/all-context.md` · `process/context/tests/all-tests.md`

---

## Overview

Add a stored, AI-assigned `agent_categories` column to `events_event` that maps every event's raw/noisy category string into a canonical taxonomy using Claude. Backfill the 915 existing events, integrate categorization into the post-scrape pipeline so new events are classified automatically, and surface `agent_categories` on the Events table page (replacing the raw badge) and the Dashboard donut chart.

**Problem today**: Raw `Event.category` values are scraper-specific noise — distance lists (`"10K, 5K, 3K"`), ticket tiers (`"SUB1 Elite, SUB1 Competitor, Open Wave"`), or blank. The existing `normalize_category()` in `categories.py` is a regex heuristic that handles the common run patterns but cannot handle novel inputs, multi-label scenarios, or future sources. It runs only at query time and is never persisted.

**What this plan delivers**:
- `agent_categories: JSONField` on `Event` — a stored list of 1–3 canonical strings (e.g. `["Fun Run / Road Race"]`, `["Sports & Fitness", "Festival"]`)
- `manage.py categorize_events` management command — shells out to the local `claude` CLI (no API key required, uses Claude Code subscription)
- Auto-classify hook in `BaseScraper.run()` — new events get classified immediately after each scrape
- Updated `api_events_by_category` endpoint to use `agent_categories`
- Updated Events page: show `agent_categories` badges instead of raw `category`
- Updated Dashboard donut chart: driven by `agent_categories`

---

## Canonical Category Taxonomy

These are the only valid values for `agent_categories` items. Claude is instructed to pick from this list only:

| Canonical Label | Covers |
|---|---|
| `Fun Run / Road Race` | distance runs, road races, fun runs, color runs, dog runs |
| `Trail Run` | trail runs, mountain races |
| `Triathlon / Duathlon` | tri, duathlon, multi-sport |
| `Cycling` | bike race, cycling event |
| `Swimming` | swim meet, open water swim |
| `Sports & Fitness` | general sports, tournaments, coaching, pickleball, basketball, etc. |
| `Music & Concert` | live music, bands, concerts, gigs |
| `Festival` | cultural festival, street fair, community festival |
| `Conference / Seminar` | summit, conference, talk, forum |
| `Workshop / Training` | class, workshop, certification, coaching clinic |
| `Food & Dining` | food fair, culinary event, dining experience |
| `Arts & Culture` | art exhibit, gallery, cultural performance |
| `Theater & Performing Arts` | theater, play, production, improv |
| `Charity / Fundraiser` | benefit, charity walk/run, fundraiser |
| `Other` | fallback — used only when nothing else fits |

**Multi-label rule**: An event may have 1–2 labels (rarely 3). If the raw data clearly maps to two canonical buckets (e.g. "Sports Festival"), assign both. Always assign at least one.

---

## Architecture Decisions

### Column: `agent_categories: JSONField(default=list)`
- Stores a Python list of canonical strings, e.g. `["Fun Run / Road Race"]`
- `default=list`, `blank=True` — safe to be empty before classification
- Never overwritten on re-scrape (same invariant as `organizer.status`)
- Can be reset by running `categorize_events --reset --source <key>`

### AI: `claude` CLI via subprocess (no API key required)
- Shells out to the local Claude Code CLI — uses the developer's Claude Code subscription
- CLI command is configurable via `CLAUDE_CLI_CMD` env var (default: `claude`) because different installs use different names (e.g. `claude-ojt`, `claude-dev`)
- Input per event: `name`, `category` (raw), `description[:200]`
- Output: JSON array of category strings from the canonical list
- Batch size: 20 events per CLI call to keep prompt size manageable
- Call pattern: `subprocess.run([CLAUDE_CLI_CMD, '-p', prompt, '--output-format', 'json'], capture_output=True, text=True, timeout=60)`

### Post-scrape integration: hook in `BaseScraper.run()`
- `save_events()` currently returns `{"created": N, "updated": M}` — extend to return `{"created": N, "updated": M, "ids": [list of event PKs created/updated]}`
- `BaseScraper.run()` receives those IDs and calls `categorize_events_by_ids(ids)` before returning
- This keeps categorization in-process and synchronous — no queue, no second command needed for the happy path
- Fallback: `manage.py categorize_events --uncategorized` for manual runs and cron safety net

### Dashboard donut chart: switch source to `agent_categories`
- New API endpoint `GET /api/events/by-agent-category/` (or update existing `by-category`)
- Recommend: update the existing `api_events_by_category` to prefer `agent_categories` when populated; fall back to `normalize_category(category)` for unclassified events (graceful degradation during backfill)
- Frontend: no route change, just consumes the updated endpoint response

### Events page: show `agent_categories` as primary badges
- If `agent_categories` is non-empty, render those badges
- If empty (not yet classified), fall back to raw `category` badge (existing behavior)
- API: add `agent_categories` field to `api_events` serializer output

---

## Touchpoints

| Layer | File | Change |
|---|---|---|
| Model | `apps/backend/events/models.py` | Add `agent_categories = models.JSONField(default=list, blank=True)` to `Event` |
| Migration | `apps/backend/events/migrations/0010_event_agent_categories.py` | New migration |
| AI service | `apps/backend/events/ai_categories.py` | New module: `categorize_events_by_ids(ids)`, `batch_categorize(events)` |
| Mgmt command | `apps/backend/events/management/commands/categorize_events.py` | New management command |
| Scraper base | `apps/backend/events/scrapers/base.py` | `save_events()` returns IDs; `BaseScraper.run()` calls categorizer |
| Backend API | `apps/backend/events/views.py` | `api_events` adds `agent_categories`; `api_events_by_category` updated |
| Frontend types | `apps/frontend/src/lib/types.ts` | `EventRow.agent_categories: string[]` |
| Frontend API | `apps/frontend/src/lib/api.ts` | Pass through `agent_categories` |
| Events page | `apps/frontend/src/routes/events/+page.svelte` | Render `agent_categories` badges |
| Dashboard | `apps/frontend/src/routes/+page.svelte` | No change (data changes come via API) |

---

## Public Contracts

- `Event.agent_categories`: `list[str]` — canonical labels only, never raw scraper values. Empty list = not yet classified.
- `api_events` response: adds `agent_categories: string[]` field to each event object.
- `api_events_by_category` response: same shape as today (`{category, count}[]`) but sourced from `agent_categories` first.
- `categorize_events_by_ids(ids: list[int]) -> dict`: callable from both the management command and `BaseScraper.run()`.
- Management command: `manage.py categorize_events [--uncategorized] [--all] [--source SOURCE] [--limit N] [--dry-run]`

---

## Blast Radius

- **Breaking**: none — `agent_categories` is additive; existing `category` field is untouched.
- **API consumers**: `api_events` adds a field (backwards-compatible). `api_events_by_category` changes its source data — the donut chart output will shift once backfill runs. Warn in deploy notes.
- **Scraper runs**: `BaseScraper.run()` will make Claude API calls during scraping. If the API key is missing or quota is exceeded, categorization should fail gracefully (log warning, do not crash the scraper). New events still save; they just have `agent_categories=[]` until the next manual run.
- **Tests**: `tests.py` currently has 49 tests. The new AI service must be mockable — `categorize_events_by_ids` should accept an injectable `llm_fn` parameter (or use `unittest.mock.patch`) so tests don't hit the Claude API.
- **Migrations**: adds one nullable/defaulted column — safe to run on a live DB, no data loss.
- **Env var**: `CLAUDE_CLI_CMD` — optional, defaults to `"claude"`. Document in `config/settings.py` and `apps/backend/.env.example`. If the command is not found on PATH, `categorize_events_by_ids` raises a clear `FileNotFoundError` with a helpful message.

---

## Phased Delivery Plan

### Phase 1 — Backend: Model + AI Service + Management Command

**Goal**: `agent_categories` exists in the DB; `manage.py categorize_events` can classify events; nothing in the scraper or frontend yet.

**Steps**:
1. Add `agent_categories = models.JSONField(default=list, blank=True)` to `Event` in `models.py`
2. Create migration `0010_event_agent_categories.py` — `python manage.py makemigrations`
3. Apply migration locally: `python manage.py migrate`
4. Create `apps/backend/events/ai_categories.py`:
   - Define `CANONICAL_CATEGORIES` list (the 15 buckets above)
   - `batch_categorize(events: list[Event], llm_fn=None) -> dict[int, list[str]]` — sends batches of 20 to Claude Haiku, returns `{event_id: [labels]}`
   - Claude prompt: structured JSON output, system prompt enforces the canonical list
   - `categorize_events_by_ids(ids: list[int], llm_fn=None, batch_size=20) -> int` — fetches events by IDs, calls `batch_categorize`, bulk-updates `agent_categories`, returns count classified
5. Create `apps/backend/events/management/commands/categorize_events.py`:
   - Options: `--uncategorized` (default), `--all`, `--source SOURCE`, `--limit N`, `--dry-run`
   - Prints progress and final count
6. Register `CLAUDE_CLI_CMD` env var in `config/settings.py` (read from env, default `"claude"`) — logs a clear error if the command is not found on PATH
7. Create/update `apps/backend/.env.example` with `CLAUDE_CLI_CMD=claude  # change to claude-ojt, claude-dev, etc.`

**Verification**:
- `python manage.py makemigrations --check` passes with no new migrations
- `python manage.py migrate` applies cleanly on a fresh DB
- `python manage.py categorize_events --limit 5 --dry-run` runs without error (mocked or live)
- `python manage.py categorize_events --limit 5` classifies 5 events; check `Event.objects.filter(agent_categories__len__gt=0).count() == 5`
- Unit tests: mock `llm_fn` to return a fixed classification; assert `agent_categories` saved correctly

### Phase 2 — Backfill All Existing Events

**Goal**: All 915 existing events in the Neon DB have `agent_categories` populated.

**Steps**:
1. Set `ANTHROPIC_API_KEY` in the backend environment (Neon DB connection + env)
2. Run: `python manage.py categorize_events --all`
3. Verify: `SELECT COUNT(*) FROM events_event WHERE agent_categories = '[]'` should be 0 (or close to it)
4. Spot-check 10 events in Django admin to confirm sensible labels

**Verification**:
- SQL: `SELECT jsonb_array_elements_text(agent_categories::jsonb) as cat, COUNT(*) FROM events_event GROUP BY cat ORDER BY count DESC;`
- Confirm "Fun Run / Road Race" is the largest bucket (>700 events based on raw data)
- Confirm no events have categories outside the canonical list

### Phase 3 — Scraper Integration

**Goal**: New events get classified automatically when any scraper runs.

**Steps**:
1. Update `save_events()` in `scrapers/base.py` to collect and return newly created/updated event PKs in the result dict: `{"created": N, "updated": M, "event_ids": [...]}`
2. In `BaseScraper.run()`, after `save_events()` / `save_organizers()` returns, call `categorize_events_by_ids(result["event_ids"])` — wrapped in `try/except` so API failures are logged but don't propagate
3. Update `scraper_webhook` in `views.py` to pass through the updated result dict (IDs are internal; no need to expose in the webhook response)
4. Add `ANTHROPIC_API_KEY` to the n8n environment if scraper webhook is used via n8n

**Verification**:
- Run `python manage.py scrape planout` (small, fast)
- Confirm new/updated events from that run have `agent_categories` populated
- Run with `ANTHROPIC_API_KEY` unset — confirm scraper still completes, logs a warning, events saved with `agent_categories=[]`

### Phase 4 — API + Frontend Integration

**Goal**: Events page shows `agent_categories` badges; Dashboard donut chart reflects canonical categories.

**Steps**:

**Backend**:
1. `api_events` view: add `"agent_categories": e.agent_categories` to the serializer dict
2. `api_events_by_category` view: rewrite aggregation to use `agent_categories`:
   - Fetch all events with non-empty `agent_categories`
   - Python-side: unnest each event's list and tally counts per label
   - Fall back to `normalize_category(e.category)` for events with `agent_categories=[]` (during/after backfill transition period)
   - Keep same response shape: `[{category, count}]`, Top-8 + Other

**Frontend**:
1. `types.ts`: add `agent_categories: string[]` to `EventRow`
2. `events/+page.svelte`: in the category cell, prefer `agent_categories` badges if non-empty; otherwise render existing `category` Badge as fallback
3. Dashboard `+page.svelte`: no template change needed — the donut chart data comes from `api_events_by_category`, which already changed on the backend

**Verification**:
- `pnpm --filter frontend check` passes (no TS errors)
- Start full dev stack (`pnpm dev`) and visit `/events` — category column shows canonical labels
- Visit `/` — donut chart shows meaningful canonical buckets (not raw distance strings)
- Filter by `agent_categories` in the browser network tab to confirm the API response shape

---

## Resume and Execution Handoff

**Plan path**: `process/general-plans/active/agent-categories_PLAN_17-06-26.md`

**Execute one phase at a time.** Pass this plan path explicitly when invoking `vc-execute-agent`. After each phase, run the listed verification steps before proceeding to the next.

**Phase dependencies**:
- Phase 2 requires Phase 1 to be complete and `ANTHROPIC_API_KEY` to be available
- Phase 3 can start as soon as Phase 1 is done (does not require backfill to finish)
- Phase 4 requires Phase 1 (column exists) and Phase 2 (enough data to validate the UI)

**Environment prerequisite** (must be in place before Phase 1 verification / Phase 2):
```
# apps/backend/.env
CLAUDE_CLI_CMD=claude-ojt   # or: claude, claude-dev — whatever resolves on this machine's PATH
```
Add to `apps/backend/.env` (create if not exists). Load in `config/settings.py` via `os.environ.get("CLAUDE_CLI_CMD", "claude")`. Verify the command resolves: `which $CLAUDE_CLI_CMD`.

**Migration state after Phase 1**:
- Next migration number: `0010`
- Local: `python manage.py migrate`
- Neon DB: apply via `DATABASE_URL` or `python manage.py migrate --database=neon` (configure in settings if needed)

**Resuming after compaction**:
- Check `Event.objects.filter(agent_categories__len__gt=0).count()` to see how many events are classified
- Check `apps/backend/events/ai_categories.py` exists to know if Phase 1 is done
- Check `apps/backend/events/migrations/0010_*.py` exists to know if migration was created
- Check `api_events` response for `agent_categories` field to know if Phase 4 is done

---

## Red-Team / Risk Questions

1. **Claude API rate limits**: 915 events at 20/batch = ~46 API calls. Haiku has generous limits. If rate-limited, add `time.sleep(0.5)` between batches.
2. **Hallucinated categories**: The prompt must instruct Claude to only return values from the canonical list. Validate the CLI output — reject any label not in `CANONICAL_CATEGORIES` and fall back to `["Other"]` for that event.
3. **Cost**: Uses Claude Code subscription — no per-token billing for CLI calls. Subprocess overhead per batch call is ~1–2 seconds; 46 batches for the full backfill = ~2–4 minutes total.
4. **Scraper latency**: Categorizing 50 new events after a scrape run = ~3 CLI calls (~3–6 seconds). Acceptable for manual/cron scraping. Wrapped in `try/except` so CLI failures never crash the scraper.
5. **Re-categorization on re-scrape**: `categorize_events_by_ids` with the set of updated IDs will re-classify even existing events. This is fine — the canonical list is stable. Add `--skip-classified` flag to the management command to skip events that already have labels, for cron safety.
6. **Empty categories**: Events from `planout` and `allevents_cdo` often have no raw `category`. Claude can still classify based on event name and description alone — include a note in the prompt.

---

## Verification Evidence (definition of done)

- [ ] `python manage.py makemigrations --check` exits 0 after Phase 1
- [ ] `python manage.py test events` passes (all 49 + new tests for `ai_categories.py`)
- [ ] `python manage.py categorize_events --limit 5` classifies 5 events with valid canonical labels
- [ ] `SELECT COUNT(*) FROM events_event WHERE agent_categories = '[]'` = 0 after backfill
- [ ] `pnpm --filter frontend check` exits 0
- [ ] `/events` page shows canonical category badges
- [ ] `/` dashboard donut chart shows canonical buckets (not raw distance strings)
- [ ] Scraper run creates new event → event has non-empty `agent_categories` without manual intervention

---

---

## Acceptance Criteria

- `agent_categories` column exists on `events_event` (JSONField, default `[]`)
- All existing events have at least one canonical category label
- New events receive `agent_categories` automatically after each scraper run
- Events page displays `agent_categories` badges (not raw category strings)
- Dashboard donut chart uses `agent_categories` as its data source
- All 49 existing backend tests still pass; new AI service tests pass with mocked LLM

---

## Phase Completion Rules

- A phase is **CODE DONE** when all code changes for that phase are written and committed.
- A phase is **VERIFIED** only when all verification steps for that phase pass (tests, manual checks, SQL spot-checks).
- Do not advance to the next phase until the current phase is **VERIFIED**.
- Phase 2 (backfill) requires `ANTHROPIC_API_KEY` to be set in the environment — confirm before starting.
- If `categorize_events` fails partway through, it is safe to re-run — already-classified events are skipped by default.
- Post-phase testing: run `python manage.py test events` after Phases 1 and 3; run `pnpm --filter frontend check` after Phase 4.

---

> **Next step for EXECUTE**: Start with Phase 1. Invoke `vc-execute-agent` with this plan file path and instruct it to complete Phase 1 steps 1–6, then run Phase 1 verification before stopping.
