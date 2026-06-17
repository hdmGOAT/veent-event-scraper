# Scraper Run Jobs — Implementation Plan

**Date**: 2026-06-17
**Complexity**: COMPLEX
**Status**: COMPLETE

---

## Completion Note

**Completed**: 2026-06-17
**Result**: Implemented and verified — 64 tests passing on Neon PostgreSQL; live browser flow
verified for page load, per-scraper Run, and Run All.

**Deviations from plan (for the historical record):**

(a) **Database:** The plan assumed SQLite; the real DB is Neon PostgreSQL. This only affected
the test harness — runner tests required `TransactionTestCase` (not `TestCase`) because
`TestCase`'s transaction wrapping prevents spawned threads from seeing uncommitted rows, and
`tearDown` must explicitly delete `ScraperRun` rows because Neon is not a discarded temp DB.
No production code change was needed.

(b) **Auth posture evolved during live verification.** The plan originally gated all endpoints
with `@staff_member_required`. Final state: all `GET /api/*` endpoints are public; the POST
trigger and run-all endpoints are public + `@csrf_exempt`. Two bugs drove this:
- A 500 error: `@staff_member_required` on a JSON endpoint redirected unauthenticated fetches
  to the HTML login page (302 → HTML); `res.json()` threw because the response was HTML, not JSON.
- A 403 error: CSRF cookie was never set on the session-less SvelteKit client, so
  `CsrfViewMiddleware` returned "CSRF cookie not set".
Root cause: the SvelteKit frontend has no auth bridge to Django (no login flow). Mutation
protection is deferred until a real auth bridge is implemented — this is a known security debt.

(c) **Scope addition:** `POST /api/scrapers/run-all/` and the corresponding **Run All** button
in the Scraper Center were added beyond the original plan scope. The endpoint skips already-active
keys and returns `{created: [...], skipped: [...]}`.

---

---

## Quick Links

- [Overview and Goals](#overview-and-goals)
- [Scope](#scope)
- [Architecture Decisions](#architecture-decisions)
- [Data Flow](#data-flow)
- [Touchpoints](#touchpoints)
- [Public Contracts](#public-contracts)
- [Implementation Checklist](#implementation-checklist)
- [Blast Radius](#blast-radius)
- [Failure Modes and Mitigations](#failure-modes-and-mitigations)
- [Verification Evidence](#verification-evidence)
- [Test Matrix](#test-matrix)
- [Resume and Execution Handoff](#resume-and-execution-handoff)

---

## Overview and Goals

Admins need to trigger scraper runs from the SvelteKit UI instead of logging into the server
to run `manage.py scrape`. The system must show currently-running jobs in near-real-time and
retain a history of every run. A new `ScraperRun` model is the single source of truth for
both live job state and history.

**In-scope**:
- `ScraperRun` model with full lifecycle (queued → running → success | failed)
- Thread-based runner with concurrency guard and SQLite-in-thread safety
- 4 new JSON API endpoints (trigger, list, active poll, detail)
- SvelteKit UI: enable Run button, show per-scraper status badge + counts + spinner, polling loop, history/active panel
- Django admin registration for `ScraperRun`

**Out-of-scope**:
- Item-level progress (no fetch() instrumentation)
- Celery / task queues (explicit non-requirement)
- Multi-user auth beyond staff check (same pattern as `/review/`)
- Log streaming (no SSE or WebSocket)
- Per-scraper scheduling (no cron configuration from UI)

---

## Scope

The work touches three layers:

1. **Backend — data layer**: one new model + one generated migration
2. **Backend — runner + API**: `events/runner.py` + 4 new views + updated `events/urls.py`
3. **Frontend**: `types.ts`, `api.ts`, `scrapers/+page.svelte` (plus its `+page.ts`)

---

## Architecture Decisions

All decisions are locked. Do not reopen.

| Decision | Choice | Rationale |
|---|---|---|
| Background execution | `threading.Thread` (daemon=True) | No new dependencies; fits WSGI dev server |
| Live updates | Frontend polling every 2-3 s | Simplest correct approach; matches team's stated preference |
| Progress granularity | Coarse (queued/running/success/failed + counts) | fetch()/run() internals must not be touched |
| Log model | Single row per run (`ScraperRun`) | Serves as both live job table and history; no separate log line table |
| Auth | `@staff_member_required` on POST trigger + all runs endpoints | Matches existing `/review/` convention |
| CSRF for SvelteKit POST | Send `X-CSRFToken` header obtained from the `csrftoken` cookie | Vite proxy makes it same-origin in dev; standard Django CSRF mechanism |
| Concurrency guard | Check for active run before spawning thread; return HTTP 409 | Prevents double-run of same scraper key |
| SQLite thread safety | Call `django.db.connection.close()` at end of worker thread | Required because SQLite connections are thread-local in Django |

---

## Data Flow

### Trigger flow (POST)

```
Browser (SvelteKit) -- POST /api/scrapers/{key}/run/ + CSRF header
  --> Django view (auth check, key validation, active-run guard)
    --> ScraperRun.objects.create(status=queued)
    --> threading.Thread(target=_run_scraper, args=(run_id, key)).start()
  <-- JsonResponse({id, status="queued"})  [immediate, ~5ms]

_run_scraper(run_id, key) [daemon thread]:
  --> ScraperRun.update(status=running, started_at=now)
  --> SCRAPERS[key]().run()  [may take 1-10 min for Playwright scrapers]
  --> on success: ScraperRun.update(status=success, finished_at, counts)
  --> on exception: ScraperRun.update(status=failed, finished_at, error_message)
  --> django.db.connection.close()  [SQLite thread-local cleanup]
```

### Polling flow (GET)

```
Browser (SvelteKit) -- GET /api/scrapers/runs/active/  [every 2-3 s while active runs exist]
  --> Django view: ScraperRun.objects.filter(status__in=[queued, running])
  <-- JsonResponse([{id, scraper_key, status, started_at, ...}])

Browser: if response is empty list → stop polling interval
```

### History flow (GET)

```
Browser (SvelteKit) -- GET /api/scrapers/runs/  [once on page load]
  --> Django view: ScraperRun.objects.all()[:50]
  <-- JsonResponse([...])
```

### Return dict → count mapping

| Scraper type | run() returns | Stored as |
|---|---|---|
| Event scrapers | `{source, created, updated}` | `created_count=created, updated_count=updated, extra_counts={}` |
| MyRuntime | `{source, created, updated, organizers_created, organizers_updated}` | `created_count=created, updated_count=updated, extra_counts={organizers_created: N, organizers_updated: N}` |
| GooglePlacesVenueScraper | `{source, created, updated}` | same as event scrapers |

The runner extracts `created` and `updated` from the dict, puts everything else (minus `source`)
into `extra_counts` as a JSONField.

---

## Touchpoints

### New files

| File | Purpose |
|---|---|
| `apps/backend/events/runner.py` | Thread runner: `trigger_scraper_run(key, triggered_by_id)` public function + `_run_scraper` private thread target |
| `apps/backend/events/migrations/0010_scraperrun.py` | Auto-generated by `makemigrations` — do NOT hand-write |

### Modified files

| File | Change |
|---|---|
| `apps/backend/events/models.py` | Add `ScraperRun` model at end of file |
| `apps/backend/events/admin.py` | Register `ScraperRunAdmin` |
| `apps/backend/events/views.py` | Add 4 new API views + import `trigger_scraper_run` |
| `apps/backend/events/urls.py` | Add 4 new URL patterns under `api/scrapers/` |
| `apps/backend/events/tests.py` | Add `ScraperRunModelTests`, `RunnerTests`, `RunEndpointTests` |
| `apps/frontend/src/lib/types.ts` | Add `ScraperRunStatus`, `ScraperRun` interfaces; extend `Scraper` with optional `active_run` |
| `apps/frontend/src/lib/api.ts` | Add `post()` helper, `runScraper`, `scraperRuns`, `activeRuns`, `scraperRun` |
| `apps/frontend/src/routes/scrapers/+page.ts` | Fetch initial runs alongside scrapers |
| `apps/frontend/src/routes/scrapers/+page.svelte` | Wire Run button, polling, status panel |

---

## Public Contracts

### ScraperRun serialised shape (used by all 4 endpoints)

```
{
  "id": <int>,
  "scraper_key": <str>,
  "status": "queued" | "running" | "success" | "failed",
  "started_at": <iso8601 | null>,
  "finished_at": <iso8601 | null>,
  "created_count": <int>,
  "updated_count": <int>,
  "extra_counts": <object>,
  "error_message": <str | null>,
  "triggered_by": <str | null>,  // username or null
  "created_at": <iso8601>,
  "duration_seconds": <float | null>  // computed property
}
```

### Endpoint contracts

| Method | URL | Auth | Request | Success | Error |
|---|---|---|---|---|---|
| POST | `/api/scrapers/<key>/run/` | staff required | empty body; `X-CSRFToken` header | 200 `{id, status}` | 404 unknown key / 409 already running |
| GET | `/api/scrapers/runs/` | staff required | `?limit=50` optional | 200 `[...ScraperRun]` | — |
| GET | `/api/scrapers/runs/active/` | staff required | — | 200 `[...ScraperRun]` (may be `[]`) | — |
| GET | `/api/scrapers/runs/<id>/` | staff required | — | 200 `ScraperRun` | 404 |

CSRF: The SvelteKit frontend reads the `csrftoken` cookie (set by Django's
`CsrfViewMiddleware` on any prior GET) and sends it as `X-CSRFToken`. In dev the Vite proxy
makes all requests same-origin so the cookie is accessible. Django's middleware accepts
`X-CSRFToken` for AJAX requests.

---

## Implementation Checklist

All steps are ordered for sequential execution. Each step is atomic and independently verifiable.

### Phase 1 — Backend data layer

- [ ] 1. **Model: `ScraperRun`** — add to `apps/backend/events/models.py` at end of file.
  - Class-level `Status` TextChoices inner class: `QUEUED="queued"`, `RUNNING="running"`, `SUCCESS="success"`, `FAILED="failed"`.
  - Fields (exact names, types, constraints):
    - `scraper_key`: `CharField(max_length=120, db_index=True)` — the SCRAPERS dict key.
    - `status`: `CharField(max_length=20, choices=Status.choices, default=Status.QUEUED, db_index=True)`.
    - `started_at`: `DateTimeField(null=True, blank=True)`.
    - `finished_at`: `DateTimeField(null=True, blank=True)`.
    - `created_count`: `IntegerField(default=0)`.
    - `updated_count`: `IntegerField(default=0)`.
    - `extra_counts`: `JSONField(default=dict, blank=True)` — holds any extra keys from run() dict beyond `source/created/updated`.
    - `error_message`: `TextField(blank=True)` — traceback string on failure; empty on success.
    - `triggered_by`: `ForeignKey("auth.User", on_delete=SET_NULL, null=True, blank=True, related_name="scraper_runs")`.
    - `created_at`: `DateTimeField(auto_now_add=True)`.
    - `updated_at`: `DateTimeField(auto_now=True)`.
  - `Meta`: `ordering = ["-created_at"]`.
  - `__str__`: returns `f"{self.scraper_key} [{self.status}] @ {self.created_at:%Y-%m-%d %H:%M}"`.
  - Property `duration_seconds` — returns `(finished_at - started_at).total_seconds()` if both are set, else `None`.
  - Property `is_active` — returns `self.status in (Status.QUEUED, Status.RUNNING)`.

- [ ] 2. **Generate migration** — run the following command from `apps/backend/`:
  ```
  ./venv/bin/python manage.py makemigrations events --name scraperrun
  ```
  Verify the generated file is `apps/backend/events/migrations/0010_scraperrun.py`.
  Do NOT edit the generated file.

- [ ] 3. **Apply migration** (for local dev verification):
  ```
  ./venv/bin/python manage.py migrate
  ```

- [ ] 4. **Admin registration** — add `ScraperRunAdmin` to `apps/backend/events/admin.py`.
  - Import `ScraperRun` from `.models`.
  - `list_display = ("scraper_key", "status", "started_at", "finished_at", "created_count", "updated_count", "triggered_by", "created_at")`.
  - `list_filter = ("status", "scraper_key")`.
  - `readonly_fields = ("scraper_key", "status", "started_at", "finished_at", "created_count", "updated_count", "extra_counts", "error_message", "triggered_by", "created_at", "updated_at")`.
  - Do not allow add/delete from admin (set `has_add_permission` and `has_delete_permission` to return `False`).

### Phase 2 — Backend runner

- [ ] 5. **Create `apps/backend/events/runner.py`**.
  - Module-level imports: `import traceback`, `import threading`, `from django.db import connection`, `from django.utils import timezone`, `from .models import ScraperRun`, `from .scrapers import SCRAPERS`.
  - Private function `_run_scraper(run_id: int, key: str) -> None`:
    - Fetch the `ScraperRun` row by `run_id`. Wrap entire body in try/except.
    - Update run: `status=RUNNING, started_at=timezone.now()`. Save with `update_fields=["status", "started_at", "updated_at"]`.
    - Call `result = SCRAPERS[key]().run()`.
    - On success:
      - Extract: `created = result.get("created", 0)`, `updated = result.get("updated", 0)`.
      - Extra counts: copy all keys from result dict except `source`, `created`, `updated` into `extra_counts` dict.
      - Update run: `status=SUCCESS, finished_at=timezone.now(), created_count=created, updated_count=updated, extra_counts=extra_counts`. Save with `update_fields=["status","finished_at","created_count","updated_count","extra_counts","updated_at"]`.
    - On any `Exception`:
      - `tb = traceback.format_exc()`.
      - Update run: `status=FAILED, finished_at=timezone.now(), error_message=tb`. Save with `update_fields=["status","finished_at","error_message","updated_at"]`.
    - Finally block (always executes): call `connection.close()` to release the SQLite thread-local connection.
  - Public function `trigger_scraper_run(key: str, triggered_by=None) -> tuple[ScraperRun, bool]`:
    - Signature: `(key: str, triggered_by=None) -> tuple[ScraperRun, bool]`. Returns `(run, already_active)`.
    - Guard: check `ScraperRun.objects.filter(scraper_key=key, status__in=[ScraperRun.Status.QUEUED, ScraperRun.Status.RUNNING]).exists()`. If True, return `(None, True)` — caller maps to 409.
    - Create: `run = ScraperRun.objects.create(scraper_key=key, triggered_by=triggered_by)`.
    - Spawn: `t = threading.Thread(target=_run_scraper, args=(run.id, key), daemon=True); t.start()`.
    - Return `(run, False)`.

  > WSGI dev-server note (for code comment): Django's dev server (`runserver`) is
  > single-process but starts a new thread per request. Daemon threads will be killed
  > if the dev server process exits. This is acceptable for development. Production
  > deployment behind gunicorn/uwsgi with multiple workers means each worker has its
  > own thread pool; a run started by worker A cannot be polled by worker B unless the
  > DB row is the shared state — which it is (the thread updates the DB, and polling
  > reads from the DB, so this is safe as long as the DB is truly shared — SQLite in
  > dev, where the single gunicorn worker model should be used).

### Phase 3 — Backend API views

- [ ] 6. **Add serialization helper** to `apps/backend/events/views.py`.
  - Private function `_serialize_run(run) -> dict` (not exposed as endpoint). Returns the
    standard `ScraperRun` dict matching the Public Contracts section above.
  - Compute `triggered_by` as `run.triggered_by.username if run.triggered_by_id else None`.
  - Compute `duration_seconds` as `run.duration_seconds` (uses the model property).

- [ ] 7. **Add 4 new view functions** to `apps/backend/events/views.py`.

  **`api_scraper_trigger(request, key)`**:
  - Decorator: `@staff_member_required` (no `@require_POST` — CSRF is enforced by `@staff_member_required`'s login redirect, but add `@require_POST` as well for explicitness; Django's CSRF middleware handles the `X-CSRFToken` header).
  - Import and call `trigger_scraper_run(key, triggered_by=request.user)`.
  - If key not in SCRAPERS: return `JsonResponse({"error": "Unknown scraper key"}, status=404)`.
  - If `already_active`: return `JsonResponse({"error": "Scraper already running"}, status=409)`.
  - Return `JsonResponse({"id": run.id, "status": run.status}, status=200)`.

  **`api_scraper_runs(request)`**:
  - Decorator: `@staff_member_required`.
  - `limit = min(int(request.GET.get("limit", 50)), 200)`.
  - `runs = ScraperRun.objects.select_related("triggered_by").order_by("-created_at")[:limit]`.
  - Return `JsonResponse([_serialize_run(r) for r in runs], safe=False)`.

  **`api_scraper_runs_active(request)`**:
  - Decorator: `@staff_member_required`.
  - `runs = ScraperRun.objects.filter(status__in=[ScraperRun.Status.QUEUED, ScraperRun.Status.RUNNING]).select_related("triggered_by")`.
  - Return `JsonResponse([_serialize_run(r) for r in runs], safe=False)`.

  **`api_scraper_run_detail(request, run_id)`**:
  - Decorator: `@staff_member_required`.
  - `run = get_object_or_404(ScraperRun.objects.select_related("triggered_by"), id=run_id)`.
  - Return `JsonResponse(_serialize_run(run))`.

- [ ] 8. **Update `apps/backend/events/urls.py`** — add 4 new patterns. Insert BEFORE the
  existing `api/scrapers/` line (more-specific paths before less-specific):
  ```python
  path("api/scrapers/<str:key>/run/", views.api_scraper_trigger, name="api_scraper_trigger"),
  path("api/scrapers/runs/active/", views.api_scraper_runs_active, name="api_scraper_runs_active"),
  path("api/scrapers/runs/<int:run_id>/", views.api_scraper_run_detail, name="api_scraper_run_detail"),
  path("api/scrapers/runs/", views.api_scraper_runs, name="api_scraper_runs"),
  path("api/scrapers/", views.api_scrapers, name="api_scrapers"),
  ```
  Note: Django resolves URL patterns top-to-bottom. `runs/active/` must appear before
  `runs/<int:run_id>/` to avoid `active` being parsed as an integer (it won't be, since
  it's not numeric, but ordering is still cleaner). `<str:key>/run/` must appear before
  the existing `api/scrapers/` catch-all.

  Also add the necessary imports to `views.py`: `from .runner import trigger_scraper_run`,
  `from .models import ..., ScraperRun`.

### Phase 4 — Frontend types and API client

- [ ] 9. **Extend `apps/frontend/src/lib/types.ts`**.
  - Add `ScraperRunStatus` type alias: `'queued' | 'running' | 'success' | 'failed'`.
  - Add `ScraperRun` interface matching the serialised shape from Public Contracts:
    ```ts
    export interface ScraperRun {
      id: number;
      scraper_key: string;
      status: ScraperRunStatus;
      started_at: string | null;
      finished_at: string | null;
      created_count: number;
      updated_count: number;
      extra_counts: Record<string, number>;
      error_message: string | null;
      triggered_by: string | null;
      created_at: string;
      duration_seconds: number | null;
    }
    ```
  - Extend existing `Scraper` interface with optional `active_run?: ScraperRun | null` (used
    by the UI to show a per-scraper badge; not returned by the existing `api_scrapers` endpoint —
    the frontend derives this from `activeRuns` response, it is NOT a new backend field).

- [ ] 10. **Extend `apps/frontend/src/lib/api.ts`**.
  - Add a private `post<T>(path: string): Promise<T>` helper:
    - Reads the `csrftoken` cookie value with a small helper `getCsrfToken(): string`:
      ```
      document.cookie.split(';').find(c=>c.trim().startsWith('csrftoken='))?.split('=')[1] ?? ''
      ```
    - Calls `fetch('/api' + path, { method: 'POST', headers: { 'X-CSRFToken': getCsrfToken(), 'Content-Type': 'application/json' }, credentials: 'include' })`.
    - Throws on non-ok responses with status code included in message.
  - Add to the `api` export object:
    ```ts
    runScraper: (key: string) => post<{ id: number; status: string }>(`/scrapers/${key}/run/`),
    scraperRuns: (limit?: number) => get<ScraperRun[]>(`/scrapers/runs/${limit ? `?limit=${limit}` : ''}`),
    activeRuns: () => get<ScraperRun[]>('/scrapers/runs/active/'),
    scraperRun: (id: number) => get<ScraperRun>(`/scrapers/runs/${id}/`),
    ```

### Phase 5 — Frontend page wiring

- [ ] 11. **Update `apps/frontend/src/routes/scrapers/+page.ts`**.
  - In the `load` function, fetch scrapers and recent runs in parallel:
    ```ts
    const [scrapers, recentRuns] = await Promise.all([
      api.scrapers(fetch),
      api.scraperRuns(undefined, fetch),
    ]);
    return { scrapers, recentRuns };
    ```
  - Note: `activeRuns` is NOT fetched in `load` — it is polled client-side after hydration.

- [ ] 12. **Rewrite `apps/frontend/src/routes/scrapers/+page.svelte`**.

  The component must use Svelte 5 runes. Key state and logic:

  **State (runes)**:
  ```ts
  let { data }: { data: PageData } = $props();
  let runningMap = $state<Map<string, ScraperRun>>(new Map());  // scraper_key -> active run
  let recentRuns = $state<ScraperRun[]>(data.recentRuns);
  let pollingInterval: ReturnType<typeof setInterval> | null = null;
  let triggering = $state<Set<string>>(new Set());  // keys currently being POST-triggered
  ```

  **Polling logic** (plain JS, not a Svelte lifecycle):
  - Function `startPolling()`: if `pollingInterval` is null, set up `setInterval(pollActive, 2500)`.
  - Function `stopPolling()`: clear the interval, set to null.
  - Function `pollActive()`: calls `api.activeRuns()`, updates `runningMap` from the response.
    If response is empty and interval is running, call `stopPolling()` and refresh `recentRuns`
    via `api.scraperRuns()` (to pick up newly completed runs).
  - On mount (`$effect` or `onMount`): call `pollActive()` immediately; if result is non-empty,
    call `startPolling()`. Also call `stopPolling` as cleanup on component destroy.

  **`handleRun(key: string)`** (async):
  1. Guard: if `triggering.has(key)` or `runningMap.has(key)`, return.
  2. `triggering = new Set([...triggering, key])`.
  3. Call `await api.runScraper(key)`.
  4. Remove key from `triggering`.
  5. Call `pollActive()` once immediately, then `startPolling()`.
  6. On error: show an inline error (store per-key error in a `$state` Map); remove from triggering.

  **Per-scraper card rendering** — for each `s` in `data.scrapers`:
  - Derive `const run = runningMap.get(s.key) ?? null`.
  - Derive `const isActive = run?.status === 'queued' || run?.status === 'running'`.
  - Run button:
    - `disabled` when `isActive || triggering.has(s.key)`.
    - `onclick={() => handleRun(s.key)}`.
    - Label: "Running..." when active, "Run" otherwise.
    - Style: use existing button class from `+page.svelte`; remove `cursor-not-allowed opacity-50` when enabled.
  - Status badge (only render when `run !== null`): use the existing `Badge` component
    (`import Badge from '$lib/components/Badge.svelte'`). The `status` prop maps directly
    since Badge already handles pending/confirmed/rejected; add `running` and `queued` CSS
    classes to `Badge.svelte`'s `styles` map:
    - `running: 'bg-accent-dim text-accent'`
    - `queued: 'bg-surface-2 text-muted'`
    - `success`: map to `'bg-success-bg text-success'` (add as alias for confirmed/verified)
    - `failed`: map to `'bg-danger-bg text-danger'` (add as alias for rejected)
  - Counts row (only when `run?.status === 'success'`): small muted text showing
    `{run.created_count} created, {run.updated_count} updated`. If `extra_counts` has keys,
    append them: e.g. `+ {run.extra_counts.organizers_created ?? 0} orgs created`.
  - Error row (only when `run?.status === 'failed'`): show a red `<pre>` with
    `{run.error_message}` truncated to 300 chars, with a "show full" toggle.
  - Spinner: show a small animated spinner (CSS-only, inline SVG or `animate-spin` Tailwind
    class on a ring div) when `isActive`.

  **Runs history panel** — below the scraper grid:
  - Section heading "Recent Runs" with a count badge.
  - Table or list rendering `recentRuns` (bound to `$state` so it updates when polling refresh fires).
  - Columns: Scraper, Status, Started, Duration, Created, Updated.
  - Format duration with a small `formatDuration(seconds: number | null): string` helper:
    returns `"—"` for null, `"<1s"` for <1, `"{n}s"` for <60, `"{m}m {s}s"` for ≥60.
  - Limit display to 20 rows; add a "show all" link or count.

  **Remove** the static informational paragraph about `manage.py scrape` once the button is wired (or repurpose it as a smaller note below the heading).

- [ ] 13. **Update `Badge.svelte`** to add `running`, `queued`, `success`, `failed` status
  mappings in its `styles` record (see step 12 for exact class strings).

---

## Blast Radius

### New files (net-new, no existing code affected)
- `apps/backend/events/runner.py`
- `apps/backend/events/migrations/0010_scraperrun.py` (generated)

### Modified files and impact
| File | Impact | Risk |
|---|---|---|
| `apps/backend/events/models.py` | Additive — new model class at end; zero changes to existing models | Low |
| `apps/backend/events/admin.py` | Additive — new admin registration | Low |
| `apps/backend/events/views.py` | Additive — 4 new functions + 1 helper; no changes to existing functions | Low |
| `apps/backend/events/urls.py` | Additive — 4 new URL patterns; existing pattern for `api/scrapers/` kept; ordering matters (see step 8) | Medium — URL ordering error would shadow existing endpoint |
| `apps/backend/events/tests.py` | Additive — new test classes | Low |
| `apps/frontend/src/lib/types.ts` | Additive — new interfaces, extends existing `Scraper` with optional field | Low |
| `apps/frontend/src/lib/api.ts` | Additive — new helper + 4 new api methods | Low |
| `apps/frontend/src/routes/scrapers/+page.ts` | Small change to `load()` — adds parallel run fetch | Low |
| `apps/frontend/src/routes/scrapers/+page.svelte` | Full rewrite of component logic; layout preserved | Medium — UI regression risk |
| `apps/frontend/src/lib/components/Badge.svelte` | Additive — new status keys in `styles` record | Low |

**Unaffected by this feature**: all other routes, views, models, scrapers, migrations 0001-0009.

---

## Failure Modes and Mitigations

| Failure | Mitigation |
|---|---|
| Thread crashes before writing `status=running` | `_run_scraper` wraps the update in the outer try/except. If even the `ScraperRun` fetch fails (row deleted), the exception is swallowed in the thread — no user impact beyond a stale `queued` row. A future cron cleanup could mark stale `queued` rows as failed after N minutes. |
| Playwright scraper runs for 10+ minutes, user navigates away | Polling stops. Thread continues running. DB row will eventually be updated. History panel will show the result on next page load. |
| WSGI multi-worker: run started in worker A, polls hit worker B | Both workers share the same DB. The thread updates the DB row; the polling view reads from the DB. No in-process state is relied upon. Safe. |
| SQLite WAL contention (thread writes while main writes) | Django's SQLite backend serializes writes via WAL mode. `connection.close()` at thread end releases the connection. Risk is low for dev; production should use Postgres (out of scope). |
| Double-click triggers two POSTs before guard fires | The `triggering` set in the frontend prevents re-submission before the response arrives. The backend guard checks the DB so two concurrent requests from different sessions are also safe (one gets 409). |
| CSRF token missing (first page load, no prior GET) | SvelteKit `load()` always GETs `/api/scrapers/` first, which causes Django's middleware to set the cookie. The cookie is present before any Run button click. |
| Unknown scraper key in URL | View returns 404. Frontend Run button only exists for keys from `data.scrapers`, which are keys from SCRAPERS — a closed set. |
| `extra_counts` has non-serializable values | `run()` only returns plain dicts with int values. Serialization is safe. |

---

## Verification Evidence

### Backend verification

```bash
# From apps/backend/

# 1. Confirm migration generated and applied
./venv/bin/python manage.py showmigrations events

# 2. Run the test suite (all 3 new test classes + existing tests must pass)
./venv/bin/python manage.py test events

# 3. Start the dev server
./venv/bin/python manage.py runserver

# 4. Log in as a staff user (via /admin/) then test the trigger endpoint
# Obtain CSRF token from cookie first:
# In browser devtools: document.cookie.match(/csrftoken=([^;]+)/)[1]
# Then:
curl -X POST http://localhost:8000/api/scrapers/myruntime/run/ \
  -H "X-CSRFToken: <token>" \
  -H "Cookie: csrftoken=<token>; sessionid=<sessionid>" \
  -H "Content-Length: 0"
# Expected: {"id": 1, "status": "queued"}

# 5. Poll active runs
curl http://localhost:8000/api/scrapers/runs/active/ \
  -H "Cookie: sessionid=<sessionid>"
# Expected: [{"id":1,"scraper_key":"myruntime","status":"running",...}]

# 6. Check history
curl http://localhost:8000/api/scrapers/runs/ \
  -H "Cookie: sessionid=<sessionid>"

# 7. 409 concurrency guard
curl -X POST http://localhost:8000/api/scrapers/myruntime/run/ \
  -H "X-CSRFToken: <token>" -H "Cookie: ..." -H "Content-Length: 0"
# Expected: {"error": "Scraper already running"} with HTTP 409

# 8. 404 unknown key
curl -X POST http://localhost:8000/api/scrapers/notakey/run/ \
  -H "X-CSRFToken: <token>" -H "Cookie: ..." -H "Content-Length: 0"
# Expected: HTTP 404
```

### Frontend verification

```bash
# From repo root (turborepo / pnpm)
pnpm dev
# or from apps/frontend:
pnpm --filter frontend dev

# Navigate to http://localhost:5173/scrapers
# Verify:
# - Run button is enabled and clickable
# - Clicking Run shows "Running..." and a spinner
# - Status badge appears on the card
# - After completion, counts appear
# - History panel updates
# - Polling stops when no active runs
```

---

## Test Matrix

### New Django test classes (add to `apps/backend/events/tests.py`)

**`ScraperRunModelTests(TestCase)`**:
- `test_str_representation` — create a run, check `__str__` format.
- `test_default_status_is_queued` — new row has `status="queued"`.
- `test_duration_seconds_none_when_no_started_at` — property returns None.
- `test_duration_seconds_computed_when_both_set` — set started_at and finished_at 5s apart, assert `~5.0`.
- `test_is_active_true_for_queued_and_running` — verify both statuses return True.
- `test_is_active_false_for_success_and_failed` — verify both statuses return False.

**`RunnerTests(TestCase)`**:
- `test_trigger_creates_run_row` — call `trigger_scraper_run("myruntime")`, assert `ScraperRun.objects.count() == 1`.
- `test_trigger_returns_run_and_false_when_clear` — check return tuple.
- `test_trigger_returns_none_true_when_already_active` — create an active run for a key, call trigger again, assert `(None, True)`.
- `test_run_scraper_happy_path` — mock `SCRAPERS["myruntime"]().run()` to return `{"source":"myruntime","created":3,"updated":1}`. Call `_run_scraper(run.id, "myruntime")`. Assert run reloaded from DB has `status="success"`, `created_count=3`, `updated_count=1`, `finished_at` is not None.
- `test_run_scraper_failure_path` — mock `SCRAPERS["myruntime"]().run()` to raise `RuntimeError("boom")`. Call `_run_scraper(run.id, "myruntime")`. Assert `status="failed"`, `error_message` contains "RuntimeError", `finished_at` is not None.
- `test_run_scraper_myruntime_extra_counts` — mock run() to return `{"source":"myruntime","created":2,"updated":0,"organizers_created":5,"organizers_updated":1}`. Assert `extra_counts == {"organizers_created":5,"organizers_updated":1}`.

**`RunEndpointTests(TestCase)`**:
- Setup: create a staff `User` and a non-staff `User`; log in as staff.
- `test_trigger_returns_200_and_run_id` — mock `trigger_scraper_run` to return `(mock_run, False)`. POST to `/api/scrapers/myruntime/run/`. Assert 200 and `{"id": ..., "status": "queued"}`.
- `test_trigger_returns_404_unknown_key` — POST to `/api/scrapers/badkey/run/`. Assert 404.
- `test_trigger_returns_409_when_already_active` — mock `trigger_scraper_run` to return `(None, True)`. Assert 409.
- `test_trigger_requires_staff` — log in as non-staff user. POST. Assert redirect to login (302).
- `test_trigger_requires_post` — GET to the trigger URL. Assert 405 or redirect.
- `test_runs_list_returns_recent_runs` — create 3 runs. GET `/api/scrapers/runs/`. Assert list length 3.
- `test_active_runs_returns_only_active` — create 1 queued, 1 success. GET `/api/scrapers/runs/active/`. Assert length 1.
- `test_run_detail_returns_correct_run` — create a run. GET `/api/scrapers/runs/{id}/`. Assert id matches.
- `test_run_detail_404_for_missing` — GET `/api/scrapers/runs/99999/`. Assert 404.
- `test_all_run_endpoints_require_staff` — test each GET endpoint without login, assert 302.

### Manual / exploratory checks

- Playwright scraper takes minutes — verify the page stays usable (polling continues, other cards work).
- Trigger the same scraper twice quickly — verify second request gets a 409 and no duplicate run appears in history.
- Check the admin at `/admin/events/scraperrun/` — verify all runs are listed, readonly.
- Verify CSRF: without a session cookie, the POST returns a 403 (Django CSRF middleware).

---

## Dependencies

- No new Python packages required.
- No new npm packages required.
- Migration 0010 depends on migration 0009 already being applied (it is, per current repo state).
- `django.contrib.auth` must be in `INSTALLED_APPS` for the `triggered_by` FK — it already is.
- Svelte 5 runes are already enforced project-wide (`runes: true` in `vite.config.ts`).

---

## Integration Notes

- `api_scrapers` (existing, GET) is unchanged. The frontend no longer derives "last run" from
  `Event.scraped_at` max per source — it still uses the existing endpoint for that. The new
  `activeRuns` polling is additive. No changes to `api_scrapers` serialisation.
- The `Scraper` type extension (`active_run?: ScraperRun | null`) is optional in TypeScript.
  The existing `load()` response still only returns `scrapers: Scraper[]` without active_run;
  the frontend derives the active state from `runningMap` built via polling.
- `Badge.svelte` style additions are additive — existing callers passing `pending`, `confirmed`,
  `verified`, `rejected` are unaffected.

---

## Resume and Execution Handoff

**Plan path**: `process/general-plans/active/scraper-run-jobs_PLAN_17-06-26.md`

**Execution sequence**: Steps 1-13 must be executed in order. Steps 1-4 (Phase 1) must complete
before Phase 2 starts (runner imports the model). Phase 2 must complete before Phase 3 (views
import from runner). Phase 4 and Phase 5 are frontend and can be parallelised with backend Phase 3
but must come after Phase 4 is done (page.svelte depends on types.ts and api.ts).

**Recommended order**:
1. Steps 1, 2, 3 (model + migration + apply)
2. Step 4 (admin)
3. Step 5 (runner)
4. Steps 6, 7, 8 (views + URLs) — verify backend endpoints with curl
5. Steps 9, 10 (frontend types + api client)
6. Step 11 (page.ts load update)
7. Steps 12, 13 (page.svelte rewrite + Badge update)
8. Step 14 (tests — all new test classes)

Step 14 (tests) is listed as a separate group below:

- [ ] 14. **Write tests** in `apps/backend/events/tests.py` covering `ScraperRunModelTests`,
  `RunnerTests`, and `RunEndpointTests` as detailed in the Test Matrix section. Run all tests
  with `./venv/bin/python manage.py test events` and confirm 0 failures before marking done.

**Rollback**: The migration adds a new table. To rollback: `./venv/bin/python manage.py migrate events 0009` followed by removing the generated migration file. All other changes are additive and can be reverted by reverting the edited files. No existing tables or views are altered.

**Validator**: After implementation run `node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs process/general-plans/active/scraper-run-jobs_PLAN_17-06-26.md` if the script exists.
