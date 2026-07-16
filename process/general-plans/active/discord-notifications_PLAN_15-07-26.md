# Discord Notifications for Veent Event Scraper

**Date:** 15-07-26
**Complexity:** SIMPLE
**Status:** ⏳ PLANNED

---

## Table of Contents

- [Overview](#overview)
- [Goals and Success Metrics](#goals-and-success-metrics)
- [Phase Completion Rules](#phase-completion-rules)
- [Execution Brief](#execution-brief)
- [Scope](#scope)
- [Assumptions and Constraints](#assumptions-and-constraints)
- [Functional Requirements](#functional-requirements)
- [Non-Functional Requirements](#non-functional-requirements)
- [Acceptance Criteria](#acceptance-criteria)
- [Implementation Checklist](#implementation-checklist)
- [Risks and Mitigations](#risks-and-mitigations)
- [Integration Notes](#integration-notes)
- [Touchpoints](#touchpoints)
- [Public Contracts](#public-contracts)
- [Blast Radius](#blast-radius)
- [Verification Evidence](#verification-evidence)
- [Resume and Execution Handoff](#resume-and-execution-handoff)
- [Cursor + RIPER-5 Guidance](#cursor--riper-5-guidance)

---

## Overview

Add one-way Discord notifications to the Veent Event Scraper so operators are alerted when scrapers start, succeed, fail, or hit a session-expiry condition — without requiring them to watch the SvelteKit dashboard. Implementation uses Discord webhooks (no bot token required) delivered from a new `notifications.py` module inside `apps/backend/events/`. The module is called directly from the two existing run-lifecycle files (`run_scraper_job.py` and `runner.py`). The feature is fully opt-in: if `DISCORD_WEBHOOK_URL` is not set in the environment, all notification calls are silent no-ops.

In addition to the basic webhook notifications (Phase 1-5), this plan includes further additions:

- **Phase 6 — Live run-all scoreboard:** Instead of posting a new message per scraper, `run-all` maintains ONE Discord message that is edited in real-time as each scraper finishes. Requires a new `ScraperRun.discord_message_id` field and a DB migration.
- **Phase 7 — Data usage display:** Both items scraped (created/updated counts) and DataImpulse proxy bandwidth are surfaced in the scoreboard embed. Bandwidth data comes from the existing `BandwidthLog` model; no new tracking is added for the 13 requests-based scrapers in this phase.
- **Phase 8 — Mid-run per-keyword progress notifications:** The scoreboard `running…` line is upgraded to show live keyword progress (e.g. `3/8 kw`) for the two social scrapers. Requires a signature fix to `facebook_posts.py` and enriching the `on_progress` payload in `facebook_events.py`.

---

## Goals and Success Metrics

- Operators receive a Discord embed within ~5 seconds of each scraper lifecycle event.
- Zero existing tests break.
- Zero scraper runs are blocked or delayed by a failing Discord call.
- Feature is invisible when `DISCORD_WEBHOOK_URL` is absent (no error, no log spam).
- Success/failure/session-expiry messages are visually distinct (color-coded embeds).
- `run-all` operations produce a single live scoreboard message that reflects the final state of every scraper in one place.
- Bandwidth consumed per scraper (where tracked) and total for the batch is visible in the scoreboard.
- For `facebook_events` batch runs, the scoreboard shows live keyword progress while the scraper is running.

---

## Phase Completion Rules

A phase is NOT complete until:

1. **Integration Test** - Works with the other system pieces (run lifecycle calls notification)
2. **Manual Test** - A real Discord message appears in the test channel
3. **Data Verification** - ScraperRun DB row is unaffected by any non-schema-change phase; migration phases verified by `python manage.py showmigrations`
4. **Error Handling** - Discord call failure does not raise in the caller
5. **User Confirmation** - Operator confirms the embed content is correct

Status meanings:
- ⏳ PLANNED - Not started
- 🔨 CODE DONE - Written but not E2E tested
- 🧪 TESTING - Currently being tested
- ✅ VERIFIED - Tested AND confirmed working
- 🚧 BLOCKED - Has issues

After each phase, document:
- [ ] What was tested manually
- [ ] ScraperRun DB row unchanged (run `SELECT status, error_message FROM events_scraperrun ORDER BY id DESC LIMIT 1;`)
- [ ] Errors encountered and fixed
- [ ] User confirmation received

---

## Execution Brief

### Phase 1 — Env var + settings wiring

**What happens:** Add `DISCORD_WEBHOOK_URL` to `apps/backend/config/settings.py` using the existing `os.environ.get` pattern. Add the placeholder line to `apps/backend/.env` (commented out). No functional code yet.

**Test:** `python manage.py shell -c "from django.conf import settings; print(settings.DISCORD_WEBHOOK_URL)"` prints an empty string or the test URL.

**Verify:** No import errors, no migration needed.

**Done when:** Settings shell test returns expected value.

---

### Phase 2 — `notifications.py` module

**What happens:** Create `apps/backend/events/notifications.py` with a single public function `notify_scraper_event(event_type, **kwargs)` and a private `_post_embed(payload)` helper. All five event types are handled. Discord is called in a fire-and-forget daemon thread so the caller is never blocked. All exceptions are caught and logged at WARNING level; they never propagate.

**Test:** Run `python -c "from events.notifications import notify_scraper_event; notify_scraper_event('started', scraper_key='test')"` from `apps/backend/` with a real `DISCORD_WEBHOOK_URL` pointing at a private test channel. Confirm embed appears.

**Verify:** Discord channel receives the embed. No exception raised in the process.

**Done when:** Embed appears in test channel with correct title, color, and fields.

---

### Phase 3 — Hook into `run_scraper_job.py`

**What happens:** Import `notify_scraper_event` and add calls at the four points in `run_scraper_job.py`:
  1. After the QUEUED→RUNNING conditional update succeeds: call `started`.
  2. In the `except Exception` block (Path 2 — scraper.run() fails): call `failed` or `session_expired` depending on `error_message` prefix.
  3. In the unknown-key branch (Path 3): call `failed`.
  4. After `run.save(...)` for SUCCESS: call `success`.

**Test:** Trigger a real scraper run via the SvelteKit UI or `manage.py scrape`. Confirm the started and success (or failed) embeds appear in Discord.

**Verify:** DB row `status` and `error_message` fields are unchanged from pre-notification behavior. Discord shows correct embed for each path.

**Done when:** Full run cycle produces started + success embeds (or started + failed for an intentional bad key).

---

### Phase 4 — Hook into `runner.py` (subprocess launch failure, Path 1)

**What happens:** In `trigger_scraper_run`, the `except Exception` block after `subprocess.Popen` currently saves the run as FAILED and re-raises. Add a `notify_scraper_event('failed', ...)` call before the `raise` so this path also notifies. The `raise` is kept — this preserves existing error propagation.

**Test:** Simulate a Popen failure (temporarily rename `manage.py` or pass a bad command) and confirm the `failed` embed appears.

**Verify:** The exception still propagates to the caller (HTTP 500 response as before). Discord receives the failed embed.

**Done when:** failed embed appears; existing error behavior is unchanged.

---

### Phase 5 — Run-all summary notification

**What happens:** Modify `api_scraper_run_all` in `views.py` to call `notify_scraper_event('run_all_summary', created=created, skipped=skipped)` after the loop finishes. This gives operators a single aggregate message for the weekly automated scrape-all triggered by n8n.

**Note:** This phase will be superseded by Phase 6 (live scoreboard), which replaces the static summary with an editable embed. Phase 5 should still be implemented as a checkpoint; Phase 6 then modifies the behaviour.

**Test:** POST to `/api/scrapers/run-all/` (via curl or n8n test trigger). Confirm a summary embed appears in Discord.

**Verify:** Embed lists the correct triggered and skipped scraper keys.

**Done when:** Summary embed is accurate and appears within 5 seconds of the run-all call.

---

### Phase 6 — Live run-all scoreboard (message editing)

**What happens:** Replace the static `run_all_summary` approach from Phase 5 with a single Discord message that is edited in real-time as each scraper finishes.

#### DB schema change

Add a new nullable field to `ScraperRun`:

```
ScraperRun.discord_message_id = models.CharField(max_length=30, null=True, blank=True, db_index=True)
```

Create migration `apps/backend/events/migrations/0028_scraperrun_discord_message_id.py` (0027 is the current highest).

#### Flow

1. `api_scraper_run_all()` in `views.py`: after kicking off all subprocesses, call `post_run_all_start(scraper_keys)` → returns `message_id` (string) or `None` if webhook is unset.
2. Bulk-update all `ScraperRun` rows created in that batch: `ScraperRun.objects.filter(id__in=run_ids).update(discord_message_id=message_id)`.
3. On terminal status in `run_scraper_job.py` (success / failed / session_expired): if `run.discord_message_id` is set, call `patch_run_all_progress(run.discord_message_id)`. Otherwise (individual run, not part of a batch), fall through to the existing single-message notify path unchanged.
4. `patch_run_all_progress` queries all `ScraperRun` rows sharing that `discord_message_id`, rebuilds the full grid embed (including bandwidth via `BandwidthLog`), and PATCHes the Discord message.

#### Discord API for editing

The webhook URL has the form `https://discord.com/api/webhooks/{webhook_id}/{webhook_token}`.

- Initial POST (with `?wait=true` to get the message object back): `POST {DISCORD_WEBHOOK_URL}?wait=true`
- Edit: `PATCH https://discord.com/api/webhooks/{webhook_id}/{webhook_token}/messages/{message_id}`

Parse `webhook_id` and `webhook_token` by splitting `DISCORD_WEBHOOK_URL` on `/` — the last two path segments are token and id respectively: `parts = url.rstrip('/').split('/'); token = parts[-1]; webhook_id = parts[-2]`.

#### New functions in `notifications.py`

- `post_run_all_start(scraper_keys: list[str]) -> str | None` — builds the initial "all queued" embed, POSTs with `?wait=true`, parses the returned JSON for `id`, returns it. Returns `None` if `DISCORD_WEBHOOK_URL` is unset or the POST fails.
- `patch_run_all_progress(message_id: str, runs: list[ScraperRun], bandwidth_by_run: dict[int, int]) -> None` — rebuilds the scoreboard embed and PATCHes via the edit endpoint. Runs in a daemon thread, all exceptions caught and logged at WARNING.
- `_build_scoreboard_embed(runs: list[ScraperRun], bandwidth_by_run: dict[int, int]) -> dict` — private; constructs the embed dict with the grid rows and footer totals.
- `_format_bytes(n: int | None) -> str` — private; formats byte count to human-readable string (see Phase 7).

#### Scoreboard embed format

```
Title:  🔄 Run-All Scrape — Mon 15 Jul 2:00 AM UTC
Color:  blue=in-progress (3447003), green=all done (5763719), red=any failed (15548997)

Body (one line per scraper, monospace via code block):
  ✅ allevents      +24  upd 3    12s   2.1 MB
  ✅ luma           +8   upd 0     8s    —
  🔄 eventbrite     running…
  ⏳ happeningnext  queued
  ❌ planout        FAILED — KeyError: 'date'

Footer:
  Progress: 2/7  •  Total created: 32  •  Updated: 3  •  Bandwidth: 2.1 MB
```

Status emoji mapping:
- ⏳ QUEUED
- 🔄 RUNNING
- ✅ SUCCESS
- ❌ FAILED
- ⚠️ SESSION_EXPIRED

Duration: `(run.finished_at - run.started_at).total_seconds()` formatted as `12s` or `1m 5s`. Show `—` if not finished.
Bandwidth column: see Phase 7. Show `—` for scrapers where no `BandwidthLog` row exists.

The embed color reflects the overall batch state: blue while any scrapers are still running or queued, green if all finished with SUCCESS/SESSION_EXPIRED, red if any finished with FAILED.

#### Changes to `views.py`

In `api_scraper_run_all`:
1. Collect the `run.id` values for every `ScraperRun` created in the batch (already available via `trigger_scraper_run` return or a post-loop query: `run_ids = list(ScraperRun.objects.filter(batch_id=...) ...` — see runner.py for how runs are created; alternatively query by `created_at` window if no batch field exists).
2. Call `message_id = post_run_all_start(list(SCRAPERS.keys()))`.
3. If `message_id` is not None: `ScraperRun.objects.filter(id__in=run_ids).update(discord_message_id=message_id)`.
4. Remove (or leave as dead code) the old `notify_scraper_event('run_all_summary', ...)` call from Phase 5.

**Implementation note on collecting run_ids:** `trigger_scraper_run` in `runner.py` returns the `ScraperRun` object. Collect these in a list during the `for key in SCRAPERS` loop in `views.py`:
```
runs_created = []
for key in ...:
    run = trigger_scraper_run(key)
    runs_created.append(run)
run_ids = [r.id for r in runs_created]
```
Verify that `trigger_scraper_run` currently returns the run object; if it returns None or raises on ALREADY_RUNNING, handle gracefully (skip None values in the list).

#### Changes to `run_scraper_job.py`

After saving terminal status (success / failed / session_expired), before the existing single-run notify call:

```python
if run.discord_message_id:
    # Part of a run-all batch — patch the live scoreboard
    from django.db.models import Sum
    all_runs = list(ScraperRun.objects.filter(discord_message_id=run.discord_message_id))
    bw_by_run = {
        r.id: (BandwidthLog.objects.filter(scraper_run=r).aggregate(total=Sum('bytes_transferred'))['total'] or 0)
        for r in all_runs
    }
    patch_run_all_progress(run.discord_message_id, all_runs, bw_by_run)
else:
    # Individual run — post new message (existing behaviour)
    notify_scraper_event(...)
```

Add import `from events.notifications import patch_run_all_progress` alongside the existing `notify_scraper_event` import.

**Test:** Trigger a full run-all via `/api/scrapers/run-all/`. Confirm:
1. One initial Discord message appears with all scrapers in ⏳ queued state.
2. As each scraper finishes the message is edited in place (not re-posted).
3. Final edit shows all scrapers with correct status, counts, and bandwidth.

**Verify:** `ScraperRun.discord_message_id` is populated for all rows in the batch. Migration applied cleanly. No new messages posted for individual scraper completions within a run-all.

**Done when:** Live scoreboard message shows accurate final state for all scrapers in one message.

---

### Phase 7 — Data usage display

**What happens:** Surface both items scraped and proxy bandwidth in all relevant notification surfaces.

#### Items scraped

`created_count` and `updated_count` already exist on every `ScraperRun` row and are already included in the Phase 2 `success` embed. No additional work needed for individual-run notifications.

For the scoreboard embed (Phase 6), each grid row shows `+{created}  upd {updated}` from the run object directly.

#### Proxy bandwidth

The `BandwidthLog` model already exists with fields:
- `source` (CharField)
- `proxy_type` (choices: PROXY_DATAIMPULSE, PROXY_FREE)
- `bytes_transferred` (BigIntegerField)
- `scraper_run` (FK to ScraperRun)

`log_bandwidth()` in `runner.py` already writes rows for scrapers that return `total_bytes`. Currently only the two FB scrapers (`facebook_events.py`, `facebook_posts.py`) return `total_bytes`.

The 13 requests-based scrapers do NOT currently track bandwidth. Expanding bandwidth tracking to those scrapers is a **separate future task** — not in scope for this plan. The scoreboard will show `—` in the bandwidth column for those scrapers.

#### `_format_bytes` helper

Add a private helper to `notifications.py`:

```
_format_bytes(n: int | None) -> str
```

- `None` or `0` → `"—"`
- `< 1024` → `"{n} B"`
- `< 1024**2` → `"{n/1024:.1f} KB"`
- `< 1024**3` → `"{n/1024**2:.1f} MB"`
- `>= 1024**3` → `"{n/1024**3:.2f} GB"`

#### Where bandwidth is displayed

| Surface | What is shown |
|---|---|
| Individual-run `success` embed | No bandwidth column (FB scrapers only have it; not worth showing for one-off runs in this phase) |
| Scoreboard grid row | Bandwidth column from `BandwidthLog.objects.filter(scraper_run=run).aggregate(Sum("bytes_transferred"))` — `"—"` if no row |
| Scoreboard footer | `Bandwidth: {_format_bytes(total_bytes)}` — sum across all runs in the batch; `"—"` if zero |

**Note:** Individual-run `success` embed bandwidth display is deferred. If desired later, add `bandwidth_bytes` kwarg to `notify_scraper_event('success', ...)` call in `run_scraper_job.py` and display via `_format_bytes`.

**Test:** Trigger a run-all that includes at least one FB scraper. Confirm the bandwidth column shows a non-zero value for that scraper and `—` for non-FB scrapers.

**Verify:** `BandwidthLog` rows exist for the FB scrapers (`SELECT * FROM events_bandwidthlog ORDER BY id DESC LIMIT 5;`). Footer total matches sum.

**Done when:** Scoreboard correctly shows bandwidth for FB scrapers and `—` for all others.

---

### Phase 8 — Mid-run per-keyword progress notifications

**What happens:** While `facebook_events` is running inside a batch, the scoreboard `running…` line is upgraded to show live keyword progress (e.g. `🔄 facebook_events    3/8 kw`). This requires three changes:

1. **Fix `facebook_posts.py` signature** — `run()` at line 1023 does not accept `on_progress`, causing a `TypeError` whenever `run_scraper_job.py` passes `on_progress=flush_progress`. Add `on_progress=None` as the last parameter of `run()`. No call to `on_progress` is added inside the method body — `facebook_posts` does not have a per-keyword loop in the same sense, so progress reporting is deferred.

2. **Enrich `on_progress` payload in `facebook_events.py`** — The existing `on_progress` call is at line 1575–1579, inside the `for i, (sq, location_suffix) in enumerate(work_items, 1):` loop (line 1386). The loop counter `i` (1-based), total `len(work_items)`, and the just-saved per-keyword counts from `save_events` are all in scope. Change the payload dict from:
   ```python
   {"total_bytes": self._bytes_transferred}
   ```
   to:
   ```python
   {
       "total_bytes": self._bytes_transferred,
       "keyword_index": i,
       "keyword_total": len(work_items),
       "keyword_created": result["created"],
       "keyword_updated": result["updated"],
   }
   ```
   `result` is the return value of `save_events(self.source, cards)` at line 1559, which is in scope at the `on_progress` call site. No other changes to `facebook_events.py`.

3. **Push a mid-run scoreboard PATCH from `flush_progress` in `run_scraper_job.py`** — `flush_progress` (defined at line 203) currently merges the incoming dict into `ScraperRun.extra_counts` via a DB update and keeps an in-memory copy in sync. After the merge, add a conditional PATCH: if `"keyword_index"` is present in `data` AND `run.discord_message_id` is set (i.e. this is a batch run), call `self._patch_batch_scoreboard(run)`. The scoreboard rebuild reads `run.extra_counts` live from DB, so the keyword progress written just above is immediately visible.

   The `flush_progress` closure is defined inside `Command.handle()` and already has `run` in scope, but does not have access to `self` (the `Command` instance). Two options: (a) convert the closure to a method or (b) inline the scoreboard call. Preferred: move the scoreboard call into a helper that is callable without `self`, or reference `self` explicitly by capturing it in the closure. Use option (b): after the `except Exception` guard inside `flush_progress`, add:
   ```python
   if "keyword_index" in data and run.discord_message_id:
       self._patch_batch_scoreboard(run)
   ```
   Since `flush_progress` is a nested function defined inside `handle()`, `self` is already accessible in its closure scope.

4. **Update `_build_scoreboard_embed` in `notifications.py`** — In the `elif status == "running":` branch (currently renders `running…`), check `run.extra_counts` for `keyword_index` and `keyword_total`. If both are present and `keyword_total > 0`, render:
   ```
   🔄 facebook_events    3/8 kw
   ```
   Otherwise fall back to `running…`. The check is:
   ```python
   ec = run.extra_counts or {}
   ki = ec.get("keyword_index")
   kt = ec.get("keyword_total")
   progress = f"{ki}/{kt} kw" if ki is not None and kt else "running…"
   lines.append(f"{emoji} {key:<16} {progress}")
   ```
   No DB or schema changes required — `extra_counts` is already a JSONField on `ScraperRun`.

**Scope boundary:** Only `facebook_events` produces keyword-level progress. `facebook_posts` does not have a per-keyword loop, so its running line remains `running…`. Individual (non-batch) runs do not have a `discord_message_id`, so mid-run PATCHes are silently skipped for those.

**Test:** Trigger a run-all while `facebook_events` is one of the scrapers. Observe the Discord scoreboard message being edited mid-run to show `3/8 kw`, `4/8 kw`, etc., then the final ✅ line on completion.

**Verify:** `SELECT extra_counts FROM events_scraperrun WHERE scraper_key='facebook_events' ORDER BY id DESC LIMIT 1;` — while running, confirm `keyword_index` and `keyword_total` keys are present in the JSON. After completion, confirm the final scoreboard line shows counts (not `kw`).

**Done when:** Scoreboard shows live `N/M kw` for `facebook_events` during a batch run and `running…` for all other scrapers that have no keyword progress.

---

### Expected Outcome (final state)

- `apps/backend/events/notifications.py` exists with `notify_scraper_event`, `post_run_all_start`, `patch_run_all_progress`, `_build_scoreboard_embed`, `_format_bytes`, and all event types handled.
- `run_scraper_job.py` calls notify at started, and at terminal status: patches scoreboard if `discord_message_id` is set, otherwise posts individual-run message. `flush_progress` triggers a mid-run scoreboard PATCH when `keyword_index` is present and run is a batch run.
- `runner.py` calls notify at failed (path 1, subprocess launch error).
- `views.py` posts initial scoreboard and bulk-updates `discord_message_id` on all batch runs.
- `config/settings.py` exposes `DISCORD_WEBHOOK_URL`.
- Feature is a no-op when env var is unset.
- All 97 existing tests still pass.
- Discord shows correctly colored embeds for all event types.
- `run-all` produces one live scoreboard message updated in real-time, not one message per scraper.
- Bandwidth is shown for FB scrapers; `—` for all others pending future expansion.
- Migration `0028_scraperrun_discord_message_id.py` applied cleanly.
- `facebook_events` batch runs show live `N/M kw` progress in the scoreboard. `facebook_posts.run()` accepts `on_progress=None` without raising.

---

## Scope

### In

- Discord webhook notification for: started, success, failed, session-expired, run-all summary.
- Live run-all scoreboard: single Discord message edited in real-time as each scraper finishes.
- `ScraperRun.discord_message_id` field + migration `0028_scraperrun_discord_message_id.py`.
- Bandwidth display in the scoreboard for scrapers that already track it (FB scrapers only).
- `_format_bytes` helper for human-readable byte formatting.
- Backend Python only (Layer 1). Opt-in via `DISCORD_WEBHOOK_URL`.
- Fire-and-forget thread so scraper execution is not blocked.
- Color-coded embeds: blue=started/in-progress, green=success/all-done, red=failed/any-failed, yellow=session-expired.
- Error truncation: first 500 chars of `error_message` in failed embeds.
- Mid-run per-keyword progress in the scoreboard for `facebook_events` batch runs (Phase 8).
- `facebook_posts.run()` signature fix to accept `on_progress=None` (Phase 8).

### Out

- Discord bot token / slash commands / DMs.
- n8n Layer 2 (described in Integration Notes as optional; not in the implementation checklist).
- Retrying failed Discord calls (fire-and-forget, no retry loop).
- Notifications for cancel or queued status transitions.
- Notification rate-limiting (acceptable given low run volume: ~10 scrapers/week).
- Bandwidth tracking for the 13 requests-based scrapers (future task).
- Bandwidth column in individual-run `success` embeds (deferred; trivial to add later).
- Per-keyword progress for `facebook_posts` (no per-keyword loop in its `run()` method).
- Mid-run progress for individual (non-batch) runs (no `discord_message_id` to PATCH).

---

## Assumptions and Constraints

- Discord webhook URL format: `https://discord.com/api/webhooks/{id}/{token}`.
- Discord allows up to 10 embeds per message; we send exactly 1 per notification call.
- Discord message edit endpoint: `PATCH https://discord.com/api/webhooks/{webhook_id}/{webhook_token}/messages/{message_id}`. The message must have been created by the same webhook.
- `?wait=true` on the initial POST causes Discord to return the full message object as JSON; `id` field contains the message ID (snowflake, fits in `max_length=30`).
- The Django process has outbound HTTPS access on the DigitalOcean droplet.
- `urllib.request` (stdlib) is sufficient; no `requests` or `httpx` dependency required.
- The existing `_load_dotenv` in `config/settings.py` already reads `apps/backend/.env`, so adding `DISCORD_WEBHOOK_URL` to that file is all that is needed for local/prod config.
- Run volume is low enough (10 scrapers, once a week) that Discord rate limits (5 requests/second per webhook, including PATCH) will not be hit. Phase 8 adds at most one PATCH per keyword completion for `facebook_events` — still well within limits.
- `trigger_scraper_run` in `runner.py` returns the `ScraperRun` object (verify before implementing Phase 6 collection logic).
- Only FB scrapers currently populate `BandwidthLog`; all others will show `—` in the bandwidth column.
- `facebook_events.py` loop variable for keyword index is `i` (1-based) from `enumerate(work_items, 1)` at line 1386. Per-keyword save result is `result` from `save_events(self.source, cards)` at line 1559. Both are in scope at the `on_progress` call site (lines 1575–1579).

---

## Functional Requirements

- `notify_scraper_event(event_type: str, **kwargs) -> None` must be callable from any Django context (management command subprocess or web process).
- When `settings.DISCORD_WEBHOOK_URL` is empty or unset, the function must return immediately without network I/O.
- Network call must run in a daemon thread; the calling thread must not wait for it.
- All exceptions inside the thread must be caught; they must not crash the calling process.
- `session_expired` detection: check if `error_message.startswith('session_expired:')` — if yes, fire `session_expired` event instead of plain `failed`.
- Duration field in success embeds: compute `(finished_at - started_at).total_seconds()` from `ScraperRun` fields passed as kwargs (do not re-query DB).
- Fields per event type:

| Event | Required kwargs | Embed color (decimal) |
|---|---|---|
| `started` | `scraper_key`, `run_id` | 3447003 (blue) |
| `success` | `scraper_key`, `run_id`, `created_count`, `updated_count`, `duration_s` | 5763719 (green) |
| `failed` | `scraper_key`, `run_id`, `error_message` (optional) | 15548997 (red) |
| `session_expired` | `scraper_key`, `run_id`, `source` (parsed from `error_message` prefix) | 16776960 (yellow) |
| `run_all_summary` | `created` (list of dicts), `skipped` (list of str) | 3447003 (blue) |

- `post_run_all_start(scraper_keys: list[str]) -> str | None` — synchronous POST with `?wait=true`; must return the Discord message ID string, or None on failure/no-webhook.
- `patch_run_all_progress(message_id: str, runs: list[ScraperRun], bandwidth_by_run: dict[int, int]) -> None` — fire-and-forget daemon thread; builds and PATCHes the scoreboard embed; all exceptions caught and logged at WARNING.
- `_format_bytes(n: int | None) -> str` — see Phase 7 for format rules.
- `_build_scoreboard_embed`: for RUNNING rows, check `run.extra_counts` for `keyword_index` and `keyword_total`; if present render `{keyword_index}/{keyword_total} kw`; otherwise render `running…` (Phase 8).

---

## Non-Functional Requirements

- Discord call must add no more than 1-2ms of latency to the caller (thread spawn cost only).
- `post_run_all_start` is synchronous (needs the message ID before proceeding) but must complete within a 5-second timeout; if it times out, return None and proceed without scoreboard.
- Module must be importable with no new third-party packages.
- All notification code must be isolated in `notifications.py`; no Discord logic in views, runner, or management commands beyond the import and single call.
- Phase 8 mid-run PATCHes are fire-and-forget (same thread pattern as existing scoreboard PATCHes); keyword completion must not be delayed by a slow Discord call.

---

## Acceptance Criteria

1. When `DISCORD_WEBHOOK_URL` is absent, running any scraper produces no errors and no Discord activity.
2. When `DISCORD_WEBHOOK_URL` is set to a test webhook, triggering a scraper run produces a blue "started" embed within 5 seconds.
3. A successful run produces a green "success" embed with correct created/updated counts and duration.
4. A run with a Python exception in `scraper.run()` produces a red "failed" embed with the first 500 chars of the traceback.
5. A run with `error_message` starting with `session_expired:` produces a yellow "session_expired" embed naming the source.
6. A run with an unknown scraper key produces a red "failed" embed.
7. A subprocess Popen failure produces a red "failed" embed and still re-raises the exception to the caller.
8. `POST /api/scrapers/run-all/` produces ONE Discord message that is edited in real-time as each scraper completes, not N separate messages.
9. The scoreboard embed's final state shows every scraper's result, created/updated counts, duration, and bandwidth (or `—`).
10. The scoreboard color transitions: blue while running, green if all succeeded, red if any failed.
11. `ScraperRun.discord_message_id` is set on all rows belonging to the batch; individual (non-batch) runs have `NULL`.
12. Migration `0028_scraperrun_discord_message_id.py` applies cleanly: `python manage.py migrate --run-syncdb` produces no errors.
13. All 97 existing Django tests pass after the change (`python manage.py test`).
14. A Discord call timeout or HTTP error does not raise in the caller and does not appear in the Django error log as an ERROR-level entry (WARNING is acceptable).
15. Bandwidth for FB scrapers shows a non-zero human-readable value; all other scrapers show `—` in the bandwidth column.
16. During a batch run of `facebook_events`, the scoreboard is edited mid-run to show `N/M kw` in the running line as each keyword completes.
17. `facebook_posts` can be invoked with `on_progress=flush_progress` without raising a `TypeError`.

---

## Implementation Checklist

### Original phases (1–5)

- [ ] **1.** Add `DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL', '')` to `apps/backend/config/settings.py` after the existing `GROQ_MODEL` lines (around line 71).
- [ ] **2.** Add `# DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN` commented placeholder to `apps/backend/.env`.
- [ ] **3.** Create `apps/backend/events/notifications.py`:
  - Private `_post_embed(payload: dict) -> None` — builds JSON, POSTs to `settings.DISCORD_WEBHOOK_URL` via `urllib.request.urlopen` with a 5-second timeout; catches all exceptions and logs at WARNING.
  - Private `_fire(payload: dict) -> None` — spawns a `threading.Thread(target=_post_embed, args=(payload,), daemon=True)` and calls `.start()`.
  - `_build_embed(title, description, color, fields=None) -> dict` — returns a Discord embed dict.
  - `notify_scraper_event(event_type: str, **kwargs) -> None` — guard clause exits if `DISCORD_WEBHOOK_URL` is falsy; dispatches to one of five internal builders; calls `_fire`.
  - Five embed builder functions (one per event type) producing the correct title, color, and fields per the table in Functional Requirements.
- [ ] **4.** Write tests for `notifications.py` in `apps/backend/events/tests.py` (or a new file `apps/backend/events/tests_notifications.py`):
  - Test: `notify_scraper_event('started', ...)` is a no-op when `DISCORD_WEBHOOK_URL` is `''` (assert `urllib.request.urlopen` is not called — use `unittest.mock.patch`).
  - Test: `notify_scraper_event('success', ...)` with a mocked URL triggers a thread that POSTs correctly structured JSON.
  - Test: `notify_scraper_event('failed', ..., error_message='session_expired:facebook')` dispatches `session_expired` embed type.
  - Test: exception inside `_post_embed` does not propagate.
- [ ] **5.** Run existing tests: `cd apps/backend && python manage.py test events` — all must pass before proceeding.
- [ ] **6.** In `apps/backend/events/management/commands/run_scraper_job.py`:
  - Add import: `from events.notifications import notify_scraper_event` at the top.
  - After `run.refresh_from_db()` (line after the QUEUED→RUNNING conditional update), add: `notify_scraper_event('started', scraper_key=run.scraper_key, run_id=run.id)`.
  - In the unknown-key branch (after `run.save(...)` near line 147), add: `notify_scraper_event('failed', scraper_key=run.scraper_key, run_id=run.id, error_message=run.error_message)`.
  - In the `except Exception` block (after `run.save(...)` near line 208), add session-expired vs. failed dispatch.
  - After `run.save(...)` for SUCCESS, add the success notification call.
- [ ] **7.** In `apps/backend/events/runner.py`:
  - Add import: `from .notifications import notify_scraper_event`.
  - In the `except Exception` block inside `trigger_scraper_run` (after `run.save(...)`, before `raise`), add: `notify_scraper_event('failed', scraper_key=key, run_id=run.id)`.
- [ ] **8.** In `apps/backend/events/views.py` (Phase 5 static summary — will be replaced in step 15):
  - Add import: `from .notifications import notify_scraper_event` near the top of the file (after existing local imports).
  - In `api_scraper_run_all`, after the `for key in SCRAPERS` loop, add: `notify_scraper_event('run_all_summary', created=created, skipped=skipped)`.
- [ ] **9.** Set `DISCORD_WEBHOOK_URL` to a real private test-channel webhook in local `.env`. Trigger a scraper run via the SvelteKit UI. Confirm started + success embeds appear in the test channel with correct colors and fields.
- [ ] **10.** Trigger a run with a bad key (e.g., POST to `/api/scrapers/bad_key/run/`) and confirm the red failed embed appears.
- [ ] **11.** Run the full test suite: `cd apps/backend && python manage.py test` — all 97+ tests must pass.

### Phase 6 — Live run-all scoreboard

- [ ] **12.** Add `discord_message_id = models.CharField(max_length=30, null=True, blank=True, db_index=True)` to the `ScraperRun` model in `apps/backend/events/models.py`.
- [ ] **13.** Create migration `apps/backend/events/migrations/0028_scraperrun_discord_message_id.py` using `python manage.py makemigrations events --name scraperrun_discord_message_id`. Confirm the generated file is named `0028_...` and references `0027_add_event_crm_pushed_at` as its dependency.
- [ ] **14.** Apply migration: `python manage.py migrate`. Confirm `events_scraperrun` now has a `discord_message_id` column.
- [ ] **15.** Add the following to `apps/backend/events/notifications.py`:
  - `_format_bytes(n: int | None) -> str` — see Phase 7 format rules. Add now since it is used in `_build_scoreboard_embed`.
  - `_build_scoreboard_embed(runs: list, bandwidth_by_run: dict) -> dict` — constructs the scoreboard embed dict with grid rows and footer totals. Color logic: all terminal = green if none FAILED, red if any FAILED, blue if any still QUEUED/RUNNING.
  - `post_run_all_start(scraper_keys: list[str]) -> str | None` — builds an initial "all queued" embed (all rows show ⏳ queued), POSTs synchronously to `{DISCORD_WEBHOOK_URL}?wait=true` with 5-second timeout, parses JSON response for `id`, returns it. Returns `None` on any error or if `DISCORD_WEBHOOK_URL` is unset.
  - `patch_run_all_progress(message_id: str, runs: list, bandwidth_by_run: dict[int, int]) -> None` — rebuilds scoreboard embed via `_build_scoreboard_embed`, PATCHes the Discord message via `PATCH .../messages/{message_id}`, runs in a daemon thread, all exceptions caught.
- [ ] **16.** Verify `trigger_scraper_run` in `runner.py` returns the `ScraperRun` instance (read the function). If it currently returns nothing, update it to `return run` at the end (before the `raise` on error path).
- [ ] **17.** Modify `api_scraper_run_all` in `apps/backend/events/views.py`:
  - Collect `ScraperRun` objects: `run_obj = trigger_scraper_run(key)` and append to `runs_created = []`. Handle `None` returns (ALREADY_RUNNING case — skip).
  - After the loop: `run_ids = [r.id for r in runs_created]`.
  - Call `message_id = post_run_all_start(list(SCRAPERS.keys()))`.
  - If `message_id` is not None and `run_ids` is not empty: `ScraperRun.objects.filter(id__in=run_ids).update(discord_message_id=message_id)`.
  - Remove the old `notify_scraper_event('run_all_summary', ...)` call added in step 8.
- [ ] **18.** Modify `apps/backend/events/management/commands/run_scraper_job.py`:
  - Add import: `from events.notifications import patch_run_all_progress` alongside the existing notify import.
  - Add import: `from events.models import BandwidthLog` if not already present; add `from django.db.models import Sum`.
  - At each terminal-status save point (success / failed / session_expired): check `run.discord_message_id`. If set: query all sibling runs and build `bandwidth_by_run`, call `patch_run_all_progress`. If not set: call `notify_scraper_event(...)` as before (individual-run path).
- [ ] **19.** Trigger a full run-all via `/api/scrapers/run-all/`. Verify in Discord: one message appears with all scrapers ⏳ queued; message is edited as each scraper completes; final state shows correct status for all scrapers.
- [ ] **20.** Verify in DB: `SELECT id, scraper_key, discord_message_id FROM events_scraperrun ORDER BY id DESC LIMIT 10;` — all batch rows share the same `discord_message_id`; any non-batch rows have `NULL`.

### Phase 7 — Data usage display

- [ ] **21.** Confirm `_format_bytes` is already added in step 15. If not added separately, add it now.
- [ ] **22.** Confirm `_build_scoreboard_embed` uses `bandwidth_by_run[run.id]` for each grid row (or 0/None if missing). The bandwidth column uses `_format_bytes(bandwidth_by_run.get(run.id))`.
- [ ] **23.** Confirm the scoreboard footer computes `total_bw = sum(bandwidth_by_run.values())` and displays `Bandwidth: {_format_bytes(total_bw) if total_bw else '—'}`.
- [ ] **24.** Trigger a run-all that includes at least one FB scraper. Confirm the bandwidth column shows a non-zero value (e.g., `2.1 MB`) for that scraper and `—` for all others.
- [ ] **25.** Query `SELECT * FROM events_bandwidthlog ORDER BY id DESC LIMIT 5;` — confirm rows exist for the FB scraper run(s) and that the value matches the embed display.
- [ ] **26.** Run the full test suite again: `cd apps/backend && python manage.py test` — all tests must pass.
- [ ] **27.** Run `node .agents/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs process/general-plans/active/discord-notifications_PLAN_15-07-26.md` and fix any blocking failures.
- [ ] **28.** Set up the production Discord channel and webhook (operator task — see Discord Channel Setup in Integration Notes). Add `DISCORD_WEBHOOK_URL` to the production `.env` on the DigitalOcean droplet.

### Phase 8 — Mid-run per-keyword progress

- [ ] **29.** In `apps/backend/events/scrapers/facebook_posts.py` line 1023: add `on_progress=None` as the last parameter of `run(self, query_id=..., max_events=..., locations=..., query_ids=..., on_progress=None)`. No call to `on_progress` inside the method body.
- [ ] **30.** In `apps/backend/events/scrapers/facebook_events.py` lines 1575–1579: change the `on_progress` call payload from `{"total_bytes": self._bytes_transferred}` to include `keyword_index`, `keyword_total`, `keyword_created`, and `keyword_updated`. Use `i` (loop counter, 1-based, from `enumerate(work_items, 1)` at line 1386), `len(work_items)`, `result["created"]`, and `result["updated"]` where `result` is the return value of `save_events(self.source, cards)` at line 1559.
- [ ] **31.** In `apps/backend/events/management/commands/run_scraper_job.py`, inside the `flush_progress` closure (around line 203): after the existing `run.extra_counts = merged` line and before the outer `except Exception`, add: `if "keyword_index" in data and run.discord_message_id: self._patch_batch_scoreboard(run)`. Confirm `self` is accessible in the closure scope (it is — `flush_progress` is defined inside `handle()` which is a method on `self`).
- [ ] **32.** In `apps/backend/events/notifications.py`, in `_build_scoreboard_embed`, update the `elif status == "running":` branch: read `ec = run.extra_counts or {}`, extract `ki = ec.get("keyword_index")` and `kt = ec.get("keyword_total")`, render `f"{ki}/{kt} kw"` if both are not None, else `"running…"`.
- [ ] **33.** Write unit tests in `apps/backend/events/tests_notifications.py` (or `tests.py`):
  - Test: `_build_scoreboard_embed` renders `3/8 kw` in the running line when `run.extra_counts = {"keyword_index": 3, "keyword_total": 8}`.
  - Test: `_build_scoreboard_embed` renders `running…` when `extra_counts` is empty or missing `keyword_index`.
- [ ] **34.** Run full test suite: `cd apps/backend && python manage.py test` — all tests must pass.
- [ ] **35.** Trigger a run-all that includes `facebook_events`. Observe the Discord scoreboard being edited mid-run: the `facebook_events` line should change from `⏳ queued` → `🔄 facebook_events    1/N kw` → `🔄 facebook_events    2/N kw` → … → `✅ facebook_events    +X  upd Y`. Confirm `facebook_posts` runs without TypeError.

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Discord webhook throttled (429) | Low (10 runs/week) | Fire-and-forget; 429 is caught and logged at WARNING; no retry |
| Discord outage during a run | Low | Caught silently; scraper run completes normally |
| `started_at` is None on success path (race/cancel) | Low | Guard with `if run.started_at else 0` in duration calc |
| Thread leaks if process exits before thread finishes | Negligible | `daemon=True` ensures thread dies with the process; Discord has 5s timeout |
| Sending embeds to wrong channel (prod vs. test URL) | Medium | Keep webhook URLs distinct; use placeholder comment in `.env` |
| `post_run_all_start` times out — no scoreboard | Low | Returns None; bulk-update is skipped; scrapers run normally without scoreboard |
| Discord PATCH rejected (message deleted or expired) | Low | Caught in thread, logged at WARNING; does not block scraper completion |
| `trigger_scraper_run` does not return run object | Medium | Verify in step 16 before implementing step 17; update if needed |
| Race condition: first scraper finishes before bulk-update sets `discord_message_id` | Low | `post_run_all_start` is synchronous and called before subprocesses have time to complete (subprocesses have startup overhead). If a race occurs, that run's PATCH call will silently skip (discord_message_id is None at read time in the subprocess); the next scraper's PATCH will include all completed rows. Acceptable for v1. |
| Discord message snowflake ID exceeds `max_length=30` | Very Low | Discord snowflakes are 64-bit ints (~19 digits); 30 chars is safe |
| Phase 8: `flush_progress` fires a PATCH on every keyword — could hit Discord rate limits for very large keyword sets | Low | `facebook_events` typically has ~8–15 keywords per run; at most 15 extra PATCHes per run-all. Still well within 5 req/s limit. |
| Phase 8: `self` not in scope inside `flush_progress` closure | Very Low | Verified: `flush_progress` is defined inside `Command.handle()`; `self` (the `Command` instance) is captured in the closure scope. |
| Phase 8: `facebook_posts.run()` TypeError when called with `on_progress` kwarg | Confirmed pre-existing | Fixed by step 29 (adding `on_progress=None` to signature). |

---

## Integration Notes

### Discord Channel Setup (operator task)

1. In Discord: Server Settings > Integrations > Webhooks > New Webhook.
2. Choose the `#scraper-ops` channel (create it if needed).
3. Copy the webhook URL.
4. Add `DISCORD_WEBHOOK_URL=<url>` to `apps/backend/.env` on the DigitalOcean droplet.
5. Restart the Django process (`systemctl restart gunicorn` or equivalent).

### Testing Without Spamming Production

- Create a separate private Discord server (or a `#scraper-ops-test` channel) and generate a second webhook URL for local `.env`.
- Never commit a real webhook URL to `.env` or any tracked file; the `.env` is already git-ignored.

### Optional Layer 2 — n8n Fallback (not in checklist, reference only)

If belt-and-suspenders coverage is desired for the weekly automated run:

1. After the `POST /api/scrapers/run-all/` step in n8n, add a `Wait` node (~5 min).
2. Add an `HTTP Request` node to `GET /api/scrapers/runs/?limit=20`.
3. Parse the response for failed runs.
4. Add a Discord node (n8n built-in) or a second `HTTP Request` to the same webhook URL.

This is optional; Layer 1 (backend notifier) already fires on every run regardless of trigger source.

### Env Var Loading

`config/settings.py` uses a custom `_load_dotenv` that reads `apps/backend/.env` into `os.environ` (no override of existing env vars). The new `DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL', '')` follows the exact same pattern as `GROQ_API_KEY` and `PLACES_API_KEY`.

### Migration Sequence

Current highest migration: `0027_add_event_crm_pushed_at.py`. New migration: `0028_scraperrun_discord_message_id.py`. The `makemigrations` command will auto-detect the dependency. If merge migrations are needed (parallel branches), resolve before applying.

### Future: Bandwidth Tracking for Requests-Based Scrapers

13 scrapers currently do not return `total_bytes` and therefore do not populate `BandwidthLog`. To expand bandwidth tracking:
1. Instrument each scraper to measure response sizes (e.g., via a session wrapper that sums `len(response.content)` per request).
2. Return `total_bytes` from `scraper.run()`.
3. `runner.py` already calls `log_bandwidth()` when `total_bytes` is present — no changes needed there.
This is a separate task; note it in backlog when Phase 7 is complete.

### Future: Per-Keyword Progress for `facebook_posts`

`facebook_posts.run()` does not currently have a per-keyword loop that maps directly to progress increments. If per-keyword progress is added later, follow the same pattern as Phase 8: enrich the `on_progress` payload and update `_build_scoreboard_embed` to read the new keys.

---

## Touchpoints

- `apps/backend/events/notifications.py` — new file (sole Discord logic owner); gains `post_run_all_start`, `patch_run_all_progress`, `_build_scoreboard_embed`, `_format_bytes` in Phase 6/7; `_build_scoreboard_embed` updated for keyword progress display in Phase 8
- `apps/backend/events/management/commands/run_scraper_job.py` — 4 call sites added (Phase 3); updated in Phase 6 to branch on `discord_message_id`; `flush_progress` gains mid-run PATCH trigger in Phase 8
- `apps/backend/events/runner.py` — 1 call site added (subprocess failure path); may need `return run` update (Phase 6, step 16)
- `apps/backend/events/views.py` — Phase 5 adds summary call; Phase 6 replaces it with scoreboard flow
- `apps/backend/config/settings.py` — 1 new `DISCORD_WEBHOOK_URL` setting
- `apps/backend/.env` — 1 commented placeholder line
- `apps/backend/events/models.py` — `ScraperRun` gains `discord_message_id` field (Phase 6)
- `apps/backend/events/migrations/0028_scraperrun_discord_message_id.py` — new migration (Phase 6)
- `apps/backend/events/scrapers/facebook_events.py` — `on_progress` payload enriched with keyword progress fields at line 1577 (Phase 8)
- `apps/backend/events/scrapers/facebook_posts.py` — `run()` signature at line 1023 gains `on_progress=None` parameter (Phase 8)

---

## Public Contracts

- `notify_scraper_event(event_type: str, **kwargs) -> None` — callable from any module in `apps/backend/events/`. Must remain a no-op when `DISCORD_WEBHOOK_URL` is falsy. Must never raise.
- `post_run_all_start(scraper_keys: list[str]) -> str | None` — synchronous; returns Discord message ID or None. Must never raise.
- `patch_run_all_progress(message_id: str, runs: list, bandwidth_by_run: dict[int, int]) -> None` — fire-and-forget; must never raise in the caller.
- `DISCORD_WEBHOOK_URL` env var — opt-in, no default. Documented in `.env` placeholder comment.
- `ScraperRun.discord_message_id` — nullable CharField; None for individual runs, populated for batch runs.
- `facebook_posts.FacebookPostsScraper.run()` — now accepts `on_progress=None` kwarg without raising. No behavior change otherwise.
- `on_progress` payload contract (for callers of `facebook_events` only): dict with keys `total_bytes`, `keyword_index` (int, 1-based), `keyword_total` (int), `keyword_created` (int), `keyword_updated` (int). `flush_progress` in `run_scraper_job.py` is the sole consumer.
- No new HTTP endpoints, no new DB tables beyond the single field addition.

---

## Blast Radius

- **Changed behavior:** None for individual runs. `run-all` now makes an additional synchronous Discord POST before returning (≤5s timeout, failure returns None and continues). Patch calls are fire-and-forget.
- **Existing tests:** All 97 tests must still pass. New notifications.py functions are tested with mocks. Migration is additive (nullable column).
- **Schema change:** One nullable column added to `events_scraperrun` — fully backwards-compatible. Existing rows get `NULL` for `discord_message_id`.
- **Runtime risk:** A buggy `notifications.py` can at worst emit a WARNING log entry or add ≤5s delay to `run-all` (only if `post_run_all_start` times out). Cannot block or crash a scraper run.
- **Affected files:**
  - `run_scraper_job.py` — added imports and up to 4 call sites; logic flow unchanged for individual runs; branches on `discord_message_id` for batch runs; `flush_progress` gains mid-run PATCH when keyword progress is present (Phase 8)
  - `runner.py` — added import and 1 call site before existing `raise`; raise is preserved; may gain `return run`
  - `views.py` — Phase 5 adds 1 call site; Phase 6 replaces it with 3-step scoreboard flow
  - `settings.py` — 1 new config line; no behavior change if var is absent
  - `models.py` — 1 new nullable field; no behavior change for existing code paths
  - `migrations/0028_...` — new file; apply before any Phase 6 code is deployed
  - `facebook_events.py` — `on_progress` payload extended; no behavior change to scraping or save logic (Phase 8)
  - `facebook_posts.py` — signature change only; existing callers passing `on_progress=flush_progress` now work instead of raising `TypeError` (Phase 8)

---

## Verification Evidence

Before claiming this feature VERIFIED, the following evidence must exist:

1. `python manage.py test` output shows all tests passing (97+ green).
2. Screenshot or copy of a Discord embed for each of the five individual event types in the test channel.
3. Screenshot of the run-all scoreboard showing the initial queued state and the final edited state with all scrapers resolved.
4. Confirmation that a scraper run completes normally with `DISCORD_WEBHOOK_URL` unset (no error in logs).
5. Confirmation that a Discord 5xx / timeout does not produce an ERROR in Django logs — only WARNING.
6. DB query showing `discord_message_id` populated for batch runs and NULL for individual runs.
7. DB query (`SELECT * FROM events_bandwidthlog ORDER BY id DESC LIMIT 5;`) showing bandwidth rows for at least one FB scraper run.
8. `validate-plan-artifact.mjs` run exits with no blocking failures.
9. Screenshot or log showing the `facebook_events` scoreboard line cycling through `N/M kw` values during a batch run (Phase 8).
10. DB query (`SELECT extra_counts FROM events_scraperrun WHERE scraper_key='facebook_events' ORDER BY id DESC LIMIT 1;`) showing `keyword_index` and `keyword_total` in the JSON while the run was active (Phase 8).

---

## Resume and Execution Handoff

If this session is interrupted, resume by:

1. Reading this file.
2. Running `python manage.py test events` to see current test state.
3. Checking `apps/backend/events/notifications.py` existence — if absent, start from checklist item 3.
4. Checking the four call sites in `run_scraper_job.py` (search for `notify_scraper_event`) — if absent, start from item 6.
5. Checking `runner.py` for `notify_scraper_event` — if absent, start from item 7.
6. Checking `views.py` for `notify_scraper_event` — if absent, start from item 8.
7. For Phase 6: check `apps/backend/events/models.py` for `discord_message_id` field — if absent, start from item 12.
8. For Phase 6: check `apps/backend/events/migrations/0028_scraperrun_discord_message_id.py` — if absent, run `makemigrations` (item 13).
9. For Phase 6: check `notifications.py` for `post_run_all_start` — if absent, start from item 15.
10. For Phase 8: check `facebook_posts.py` line 1023 for `on_progress=None` parameter — if absent, start from item 29.
11. For Phase 8: check `facebook_events.py` lines 1575–1579 for enriched `on_progress` payload — if absent, start from item 30.
12. For Phase 8: check `flush_progress` in `run_scraper_job.py` for the `keyword_index` PATCH trigger — if absent, start from item 31.
13. For Phase 8: check `_build_scoreboard_embed` in `notifications.py` for `keyword_index`/`keyword_total` rendering — if absent, start from item 32.
14. The Discord webhook URL for testing lives in `apps/backend/.env` (not committed).

Key file paths for the executor:
- `/home/hd/projects/veent/sir_yuri/veent-event-scraper/apps/backend/events/notifications.py` (create; extend in Phase 6; update `_build_scoreboard_embed` in Phase 8)
- `/home/hd/projects/veent/sir_yuri/veent-event-scraper/apps/backend/events/management/commands/run_scraper_job.py` (edit — 4 sites Phase 3; branch logic Phase 6; `flush_progress` mid-run PATCH Phase 8)
- `/home/hd/projects/veent/sir_yuri/veent-event-scraper/apps/backend/events/runner.py` (edit — 1 site, before existing `raise`; possible `return run` addition)
- `/home/hd/projects/veent/sir_yuri/veent-event-scraper/apps/backend/events/views.py` (edit — Phase 5 summary; Phase 6 scoreboard flow)
- `/home/hd/projects/veent/sir_yuri/veent-event-scraper/apps/backend/config/settings.py` (edit — 1 new line after line ~71)
- `/home/hd/projects/veent/sir_yuri/veent-event-scraper/apps/backend/events/models.py` (edit — add `discord_message_id` field)
- `/home/hd/projects/veent/sir_yuri/veent-event-scraper/apps/backend/events/migrations/0028_scraperrun_discord_message_id.py` (generate via makemigrations)
- `/home/hd/projects/veent/sir_yuri/veent-event-scraper/apps/backend/events/scrapers/facebook_events.py` (edit — enrich `on_progress` payload at line 1577, Phase 8)
- `/home/hd/projects/veent/sir_yuri/veent-event-scraper/apps/backend/events/scrapers/facebook_posts.py` (edit — add `on_progress=None` to `run()` signature at line 1023, Phase 8)

---

## Cursor + RIPER-5 Guidance

- **Cursor Plan mode:** Import the Implementation Checklist above. Execute items 1-2, then 3-4, then 5, then 6-8 as logical groups. After item 5 (tests), stop and confirm all pass before continuing. After item 11 (full test suite), stop and confirm before starting Phase 6 (items 12-20). After item 20, stop and verify in DB before starting Phase 7 (items 21-27). After item 27 (validate-plan) and item 28 (prod deploy), proceed to Phase 8 (items 29-35).
- **RIPER-5:** This plan is the output of PLAN mode. Say `ENTER EXECUTE MODE` to begin implementation. The executor must not deviate from the checklist ordering without noting the deviation.
- **After each phase, STOP and verify before proceeding.**
- **If scope expands** (e.g., retry logic, DB logging of Discord status, rate limiting, bandwidth tracking for 13 remaining scrapers, per-keyword progress for `facebook_posts`), pause and assess whether to extend this plan or create a new one.
