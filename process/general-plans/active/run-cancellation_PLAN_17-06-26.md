# Run Cancellation Plan
## Subprocess-Based Scraper Kill

**Type:** COMPLEX
**Created:** 2026-06-17
**Branch:** feat/run-cancellers (suggested; implementation may use current branch)
**Status:** READY FOR EXECUTE

---

## Overview

Replace the thread-based scraper runner with a subprocess-per-run model so the OS can terminate
a running scraper — including its child processes (e.g. Playwright's chromium) — when an admin
requests cancellation from the Scraper Center UI.

The current design uses `threading.Thread` with no kill hook. Threads cannot be forcibly
stopped from outside; the only safe kill unit is a process. Switching to
`subprocess.Popen(..., start_new_session=True)` gives every run its own process group, which
can be terminated with `os.killpg`.

---

## Goals

1. Admin can cancel an actively-running scraper run from the Scraper Center UI.
2. Cancel ACTUALLY kills the work — including Playwright's browser child process.
3. Cancelled status is durable: the DB row transitions to `cancelled`, not left as `running`.
4. Existing 64 tests continue to pass after the change.
5. No scraper files (`base.py`, 8 scrapers) are modified.

---

## Out of Scope

- Windows process group semantics (`CREATE_NEW_PROCESS_GROUP`) — dev/prod is Linux (POSIX).
- Celery / task queue introduction.
- Auth gate on cancel endpoint (matches existing trigger endpoint posture — public, `@csrf_exempt`).
- Server crash recovery / stale-run reconciliation beyond a diagnostic note.

---

## Verified Current State (confirmed against files)

| File | Confirmed |
|---|---|
| `apps/backend/events/runner.py` — `trigger_scraper_run` + `_run_scraper` (thread-based) | yes |
| `apps/backend/events/models.py` — `ScraperRun.Status` has 4 values: queued/running/success/failed; no `pid` field | yes |
| `apps/backend/events/views.py` — `_serialize_run`, trigger/run-all/list/active/detail endpoints; no cancel endpoint | yes |
| `apps/backend/events/urls.py` — scraper routes, ordering: `<key>/run/` then `run-all/` then `runs/active/` then `runs/<id>/` then `runs/` then `scrapers/` | yes |
| `apps/backend/events/tests.py` — 64 tests; `RunnerTests` uses `TransactionTestCase` + mock SCRAPERS | yes |
| `apps/backend/events/management/commands/scrape.py` — existing blocking CLI runner | yes |
| Latest migration: `0010_scraperrun` | yes |
| `apps/frontend/src/lib/types.ts` — `ScraperRunStatus = 'queued' | 'running' | 'success' | 'failed'` | yes |
| `apps/frontend/src/lib/api.ts` — `post<T>()` helper; no `cancelRun` | yes |
| `apps/frontend/src/routes/scrapers/+page.svelte` — Svelte 5 runes; `runningMap`, `triggering`, polling every 2.5s | yes |
| `apps/frontend/src/lib/components/Badge.svelte` — `styles` dict; no `cancelled` entry | yes |

---

## Data Flow

```
UI click "Cancel"
  → POST /api/scrapers/runs/<id>/cancel/
      → cancel_run(run_id) in runner.py
          → loads ScraperRun row
          → if not is_active → return signal → 409
          → reads run.pid
          → os.killpg(os.getpgid(pid), SIGTERM)
          → catches ProcessLookupError (process already gone)
          → re-fetches row to check terminal status not already written
          → if still active → set status=CANCELLED, finished_at=now(), save()
          → return serialized run → 200
  ← polling tick sees status=cancelled → stops polling, refreshes recentRuns
```

```
UI click "Run"
  → POST /api/scrapers/<key>/run/
      → trigger_scraper_run(key) in runner.py
          → concurrency guard (queued/running check)
          → ScraperRun.objects.create(status=QUEUED)
          → subprocess.Popen(
                [sys.executable, BASE_DIR/"manage.py", "run_scraper_job", "--run-id", str(run.id)],
                start_new_session=True,   # own process group = setsid
                cwd=BASE_DIR,
             )
          → run.pid = proc.pid; run.save(update_fields=["pid", "updated_at"])
          → return (run, False)
  subprocess: run_scraper_job --run-id <id>
      → ScraperRun row loaded by id
      → key read from row.scraper_key
      → run.status = RUNNING, run.started_at = now(), save()
      → SCRAPERS[key]().run() → result dict
      → run.status = SUCCESS, run.finished_at = now(), counts set, save()
      → OR on exception: status = FAILED, error_message = traceback, save()
```

---

## Implementation Checklist

### Phase 1 — Model + Migration

- [ ] **1.** In `apps/backend/events/models.py`, add `CANCELLED = "cancelled", "Cancelled"` to
  `ScraperRun.Status` TextChoices (after `FAILED`).
  - `is_active` property: no change needed — it already tests membership in `(QUEUED, RUNNING)`;
    `CANCELLED` is excluded automatically.
  - `__str__` method: no change needed (uses `self.status` which is now a 5-value choice).

- [ ] **2.** In `apps/backend/events/models.py`, add `pid` field to `ScraperRun` after
  `error_message`:
  ```
  pid = models.PositiveIntegerField(null=True, blank=True,
      help_text="OS PID of the worker subprocess; null for queued/pre-subprocess rows.")
  ```

- [ ] **3.** Generate migration (do NOT hand-write):
  ```bash
  cd apps/backend && ./venv/bin/python manage.py makemigrations events --name run_cancellation
  ```
  This produces `0011_scraperrun_run_cancellation.py`. Verify it covers both the new `Status`
  choice and the new `pid` field. The migration file itself needs no manual edits.

- [ ] **4.** Apply migration to Neon Postgres:
  ```bash
  cd apps/backend && ./venv/bin/python manage.py migrate
  ```

### Phase 2 — Management Command `run_scraper_job`

- [ ] **5.** Create `apps/backend/events/management/commands/run_scraper_job.py`.

  The command owns one run's full lifecycle. Exact specification:

  **Arguments:**
  - `--run-id` (required, int): the `ScraperRun.pk` to execute.

  **`handle()` logic (ordered, must be exact):**
  1. Load `run = ScraperRun.objects.get(id=options["run_id"])`. If `DoesNotExist`, write to
     `stderr` and exit cleanly (return, no exception propagation — the row may have been
     deleted in a race).
  2. Resolve `key = run.scraper_key`.
  3. Verify `key in SCRAPERS`. If not, mark `FAILED` with `error_message = f"Unknown key: {key}"`,
     `finished_at = timezone.now()`, save, and return.
  4. Set `run.status = ScraperRun.Status.RUNNING`, `run.started_at = timezone.now()`, save
     with `update_fields=["status", "started_at", "updated_at"]`.
     - NOTE: the parent `trigger_scraper_run` already stores `proc.pid` on the row (step 7
       below). The command does NOT need to write the pid — it is already there when this
       command starts running.
  5. Extract result dict:
     ```python
     try:
         result = SCRAPERS[key]().run()
     except Exception:
         tb = traceback.format_exc()
         run.status = ScraperRun.Status.FAILED
         run.finished_at = timezone.now()
         run.error_message = tb
         run.save(update_fields=["status", "finished_at", "error_message", "updated_at"])
         return
     ```
  6. Map result dict → counts using the shared helper `_map_result` (defined in step 6):
     ```python
     created, updated, extra_counts = _map_result(result)
     run.status = ScraperRun.Status.SUCCESS
     run.finished_at = timezone.now()
     run.created_count = created
     run.updated_count = updated
     run.extra_counts = extra_counts
     run.save(update_fields=[
         "status", "finished_at", "created_count",
         "updated_count", "extra_counts", "updated_at",
     ])
     ```
  7. No `connection.close()` needed — the management command is a full Django process; its
     connection lifecycle is managed by Django on process exit.

- [ ] **6.** Extract `_map_result(result_dict) -> tuple[int, int, dict]` as a module-level
  helper in `apps/backend/events/runner.py`. This avoids duplication between `_run_scraper`
  (which is removed in step 8) and the new management command.

  Exact implementation:
  ```python
  def _map_result(result: dict) -> tuple[int, int, dict]:
      """Extract (created, updated, extra_counts) from a scraper run() result dict."""
      created = result.get("created", 0)
      updated = result.get("updated", 0)
      extra_counts = {
          k: v
          for k, v in result.items()
          if k not in ("source", "created", "updated")
      }
      return created, updated, extra_counts
  ```

  Import `_map_result` in `run_scraper_job.py` as:
  ```python
  from events.runner import _map_result
  ```

### Phase 3 — Runner Refactor

- [ ] **7.** Rewrite `apps/backend/events/runner.py` completely. The new file must:

  **Imports to add / change:**
  - Remove: `import threading`
  - Remove: `from django.db import connection`
  - Add: `import os`, `import signal`, `import subprocess`, `import sys`
  - Keep: `import traceback`, `from django.utils import timezone`, `from .models import ScraperRun`
  - Keep: `from .scrapers import SCRAPERS` (still used by `cancel_run` for the concurrency guard
    import; also used in `_map_result`)

  **`_map_result` helper:** add per step 6.

  **`trigger_scraper_run(key, triggered_by=None) -> tuple[ScraperRun | None, bool]`:**
  - Keep concurrency guard exactly as-is (query `status__in=[QUEUED, RUNNING]`).
  - `run = ScraperRun.objects.create(scraper_key=key, triggered_by=triggered_by)` — status
    defaults to QUEUED.
  - Determine `manage_py` path:
    ```python
    import django
    from django.conf import settings
    manage_py = settings.BASE_DIR / "manage.py"
    ```
    `BASE_DIR` is defined in `apps/backend/config/settings.py` as `Path(__file__).resolve().parent.parent`
    which resolves to `apps/backend/` — this is the directory containing `manage.py`. Verify
    this path resolves correctly by asserting `manage_py.exists()` during development.
  - Launch subprocess:
    ```python
    proc = subprocess.Popen(
        [sys.executable, str(manage_py), "run_scraper_job", "--run-id", str(run.id)],
        start_new_session=True,
        cwd=str(settings.BASE_DIR),
    )
    ```
    `start_new_session=True` is the POSIX equivalent of `setsid()` — it creates a new session
    and process group for the child. This is required for `killpg` to kill the whole tree
    (including Playwright's spawned chromium).
  - Store pid immediately:
    ```python
    run.pid = proc.pid
    run.save(update_fields=["pid", "updated_at"])
    ```
  - Return `(run, False)`.
  - Do NOT call `proc.wait()` — the subprocess runs independently; the Django web process
    does not block.

  **`cancel_run(run_id: int) -> tuple[ScraperRun | None, str]`:**
  Return values: `(run, "ok")`, `(None, "not_found")`, `(run, "not_active")`.

  Exact logic:
  ```
  1. run = ScraperRun.objects.select_for_update().get(id=run_id)
     - Catch DoesNotExist → return (None, "not_found")
  2. Re-check is_active inside the SELECT FOR UPDATE to avoid the race where the
     subprocess writes SUCCESS in the same instant.
     if not run.is_active:
         return (run, "not_active")
  3. pid = run.pid
  4. if pid is not None:
         try:
             pgid = os.getpgid(pid)
             os.killpg(pgid, signal.SIGTERM)
         except ProcessLookupError:
             pass  # subprocess already exited
         except PermissionError:
             pass  # shouldn't happen (same uid), but don't crash
  5. Re-fetch run inside the same DB transaction to check if subprocess raced us
     to a terminal state:
     run.refresh_from_db()
     if not run.is_active:
         # Subprocess beat us — respect its terminal status.
         return (run, "ok")
  6. run.status = ScraperRun.Status.CANCELLED
     run.finished_at = timezone.now()
     run.save(update_fields=["status", "finished_at", "updated_at"])
  7. return (run, "ok")
  ```

  Wrap steps 1-7 in `with transaction.atomic():` so the SELECT FOR UPDATE and the final
  save are atomic. Import `from django.db import transaction`.

  **Remove `_run_scraper`:** it is replaced by the management command. Remove the old
  `import threading` and `from django.db import connection` imports.

  **Module-level docstring:** update to describe subprocess model and process-group kill.

- [ ] **8.** Update `apps/backend/events/runner.py` imports in other files: none needed —
  `views.py` imports `from .runner import trigger_scraper_run`; we are adding `cancel_run`
  which will be imported in step 9.

### Phase 4 — Cancel Endpoint + URL

- [ ] **9.** In `apps/backend/events/views.py`:

  **Add import:** `from .runner import trigger_scraper_run, cancel_run`
  (replace the existing single-function import).

  **Add `api_scraper_run_cancel` view function** after `api_scraper_run_detail`:
  ```python
  @csrf_exempt
  @require_POST
  def api_scraper_run_cancel(request, run_id):
      # SECURITY NOTE: same posture as api_scraper_trigger — unauthenticated
      # intentionally (no Django session from SvelteKit). Re-evaluate when real
      # auth is added.
      run, signal = cancel_run(run_id)
      if signal == "not_found":
          return JsonResponse({"error": "Run not found"}, status=404)
      if signal == "not_active":
          return JsonResponse({"error": "Run is not active", "run": _serialize_run(run)}, status=409)
      return JsonResponse(_serialize_run(run), status=200)
  ```

  **Update `_serialize_run`:** no structural change needed — it serializes `run.status`
  as a string, and `cancelled` is already a valid string value after the model change.
  The `pid` field does NOT need to be included in the serialized shape (it is internal
  infrastructure, not useful to the frontend).

- [ ] **10.** In `apps/backend/events/urls.py`, add the cancel URL. Insert it **between**
  `runs/active/` and `runs/<id>/` (more-specific path must precede the int pattern):

  Current order:
  ```
  runs/active/
  runs/<int:run_id>/
  runs/
  ```

  New order:
  ```
  runs/active/
  runs/<int:run_id>/cancel/   ← INSERT HERE
  runs/<int:run_id>/
  runs/
  ```

  Add line:
  ```python
  path("api/scrapers/runs/<int:run_id>/cancel/", views.api_scraper_run_cancel, name="api_scraper_run_cancel"),
  ```

  URL resolution rationale: Django path() patterns are tested in order. The `cancel/` suffix
  makes `runs/<int:run_id>/cancel/` unambiguous — it cannot conflict with `runs/<int:run_id>/`
  because the trailing path segment differs. No ordering conflict exists, but inserting before
  `runs/<int:run_id>/` is cleaner and matches the "more specific first" convention.

### Phase 5 — Frontend

- [ ] **11.** In `apps/frontend/src/lib/types.ts`:
  - Change `ScraperRunStatus` union: `'queued' | 'running' | 'success' | 'failed' | 'cancelled'`
  - No `pid` field on `ScraperRun` interface — the backend does not serialize `pid`.

- [ ] **12.** In `apps/frontend/src/lib/api.ts`, add `cancelRun` method to the `api` object:
  ```typescript
  cancelRun: (id: number) => post<ScraperRun>(`/scrapers/runs/${id}/cancel/`),
  ```
  Import `ScraperRun` type (already imported via types.ts in the file via the type block at
  the top — confirm it is included or add to the import list).

  The existing `post<T>()` helper sends `X-CSRFToken` + `credentials: 'include'`; this is
  correct for the cancel endpoint. No new helper needed.

- [ ] **13.** In `apps/frontend/src/lib/components/Badge.svelte`, add `cancelled` entry to
  the `styles` record:
  ```typescript
  cancelled: 'bg-warning-bg text-warning',
  ```
  Insert after the `failed` entry. Style rationale: cancelled is a deliberate user action,
  not a failure; warning (amber) color distinguishes it visually from both success (green)
  and failure (red).

- [ ] **14.** In `apps/frontend/src/routes/scrapers/+page.svelte`, make these changes:

  **State additions** (after existing `triggering` state):
  ```typescript
  // Keys currently being cancelled (before the response lands).
  let cancelling = $state<Set<string>>(new Set());
  ```

  **Add `handleCancel` function** (after `handleRun`):
  ```typescript
  async function handleCancel(key: string, runId: number) {
      if (cancelling.has(key)) return;
      cancelling = new Set([...cancelling, key]);
      errors = new Map([...errors].filter(([k]) => k !== key));
      try {
          await api.cancelRun(runId);
          await pollActive();
      } catch (e) {
          const msg = e instanceof Error ? e.message : 'Failed to cancel run';
          errors = new Map([...errors, [key, msg]]);
      } finally {
          cancelling = new Set([...cancelling].filter((k) => k !== key));
      }
  }
  ```

  **Cancel button in scraper card** (inside the `{#if isActive}` block in the card header,
  after the spinning indicator or as a sibling to the "Run" button):

  Replace the existing Run button conditional block. The current template has:
  ```svelte
  <button
      disabled={isActive || triggering.has(s.key)}
      onclick={() => handleRun(s.key)}
      ...
  >
      {isActive ? 'Running…' : 'Run'}
  </button>
  ```

  Replace with two buttons side-by-side:
  ```svelte
  <div class="flex gap-2">
      <button
          disabled={isActive || triggering.has(s.key)}
          onclick={() => handleRun(s.key)}
          class="rounded-md border border-border px-2.5 py-1 text-xs text-text transition hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
      >
          {triggering.has(s.key) ? 'Starting…' : 'Run'}
      </button>
      {#if isActive && run}
          <button
              disabled={cancelling.has(s.key)}
              onclick={() => handleCancel(s.key, run.id)}
              class="rounded-md border border-danger/40 bg-danger-bg/40 px-2.5 py-1 text-xs text-danger transition hover:bg-danger-bg disabled:cursor-not-allowed disabled:opacity-50"
          >
              {cancelling.has(s.key) ? 'Cancelling…' : 'Cancel'}
          </button>
      {/if}
  </div>
  ```

  **`isActive` logic update:** the existing `const isActive = run?.status === 'queued' || run?.status === 'running'`
  is already correct — `cancelled` is a terminal status so it will not appear in `runningMap`
  (the active runs poll only returns queued/running rows). No change needed here.

  **`pollActive` update:** the poll fetches `/api/scrapers/runs/active/` which only returns
  queued/running rows. After cancellation, the cancelled run disappears from active, the
  polling stops, and `recentRuns` is refreshed — this is the same path as normal completion.
  No change to `pollActive` is needed.

### Phase 6 — Tests

- [ ] **15.** In `apps/backend/events/tests.py`, add the following test classes. Keep all
  existing 64 tests unchanged.

  **`ScraperRunCancelledStatusTests(TestCase)`** — model-level:
  - `test_cancelled_is_valid_status`: create a run, set `status = ScraperRun.Status.CANCELLED`,
    save, refresh, assert `status == "cancelled"`.
  - `test_is_active_false_for_cancelled`: set status to CANCELLED on an unsaved instance,
    assert `is_active` is False.
  - `test_pid_field_defaults_to_null`: create run, assert `run.pid is None`.

  **`RunnerSubprocessTests(TransactionTestCase)`** — replaces/extends `RunnerTests` for
  subprocess-specific behaviour. Use `TransactionTestCase` (not `TestCase`) because the
  runner uses `select_for_update` inside a `transaction.atomic()` which is not compatible
  with `TestCase`'s test-wrapping transaction on some Postgres setups.

  Each test in this class must mock `subprocess.Popen` to avoid spawning real processes.
  Use `mock.patch("events.runner.subprocess.Popen")` for all trigger tests.

  Tests:
  - `test_trigger_creates_run_row_subprocess`: mock `Popen()`; assert `ScraperRun.objects.count() == 1`.
  - `test_trigger_stores_pid`: mock `Popen()` with `mock_proc.pid = 12345`; call
    `trigger_scraper_run("myruntime")`; `run.refresh_from_db()`; assert `run.pid == 12345`.
  - `test_trigger_returns_run_and_false_when_clear`: mock `Popen()`; assert `(run is not None, already_active is False)`.
  - `test_trigger_returns_none_true_when_already_active`: create a RUNNING row; call `trigger_scraper_run`; assert `(None, True)` — same as existing test but now mocking `Popen`.
  - `test_cancel_run_happy_path`: create a RUNNING run with `pid=99999`; mock `os.killpg` and
    `os.getpgid` to do nothing (process group "killed" silently); call `cancel_run(run.id)`;
    assert signal `"ok"`, `run.status == "cancelled"`, `run.finished_at is not None`.
  - `test_cancel_run_not_found`: call `cancel_run(99999)`; assert signal `"not_found"`, run `None`.
  - `test_cancel_run_not_active`: create a SUCCESS run; call `cancel_run(run.id)`; assert
    signal `"not_active"`, run returned.
  - `test_cancel_run_process_already_gone`: create RUNNING run with `pid=99999`; mock `os.killpg`
    to raise `ProcessLookupError`; mock `os.getpgid` to return `99999`; call `cancel_run`; assert
    status becomes CANCELLED (process gone but row still active → still cancel it).
  - `test_cancel_run_race_subprocess_wrote_success`: create RUNNING run with `pid=99999`; mock
    `os.killpg` to do nothing, but also mock the `refresh_from_db` call to flip status to SUCCESS
    (simulating the subprocess winning the race); assert `cancel_run` returns `(run, "ok")` and
    does NOT overwrite to CANCELLED.
    Implementation note: patch `ScraperRun.refresh_from_db` to set `run.status = SUCCESS`; then
    verify the returned run's status is SUCCESS.

  **`CancelEndpointTests(TestCase)`** — HTTP-level:
  - `test_cancel_happy_path_returns_200`: mock `cancel_run` returning `(mock_run, "ok")` where
    `mock_run` has all fields needed by `_serialize_run`; POST to
    `/api/scrapers/runs/<id>/cancel/`; assert 200, body contains `"status"`.
  - `test_cancel_not_found_returns_404`: mock `cancel_run` returning `(None, "not_found")`;
    assert 404.
  - `test_cancel_not_active_returns_409`: mock `cancel_run` returning `(mock_run, "not_active")`
    where mock_run is a finished run; assert 409.
  - `test_cancel_requires_post`: GET to `/api/scrapers/runs/1/cancel/`; assert 405.
  - `test_cancel_is_public`: no auth; POST `/api/scrapers/runs/1/cancel/` with `cancel_run`
    mocked returning `(mock_run, "ok")`; assert 200.

  **`RunnerMappingTests(TestCase)`** — covers `_map_result` helper:
  - `test_map_result_basic`: `{"source": "x", "created": 3, "updated": 1}` → `(3, 1, {})`.
  - `test_map_result_extra_counts`: myruntime dict with `organizers_created/organizers_updated` →
    `extra_counts` has those keys; `source` not in extra_counts.

  **Existing `RunnerTests`:** retain all 6 tests. They test `_run_scraper` (called directly,
  not via subprocess) — this function is removed in step 7. Update these tests in step 16.

- [ ] **16.** Update `RunnerTests` in `tests.py`: `_run_scraper` no longer exists after the
  refactor. Migrate the 6 runner tests:

  - `test_trigger_creates_run_row` → now lives in `RunnerSubprocessTests` (step 15).
  - `test_trigger_returns_run_and_false_when_clear` → same.
  - `test_trigger_returns_none_true_when_already_active` → same.
  - `test_run_scraper_happy_path` → now covered by the management command's own logic; this test
    should be removed OR re-written to test the `run_scraper_job` command via
    `call_command("run_scraper_job", run_id=run.id)` with mock SCRAPERS. Rewrite as
    `test_run_scraper_job_happy_path`.
  - `test_run_scraper_failure_path` → rewrite as `test_run_scraper_job_failure_path`.
  - `test_run_scraper_myruntime_extra_counts` → rewrite as `test_run_scraper_job_extra_counts`.

  The rewritten command tests call `from django.core.management import call_command` and
  `call_command("run_scraper_job", run_id=run.id)` with `mock.patch.dict(runner.SCRAPERS, {...})`.
  These tests use `TestCase` (not `TransactionTestCase`) since the command runs synchronously
  in the test process without threading.

  Remove the old `RunnerTests` class entirely; replace with `RunnerSubprocessTests` (new
  subprocess trigger tests) + `ScraperJobCommandTests` (command execution tests).

---

## Touchpoints

| File | Change |
|---|---|
| `apps/backend/events/models.py` | +`CANCELLED` status, +`pid` field |
| `apps/backend/events/migrations/0011_scraperrun_run_cancellation.py` | new (generated) |
| `apps/backend/events/runner.py` | full rewrite: remove `_run_scraper`+threading, add `_map_result`+`cancel_run`, refactor `trigger_scraper_run` |
| `apps/backend/events/management/commands/run_scraper_job.py` | new file |
| `apps/backend/events/views.py` | +`api_scraper_run_cancel` view, update import |
| `apps/backend/events/urls.py` | +cancel URL pattern |
| `apps/backend/events/tests.py` | +new test classes, rewrite `RunnerTests` |
| `apps/frontend/src/lib/types.ts` | +`'cancelled'` to `ScraperRunStatus` |
| `apps/frontend/src/lib/api.ts` | +`cancelRun` method |
| `apps/frontend/src/lib/components/Badge.svelte` | +`cancelled` style |
| `apps/frontend/src/routes/scrapers/+page.svelte` | +`cancelling` state, +`handleCancel`, +Cancel button |

**NOT touched:** `apps/backend/events/scrapers/` (all 8 scraper files + `base.py`),
`apps/backend/events/admin.py`, all template files, `apps/backend/events/management/commands/scrape.py`.

---

## Public Contracts

### New API endpoint
```
POST /api/scrapers/runs/<id>/cancel/
  auth: public, @csrf_exempt, @require_POST
  200: serialized ScraperRun with status="cancelled"
  404: {"error": "Run not found"}
  409: {"error": "Run is not active", "run": <serialized run>}
  405: (on GET)
```

### Modified serialized shape
`_serialize_run` now emits `status: "cancelled"` for cancelled runs. No structural change
to existing fields. `pid` is NOT included in the serialized output.

### Modified `ScraperRunStatus` TypeScript union
```typescript
export type ScraperRunStatus = 'queued' | 'running' | 'success' | 'failed' | 'cancelled';
```

### `cancel_run` Python function signature
```python
def cancel_run(run_id: int) -> tuple[ScraperRun | None, str]:
    # signals: "ok" | "not_found" | "not_active"
```

### `trigger_scraper_run` signature — unchanged
```python
def trigger_scraper_run(key: str, triggered_by=None) -> tuple[ScraperRun | None, bool]:
```

---

## Blast Radius

- **Concurrency guard** in `trigger_scraper_run` filters `status__in=[QUEUED, RUNNING]`. The
  new `CANCELLED` status is excluded — correct behaviour (a cancelled run is terminal; a new
  run for the same key is allowed).
- **`api_scraper_runs_active`** filters `status__in=[QUEUED, RUNNING]`. Cancelled runs do not
  appear in the active poll — correct.
- **`ScraperRunAdmin`** in `admin.py` uses `list_filter: status` and `list_display: status`.
  Django admin automatically picks up the new TextChoices value. No admin.py edits needed.
- **`is_active` property** tested against `(QUEUED, RUNNING)` tuple — not affected.
- **Frontend polling** stops when `active.length === 0`. A cancelled run transitions out of
  the active endpoint, so polling stops naturally — no frontend polling logic change needed.
- **`run-all/` endpoint** iterates `SCRAPERS` and calls `trigger_scraper_run` per key. No
  change needed.
- **Subprocess orphan on server crash:** if the Django/gunicorn process dies while a
  subprocess is running, the subprocess becomes an orphan (its parent PID becomes `init`/`1`).
  The `ScraperRun` row stays `RUNNING` indefinitely. This is a known limitation of the
  subprocess model. A future reconciliation step (not in scope) would query `RUNNING` rows
  older than N minutes and attempt `os.kill(pid, 0)` to verify liveness, marking them FAILED
  if the pid is gone.

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|---|---|---|
| `manage.py` path wrong at runtime | Low | Derived from `settings.BASE_DIR` (Path object); validated at import time by checking `manage_py.exists()` in a dev assertion or startup check |
| `sys.executable` points to wrong Python | Very Low | Always the interpreter that started the Django process; same venv |
| `os.getpgid` raises `ProcessLookupError` before `killpg` | Medium | Caught explicitly; run marked CANCELLED anyway if row still active |
| Race: subprocess writes SUCCESS before parent writes CANCELLED | Medium | `transaction.atomic() + select_for_update()` + `refresh_from_db()` check covers this |
| Subprocess hangs despite SIGTERM (Playwright?) | Low | SIGTERM is sent to the whole process group; Playwright browser also in same group. If needed, a follow-up SIGKILL after a timeout can be added to `cancel_run` in a future pass |
| Migration conflict with existing 0010_scraperrun | None | `makemigrations` auto-detects the latest migration as parent |
| Existing 64 tests broken by `_run_scraper` removal | Medium | Step 16 explicitly migrates all 6 runner tests to new forms |

---

## Verification Evidence

### Backend: migration + tests
```bash
# Generate and verify migration
cd apps/backend
./venv/bin/python manage.py makemigrations events --name run_cancellation
./venv/bin/python manage.py migrate

# Run full test suite — must stay at 64+ (new tests add to the count)
./venv/bin/python manage.py test events --verbosity=2

# Expected: 0 errors, 0 failures, test count >= 64
```

### Backend: manual cancel verification
```bash
# Terminal 1: Start Django dev server
cd apps/backend && ./venv/bin/python manage.py runserver

# Terminal 2: Trigger a slow scraper (e.g. allevents_cdo uses Playwright)
curl -s -X POST http://localhost:8000/api/scrapers/allevents_cdo/run/ | python3 -m json.tool
# → {"id": <ID>, "status": "queued"}

# Poll until RUNNING
curl -s http://localhost:8000/api/scrapers/runs/active/ | python3 -m json.tool

# Cancel while RUNNING
curl -s -X POST http://localhost:8000/api/scrapers/runs/<ID>/cancel/ | python3 -m json.tool
# → {"id": <ID>, "status": "cancelled", "finished_at": "..."}

# Verify no orphaned chromium process
ps aux | grep chromium
# → should be empty (process group kill eliminated browser too)

# Verify re-trigger is allowed immediately after cancel
curl -s -X POST http://localhost:8000/api/scrapers/allevents_cdo/run/ | python3 -m json.tool
# → 200 (not 409)
```

### Backend: cancel-while-terminal guard
```bash
# Create a finished run, try to cancel it
# (Manually set a run to SUCCESS in admin or via shell)
curl -s -X POST http://localhost:8000/api/scrapers/runs/<SUCCESS_ID>/cancel/
# → HTTP 409, {"error": "Run is not active", ...}
```

### Frontend: build check
```bash
cd apps/frontend
pnpm exec svelte-check --tsconfig ./tsconfig.json
pnpm build
# → zero TypeScript errors; build succeeds
```

### Frontend: UI smoke test
1. Start both servers (`pnpm dev` from repo root or separately).
2. Navigate to `/scrapers`.
3. Click "Run" on `allevents_cdo` (Playwright scraper — takes time).
4. Verify spinner and status badge appear, Cancel button appears.
5. Click Cancel. Verify button shows "Cancelling…" then disappears.
6. Verify badge shows "cancelled" (amber/warning color).
7. Verify run appears in Recent Runs table with cancelled badge.
8. Verify Run button is re-enabled immediately.
9. `ps aux | grep chromium` — confirm browser process gone.

---

## Failure Modes

| Scenario | Behaviour |
|---|---|
| Cancel called on non-existent run_id | 404 |
| Cancel called on SUCCESS/FAILED/CANCELLED run | 409 with run body |
| Cancel called on QUEUED run (subprocess not started yet, pid may be null) | SIGTERM not sent (pid=null guard); status set to CANCELLED anyway |
| Subprocess exits between SIGTERM and `refresh_from_db` | `ProcessLookupError` caught; `refresh_from_db` sees row still active (subprocess didn't update it) → CANCELLED |
| Subprocess wins race and writes SUCCESS before `save()` | `refresh_from_db` sees SUCCESS → `is_active` False → skip CANCELLED write → return `(run, "ok")` with SUCCESS status |
| Django crashes mid-run | Run stays RUNNING with a real pid; future reconciliation can detect via `os.kill(pid, 0)` (not in scope) |
| `manage.py` path does not exist at Popen time | `FileNotFoundError` propagates from `Popen`; caught by `trigger_scraper_run`'s outer try block (not currently present — add a try/except around `Popen` that marks run FAILED) — see note in step 7 |

**QUEUED cancellation note:** if the run is QUEUED and `pid` is already set (parent stored it
synchronously right after `Popen`), the SIGTERM is still sent. If the subprocess hasn't entered
Django setup yet, it will be killed before it does any work. If `pid` is null (should not happen
given the synchronous `proc.pid` assignment, but defensive), skip the kill and just mark CANCELLED.

---

## Rollback Notes

- The migration adds a nullable column (`pid`) and a new choice to a TextChoices field.
  Rolling back: `python manage.py migrate events 0010` (reverts 0011). This drops the `pid`
  column; existing rows with `status='cancelled'` will have an orphaned value not in the
  choices list but will not break Postgres (it is a varchar constraint, not a DB enum).
  Purge any `cancelled` rows before rolling back if strict constraint enforcement is needed.
- The runner rewrite is a pure replacement. Rollback: revert `runner.py` to the thread-based
  version and delete `run_scraper_job.py`.
- Frontend type change is additive (`cancelled` added to union). No rollback needed unless
  the backend change is reverted.

---

## Resume and Execution Handoff

**Plan file:** `/home/hd/projects/veent-event-scraper/process/general-plans/active/run-cancellation_PLAN_17-06-26.md`

**Execute starting point:** Phase 1, step 1 — model change.

**Phase order:**
1. Phase 1 (model + migration): steps 1–4
2. Phase 2 (management command): steps 5–6
3. Phase 3 (runner refactor): steps 7–8
4. Phase 4 (cancel endpoint + URL): steps 9–10
5. Phase 5 (frontend): steps 11–14
6. Phase 6 (tests): steps 15–16

**Test gate:** After Phase 3, before Phase 5, run `manage.py test events` to verify backend
contract before touching frontend. All existing 64 tests must pass with the runner rewrite
(even without the new tests in Phase 6 — the refactor must not break existing coverage).

**Dependency rules:**
- Phase 2 depends on Phase 1 (command imports `ScraperRun.Status.CANCELLED`).
- Phase 3 depends on Phase 2 (`_map_result` helper exported from runner.py is imported by command).
- Phase 4 depends on Phase 3 (`cancel_run` must exist before the view imports it).
- Phase 5 is independent of backend changes at TypeScript level but requires the backend to be
  running for manual smoke test.
- Phase 6 tests can be written in any order but must be run after Phase 4 completes.

**Context to pass to EXECUTE agent:**
- This plan file (full path above)
- `apps/backend/events/runner.py` — current version (will be rewritten)
- `apps/backend/events/models.py` — current version
- `apps/backend/events/views.py` — current version (cancel view + import to add)
- `apps/backend/events/urls.py` — current version (cancel URL to add)
- `apps/backend/events/tests.py` — current version (tests to add/rewrite)
- `apps/frontend/src/lib/types.ts`
- `apps/frontend/src/lib/api.ts`
- `apps/frontend/src/lib/components/Badge.svelte`
- `apps/frontend/src/routes/scrapers/+page.svelte`

**Cross-platform note:** `os.setsid` / `killpg` are POSIX-only. This implementation uses
`start_new_session=True` in `Popen` (equivalent, cross-platform-safe in Python 3.2+, but on
Windows it maps to `CREATE_NEW_PROCESS_GROUP` — which is fine conceptually but `os.killpg`
does not exist on Windows). The dev/prod environment is Linux; no Windows support is required.
Document this in a comment in `runner.py`.
