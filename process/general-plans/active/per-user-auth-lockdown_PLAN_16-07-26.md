# Per-User Auth Lockdown — Veent Event Scraper

**Date:** 16-07-26
**Complexity:** SIMPLE (single session, four sequenced areas)
**Status:** PENDING EXECUTION
**Builds on:** `deploy-readiness_PLAN_16-07-26.md` (fully implemented)

> **Scope summary:** Replace the single shared-password SvelteKit gate with per-user
> Django-backed sessions, brute-force lockout via django-axes, and JSON 401 enforcement
> at the Django layer so that a direct hit to Django:8000 is also rejected. Areas A and B
> are pure Django. Area C is pure SvelteKit. Area D is env/docs. Areas are independently
> reviewable but must be implemented in A → B → C → D order (Django endpoints must exist
> before SvelteKit validates against them).

---

## Table of Contents

- [Overview](#overview)
- [Goals and Success Metrics](#goals-and-success-metrics)
- [Scope](#scope)
- [Assumptions and Constraints](#assumptions-and-constraints)
- [Security Context](#security-context)
- [Blast Radius](#blast-radius)
- [Touchpoints](#touchpoints)
- [Public Contracts](#public-contracts)
- [Endpoint Guard / CSRF Decision Table](#endpoint-guard--csrf-decision-table)
- [Implementation Checklist](#implementation-checklist)
  - [Area A — Django auth endpoints and session hardening](#area-a--django-auth-endpoints-and-session-hardening)
  - [Area B — Django route guarding (defense-in-depth)](#area-b--django-route-guarding-defense-in-depth)
  - [Area C — SvelteKit auth rework](#area-c--sveltekit-auth-rework)
  - [Area D — Env, migrations, seeding, docs](#area-d--env-migrations-seeding-docs)
- [Verification Evidence](#verification-evidence)
- [Acceptance Criteria](#acceptance-criteria)
- [Risks and Mitigations](#risks-and-mitigations)
- [Resume and Execution Handoff](#resume-and-execution-handoff)

---

## Overview

The deploy-readiness pass added a **shared single-password gate** in SvelteKit hooks (the
`sess` HMAC cookie). That gate is now being **replaced** by per-user Django sessions so that:

1. Each operator logs in with their own username + password (tracked in `auth.User`).
2. Django's built-in session engine issues a `sessionid` cookie that SvelteKit proxies
   transparently.
3. The existing SvelteKit proxy already forwards `Cookie` headers to Django and relays
   `Set-Cookie` headers back to the browser without modification (confirmed in
   `hooks.server.ts` lines 29–60), so no proxy changes are required to make Django
   sessions flow through.
4. A brute-force lockout layer (`django-axes`) protects the new login endpoint.
5. All `/api/*` views return JSON 401 for unauthenticated direct Django requests (belt and
   suspenders beyond the SvelteKit gate).

`ScraperRun.triggered_by` (already a nullable FK to `auth.User`, populated when
`request.user.is_authenticated`) activates automatically once real sessions flow through
the proxy.

---

## Goals and Success Metrics

- An unauthenticated browser request to any protected route redirects to `/login`.
- A correct username + password combo creates a Django session, sets `sessionid` + `csrftoken`
  cookies, and grants access to all protected routes.
- After `AXES_FAILURE_LIMIT` (5) failed attempts within the cooloff window, the account/IP
  is locked; subsequent attempts return a lockout error without hitting the database auth path.
- A direct unauthenticated HTTP request to `http://localhost:8000/api/events/` returns
  JSON `{"error": "authentication required"}` with status 401.
- n8n webhook endpoints (`/webhooks/scrape/`, `/webhooks/ingest-events/`) continue to work
  with `X-Scraper-Key` and are NOT affected by the new login requirement.
- The `/review/*` staff UI continues to work via Django admin login (`@staff_member_required`)
  unchanged.
- The 197-test backend suite passes with `DEBUG=true` (axes disabled in tests, see A-6).
- Dev mode (`ENVIRONMENT != 'production'`) retains the bypass (no auth required in dev).
- `ScraperRun.triggered_by` is populated on all UI-triggered runs for authenticated users.

---

## Scope

**In scope:**
- `apps/backend/requirements.txt` — add `django-axes`
- `apps/backend/config/settings.py` — axes config, session hardening, AUTHENTICATION_BACKENDS
- `apps/backend/events/views.py` — new auth views, `@api_login_required` decorator, remove
  `@csrf_exempt` on guarded endpoints
- `apps/backend/events/urls.py` — wire new auth endpoints
- `apps/frontend/src/hooks.server.ts` — replace HMAC gate with `/api/auth/me` validation
- `apps/frontend/src/routes/login/+page.svelte` — username + password fields
- `apps/frontend/src/routes/login/+page.server.ts` — server-side GET csrf + POST login
- `apps/frontend/src/routes/logout/+server.ts` — POST to Django `/api/auth/logout`
- `apps/frontend/src/routes/+layout.svelte` — logout link → POST form
- `apps/frontend/src/lib/api.ts` — add `credentials:'include'` to `get()` helper
- `apps/frontend/src/lib/session.ts` — retire (delete or make empty re-export if imported elsewhere)
- `apps/backend/.env.example` — add axes tunables, SESSION_COOKIE_AGE
- `apps/frontend/.env.example` — remove DASHBOARD_PASSWORD + SESSION_SECRET; no new vars needed
- `docs/deployment/README.md` — new login flow, user creation, axes lockout, belt-and-suspenders note

**Out of scope:**
- DRF, JWT, or token-based auth
- Custom Django User model
- Celery/async job queue
- HTTPS provisioning
- n8n webhook auth changes
- The `/review/*` Django-rendered staff UI auth (stays on `@staff_member_required`)
- Any frontend UI refactor beyond the login page and logout flow

---

## Assumptions and Constraints

- The SvelteKit proxy (`proxyRequest`) forwards all request headers including `Cookie` and
  relays all response headers including `Set-Cookie` without modification. Confirmed at
  `hooks.server.ts:29–60`. No proxy changes are needed to make Django sessions work.
- `django.contrib.auth` + `django.contrib.sessions` + `SessionMiddleware` +
  `AuthenticationMiddleware` are all already present and active. Confirmed in `settings.py:91–109`.
- No custom User model. Stock `auth.User`. Confirmed in research.
- `django-axes` must be installed before running its migration. It adds its own table.
- Axes requires placement as the **first** item in `AUTHENTICATION_BACKENDS` when using
  `AxesStandaloneBackend`; `ModelBackend` goes second.
- `AxesMiddleware` must be placed **after** `AuthenticationMiddleware` in `MIDDLEWARE`.
- Behind nginx, client IPs arrive via `X-Forwarded-For`. Axes needs
  `AXES_IPWARE_META_PRECEDENCE_ORDER = ['HTTP_X_FORWARDED_FOR']` to read the correct IP
  (nginx already sets this header; `SECURE_PROXY_SSL_HEADER` in prod settings confirms the
  proxy trust pattern is already established).
- The login form action in `+page.server.ts` runs server-side, so it can call Django
  directly (not via the browser) using `DJANGO_API_URL` from env. This avoids the need for
  the browser to obtain a CSRF token separately — the server-side action can call
  `GET /api/auth/csrf` to seed the cookie, then `POST /api/auth/login` with the returned
  token.
- Dev bypass: `IS_PRODUCTION = process.env.ENVIRONMENT === 'production'` in hooks.server.ts
  (line 8). This check must remain; the new gate is also wrapped in it.
- `CSRF_TRUSTED_ORIGINS` is already set for `http://localhost:5173`, `http://127.0.0.1:5173`,
  and `PROD_ORIGIN`. The login POST from the SvelteKit server process hits Django at
  `http://localhost:8000` (or `DJANGO_API_URL`), so `http://localhost:8000` must also be in
  `CSRF_TRUSTED_ORIGINS` OR the login endpoint must read the CSRF cookie set in step
  `GET /api/auth/csrf` via the `X-CSRFToken` header. See A-3 for the exact mechanism.
- `SESSION_COOKIE_NAME` defaults to `sessionid` in Django — no change needed.
- `SESSION_COOKIE_SAMESITE` defaults to `'Lax'` in Django 4+ — make it explicit.
- The existing `api.ts` `get()` function lacks `credentials:'include'`; this must be fixed
  so SSR `fetch` calls from `+page.server.ts` load functions also carry the session cookie
  when the SvelteKit server makes outbound requests to Django. This is a real correctness
  fix, not cosmetic.

---

## Security Context

### Session security
- On successful login, Django calls `request.session.cycle_key()` (session fixation
  prevention — standard Django `login()` already does this).
- `SESSION_COOKIE_AGE`: set to 8 hours via env (`SESSION_COOKIE_AGE_SECONDS`, default 28800).
  This is short enough to require re-login for a day-old abandoned session.
- `SESSION_SAVE_EVERY_REQUEST = True`: sliding expiry — each request resets the 8-hour clock.
- `SESSION_COOKIE_SAMESITE = 'Lax'`: explicit.
- `SESSION_COOKIE_SECURE` and `SESSION_COOKIE_HTTPONLY` are already prod-gated (see
  `settings.py:220-222`).
- `SESSION_EXPIRE_AT_BROWSER_CLOSE`: leave at default (`False`) — operators close and reopen
  browsers frequently; forced re-login on browser close would be disruptive. Document the
  decision.

### Brute-force lockout (django-axes)
- `AXES_FAILURE_LIMIT = 5` (5 failed attempts triggers lockout)
- `AXES_COOLOFF_TIME = 1` (1 hour, expressed as `datetime.timedelta(hours=1)` in settings)
- `AXES_LOCKOUT_PARAMETERS = [['username', 'ip_address']]` (lock the combination of
  username + IP; this prevents a targeted attacker on the same network from cycling IPs to
  bypass a per-username lock, while not locking out the real user from a different IP)
- `AXES_RESET_ON_SUCCESS = True` (clear failure count on successful login)
- `AXES_LOCKOUT_CALLABLE` not needed — the default axes behavior returns 403; the login view
  must catch `AxesSignalPermissionDenied` (or rely on `AXES_LOCKOUT_RESPONSE`) and return
  JSON 423.
- For tests: `AXES_ENABLED = False` when `DEBUG = True` (or a test-settings override) —
  see A-6.

### CSRF posture
- The login endpoint (`POST /api/auth/login`) must be CSRF-protected (NOT `@csrf_exempt`)
  to prevent cross-site form submission attacks.
- The SvelteKit `+page.server.ts` form action obtains the CSRF cookie by calling
  `GET /api/auth/csrf` first (sets `csrftoken` cookie on the Django response), then reads
  the cookie value and sends `X-CSRFToken: <value>` header in the POST to `/api/auth/login`.
- Because this flow is server-to-server (SvelteKit node → Django), the CSRF check relies on
  the `X-CSRFToken` header (standard SPA pattern) rather than a cookie double-submit from
  the browser. The key constraint: `CSRF_TRUSTED_ORIGINS` must include the SvelteKit
  server's origin as seen from the Django process, OR the login view must use
  `@csrf_protect` with `ensure_csrf_cookie` and the header-based check. Django's
  `CsrfViewMiddleware` accepts `X-CSRFToken` header natively for non-browser clients.
  **Decision:** make `/api/auth/login` a standard CSRF-protected view (no decorator needed —
  `CsrfViewMiddleware` covers all views by default). The SvelteKit action calls
  `GET /api/auth/csrf` to get the token, then POSTs with `X-CSRFToken` header. The
  `csrftoken` cookie returned by `/api/auth/csrf` is relayed to the browser via `Set-Cookie`
  so subsequent SPA calls also work.
- The logout endpoint must also be CSRF-protected (POST only, with `X-CSRFToken`).
- All other mutating `/api/*` endpoints: remove `@csrf_exempt` from endpoints where the
  SPA already sends `X-CSRFToken` (confirmed in `api.ts`: `post()`, `postJson()`,
  `patch()`, `del()` all set the header). Read-only endpoints that currently lack
  `@csrf_exempt` (most GETs) need no change. See the endpoint table below for exact
  decisions per endpoint.

### Retiring the shared-password gate
- `DASHBOARD_PASSWORD` and `SESSION_SECRET` env vars are removed from the frontend env.
- `apps/frontend/src/lib/session.ts` (HMAC helpers) is deleted.
- The `sess` cookie is replaced by `sessionid` (Django) + `csrftoken` (Django).
- Any active `sess` cookies in browsers will be ignored (the gate logic that checked for them
  is removed).

---

## Blast Radius

| File | Change type | Rollback risk |
|---|---|---|
| `apps/backend/requirements.txt` | Additive (add `django-axes`) | Low — additive |
| `apps/backend/config/settings.py` | Extend (axes config, session settings, backends) | Medium — middleware ordering matters; wrong placement breaks all auth |
| `apps/backend/events/views.py` | Extend + modify (add 4 auth views + `@api_login_required` decorator; remove `@csrf_exempt` on guarded endpoints) | High — every guarded endpoint breaks if decorator logic is wrong |
| `apps/backend/events/urls.py` | Additive (4 new URL patterns) | Low |
| `apps/frontend/src/hooks.server.ts` | Replace gate logic (HMAC → /me call) | High — wrong logic = all-routes lockout or no auth |
| `apps/frontend/src/routes/login/+page.svelte` | Replace (password → username+password fields) | Medium — UI change; wrong field names break form submission |
| `apps/frontend/src/routes/login/+page.server.ts` | Replace (HMAC → Django login flow) | High — if csrf/login flow breaks, no one can log in |
| `apps/frontend/src/routes/logout/+server.ts` | Modify (proxy logout to Django) | Medium |
| `apps/frontend/src/routes/+layout.svelte` | Minor (logout `<a>` → POST form) | Low |
| `apps/frontend/src/lib/api.ts` | Minor (add `credentials:'include'` to `get()`) | Low — additive |
| `apps/frontend/src/lib/session.ts` | Delete | Low — only imported by files that are being rewritten |
| `apps/backend/.env.example` | Additive | None |
| `apps/frontend/.env.example` | Remove two vars, no new vars | None |
| `docs/deployment/README.md` | Additive notes | None |
| `apps/backend/events/migrations/` | New axes migration (auto-generated) | Low — additive table |

---

## Touchpoints

- `apps/backend/config/settings.py` — axes and session config affects all requests
- `apps/backend/events/views.py` — `@api_login_required` decorator applied to all `/api/*`
  views (except webhooks and read-only read endpoints if excluded — see table)
- `apps/frontend/src/hooks.server.ts` — every SvelteKit request passes through this; the
  `/me` call is the new per-request auth cost
- `apps/frontend/src/routes/login/+page.server.ts` — the CSRF-then-login server flow is
  the only entry point for new sessions; if it breaks, all users are locked out
- Django `AUTHENTICATION_BACKENDS` list — axes `AxesStandaloneBackend` must be first

---

## Public Contracts

- `GET /api/auth/csrf` — sets `csrftoken` cookie; returns 204. No auth required.
- `POST /api/auth/login` — JSON body `{username, password}`. CSRF-protected. Returns 200
  `{user: {id, username, email}}` + sets `sessionid` cookie. Returns 400 for bad input,
  401 for bad credentials, 423 for axes lockout.
- `POST /api/auth/logout` — CSRF-protected. Clears session. Returns 204. No-op if not
  logged in.
- `GET /api/auth/me` — returns 200 `{id, username, email}` if authenticated, 401 JSON if
  anonymous. No auth bypass.
- `GET /api/*` (guarded read endpoints) — returns 401 JSON for unauthenticated requests.
- `POST/PATCH/DELETE /api/*` (guarded write endpoints) — returns 401 JSON for
  unauthenticated requests; 403 for authenticated-but-no-CSRF.
- `/webhooks/scrape/` and `/webhooks/ingest-events/` — unchanged; `X-Scraper-Key` auth only.
- `/review/*` — unchanged; `@staff_member_required` → Django admin login.
- SvelteKit `sess` cookie — **retired**. Existing sessions are invalidated on next request
  (the gate logic that checked `sess` is removed).
- SvelteKit public paths: `/login`, `/logout`, `/favicon.ico`, `/_app/*`,
  `/api/auth/csrf`, `/api/auth/login` — reachable before authentication.
  `/api/auth/me` is technically callable pre-auth but returns 401 (the gate uses this
  intentionally).

---

## Endpoint Guard / CSRF Decision Table

> **Legend:**
> - Guard = `@api_login_required` applied (returns JSON 401 for anonymous)
> - CSRF = `@csrf_exempt` removed (Django's `CsrfViewMiddleware` enforces the token)
> - Note: `@csrf_exempt` is currently on all mutating views. After this plan, it is removed
>   from SPA-called endpoints. Webhook endpoints keep `@csrf_exempt` (they authenticate via
>   `X-Scraper-Key`, not sessions, and have no browser CSRF surface).

| URL | Method(s) | View function | Guard | CSRF | Rationale |
|---|---|---|---|---|---|
| `/api/auth/csrf` | GET | `api_auth_csrf` (new) | No | Yes (no-op on GET — middleware only checks POST+) | Public; sets cookie |
| `/api/auth/login` | POST | `api_auth_login` (new) | No | Yes (must enforce — removes `@csrf_exempt` which doesn't exist yet; plain view protected by default) | Pre-auth; axes handles brute force |
| `/api/auth/logout` | POST | `api_auth_logout` (new) | No | Yes | Pre-auth callable (logout of already-logged-out session is fine) |
| `/api/auth/me` | GET | `api_auth_me` (new) | No | No CSRF issue (GET) | Returns 401 for anon; gate uses this |
| `/api/stats/` | GET | `api_stats` | Yes | No (GET — no state change) | Dashboard summary; PII-adjacent |
| `/api/events/by-source/` | GET | `api_events_by_source` | Yes | No | Aggregate; guarded for consistency |
| `/api/events/by-category/` | GET | `api_events_by_category` | Yes | No | Aggregate |
| `/api/events/agent-categories/` | GET | `api_agent_categories` | Yes | No | Internal config |
| `/api/events/` | GET | `api_events` | Yes | No | PII (event names, organizers) |
| `/api/organizers/export/` | GET | `api_organizers_export` | Yes | No | Exports PII CSV |
| `/api/leads/` | GET | `api_leads` | Yes | No | PII |
| `/api/organizers/<slug>/` | GET, PATCH | `api_organizer_detail` | Yes | PATCH: Yes (remove `@csrf_exempt`); GET: No | PATCH mutates; GET reads |
| `/api/organizers/` | GET | `api_organizers` | Yes | No | PII |
| `/api/venues/types/` | GET | `api_venue_types` | Yes | No | Internal config |
| `/api/venues/map/` | GET | `api_venues_map` | Yes | No | Location data |
| `/api/venues/<slug>/` | GET | `api_venue_detail` | Yes | No | Venue data |
| `/api/venues/` | GET | `api_venues` | Yes | No | Venue data |
| `/api/settings/proxy/` | GET, POST | `api_proxy_setting` | Yes | POST: Yes (remove `@csrf_exempt`); GET: No | POST toggles runtime setting |
| `/api/scrapers/<key>/run/` | POST | `api_scraper_trigger` | Yes | Yes (remove `@csrf_exempt`) | Mutating; triggers long-running job |
| `/api/scrapers/dedup/` | POST | `api_dedup_trigger` | Yes | Yes (remove `@csrf_exempt`) | Mutating |
| `/api/scripts/<name>/run/` | POST | `api_script_trigger` | Yes | Yes (remove `@csrf_exempt`) | Mutating |
| `/api/scrapers/run-all/` | POST | `api_scraper_run_all` | Yes | Yes (remove `@csrf_exempt`) | Mutating |
| `/api/scrapers/runs/active/` | GET | `api_scraper_runs_active` | Yes | No | Read |
| `/api/scrapers/runs/<id>/cancel/` | POST | `api_scraper_run_cancel` | Yes | Yes (remove `@csrf_exempt`) | Mutating |
| `/api/scrapers/runs/<id>/` | GET | `api_scraper_run_detail` | Yes | No | Read |
| `/api/scrapers/runs/` | GET | `api_scraper_runs` | Yes | No | Read |
| `/api/scrapers/` | GET | `api_scrapers` | Yes | No | Read |
| `/api/search-queries/<pk>/run/` | POST | `api_search_query_run` | Yes | Yes (remove `@csrf_exempt`) | Mutating |
| `/api/search-queries/<pk>/` | GET, PATCH, DELETE | `api_search_query_detail` | Yes | PATCH/DELETE: Yes (remove `@csrf_exempt`); GET: No | Mixed |
| `/api/search-queries/` | GET, POST | `api_search_queries` | Yes | POST: Yes (remove `@csrf_exempt`); GET: No | Mixed |
| `/api/tracker-notes/` | GET, POST | `api_tracker_notes` | Yes | POST: Yes (remove `@csrf_exempt`); GET: No | Mixed |
| `/api/tracker-notes/<pk>/` | GET, PATCH, DELETE | `api_tracker_note_detail` | Yes | PATCH/DELETE: Yes (remove `@csrf_exempt`); GET: No | Mixed |
| `/webhooks/scrape/` | POST | `scraper_webhook` | No | No — keep `@csrf_exempt` | X-Scraper-Key auth; no browser session |
| `/webhooks/ingest-events/` | POST | `ingest_events_webhook` | No | No — keep `@csrf_exempt` | X-Scraper-Key auth |
| `/review/` | GET | `review_dashboard` | No (keep `@staff_member_required`) | n/a — Django form renders its own token | Staff-only Django-rendered UI; separate auth path |
| `/review/venues/<slug>/` | GET | `review_venue_detail` | No (keep `@staff_member_required`) | n/a | As above |
| `/review/venues/<slug>/status/` | POST | `review_set_status` | No (keep `@staff_member_required`) | n/a | As above |

**Decision note on read endpoints:** All read-only `/api/*` endpoints are guarded because
the data they return (events, organizers, leads, venues) contains PII and operational data
that should not be publicly accessible. The marginal per-request cost of the decorator is a
Python function call check (`request.user.is_authenticated`), which is negligible.

**CSRF exemption retention rule:** `@csrf_exempt` stays ONLY on webhook endpoints that use
`X-Scraper-Key`. Everything else has it removed; the SPA already sends `X-CSRFToken` on all
mutations (confirmed in `api.ts`), so removing `@csrf_exempt` on those views adds real
protection without breaking anything.

---

## Implementation Checklist

### Area A — Django auth endpoints and session hardening

*(Files: `apps/backend/requirements.txt`, `apps/backend/config/settings.py`,
`apps/backend/events/views.py`, `apps/backend/events/urls.py`)*

- [ ] **A-1** `apps/backend/requirements.txt` — add `django-axes` (unpinned, same style
  as `Django` and `gunicorn` in the file). No version pin needed; axes is a stable,
  well-maintained package. Add on its own line after the existing Django ecosystem deps.

- [ ] **A-2** `apps/backend/config/settings.py` — add `'axes'` to `INSTALLED_APPS` after
  `'events'` (line ~98). Axes must be installed before its migration can run.

- [ ] **A-3** `apps/backend/config/settings.py` — add `AUTHENTICATION_BACKENDS` list
  immediately after `INSTALLED_APPS`:
  ```
  AUTHENTICATION_BACKENDS = [
      'axes.backends.AxesStandaloneBackend',
      'django.contrib.auth.backends.ModelBackend',
  ]
  ```
  `AxesStandaloneBackend` must be first so it can intercept locked accounts before
  `ModelBackend` authenticates them.

- [ ] **A-4** `apps/backend/config/settings.py` — insert `'axes.middleware.AxesMiddleware'`
  into `MIDDLEWARE` immediately AFTER `'django.contrib.auth.middleware.AuthenticationMiddleware'`
  (currently line 106). The final order at that position must be:
  ```
  ...
  'django.contrib.auth.middleware.AuthenticationMiddleware',
  'axes.middleware.AxesMiddleware',
  'django.contrib.messages.middleware.MessageMiddleware',
  ...
  ```

- [ ] **A-5** `apps/backend/config/settings.py` — add axes configuration block after the
  `MIDDLEWARE` definition (before the `ROOT_URLCONF` line). Variables:
  - `AXES_FAILURE_LIMIT = int(os.environ.get('AXES_FAILURE_LIMIT', '5'))`
  - `AXES_COOLOFF_TIME = datetime.timedelta(hours=int(os.environ.get('AXES_COOLOFF_HOURS', '1')))`
    (requires `import datetime` at top of file — add it after the existing `import os`)
  - `AXES_LOCKOUT_PARAMETERS = [['username', 'ip_address']]`
  - `AXES_RESET_ON_SUCCESS = True`
  - `AXES_IPWARE_META_PRECEDENCE_ORDER = ['HTTP_X_FORWARDED_FOR', 'REMOTE_ADDR']`
    (reads the real client IP from nginx's forwarded header)

- [ ] **A-6** `apps/backend/config/settings.py` — add axes test bypass immediately after
  the axes config block:
  ```python
  # Disable axes lockout in dev/test so the test suite is not affected.
  if DEBUG:
      AXES_ENABLED = False
  ```
  This ensures the 197-test suite runs cleanly with `DEBUG=true` (the CI env). Tests that
  explicitly test lockout behavior would need a separate test settings override; none
  currently exist so this is sufficient.

- [ ] **A-7** `apps/backend/config/settings.py` — add session hardening settings after the
  `AXES_ENABLED` block (unconditional — some apply in dev too):
  ```python
  SESSION_COOKIE_AGE = int(os.environ.get('SESSION_COOKIE_AGE_SECONDS', str(8 * 60 * 60)))  # 8 hours default
  SESSION_SAVE_EVERY_REQUEST = True   # Sliding expiry — each request resets the timer
  SESSION_COOKIE_SAMESITE = 'Lax'    # Explicit (Django 4+ default but make it clear)
  # SESSION_EXPIRE_AT_BROWSER_CLOSE is left at default (False) — operators frequently
  # close and reopen browsers; forced re-login on close is unnecessarily disruptive.
  ```
  Note: `SESSION_COOKIE_SECURE` and `SESSION_COOKIE_HTTPONLY` are already set in the
  `if not DEBUG:` prod-hardening block at the bottom of settings.py (lines 220–222).
  Do not duplicate them here — reference that they exist.

- [ ] **A-8** `apps/backend/events/views.py` — add the `@api_login_required` decorator
  function near the top of the file (after imports, before any view functions). It must:
  - Accept a view function and return a wrapped function.
  - If `request.user.is_authenticated` is False, return
    `JsonResponse({"error": "authentication required"}, status=401)` immediately.
  - Otherwise call and return the original view function.
  - Be a simple pure-Python decorator (no class-based view machinery).
  - Name: `api_login_required` (snake_case, consistent with the rest of the file).

- [ ] **A-9** `apps/backend/events/views.py` — add four new JSON auth view functions.
  Place them in a clearly marked section (e.g. a comment `# ── Auth endpoints ──────`)
  before the existing API views. Import requirements: `from django.contrib.auth import
  authenticate, login, logout` must be added to the existing imports at the top of the file
  (verify they are not already present — they likely are not since no current login view
  exists). Also need `from django.middleware.csrf import get_token` for the csrf endpoint.

  **A-9a** `api_auth_csrf(request)`:
  - Method: GET (or any)
  - Call `get_token(request)` to ensure the `csrftoken` cookie is set on the response.
  - Return `JsonResponse({}, status=204)`.
  - No decorator needed; reachable pre-auth.

  **A-9b** `api_auth_login(request)`:
  - Method: POST only (return 405 for other methods).
  - NOT `@csrf_exempt` — protected by `CsrfViewMiddleware` by default.
  - Parse JSON body: `username`, `password`. Return 400 if either is missing.
  - Call `authenticate(request, username=username, password=password)`.
    - If `None` is returned (bad credentials OR axes locked): check if axes locked the
      account by catching `PermissionDenied` (axes raises this via signal when locked) or
      checking `axes.helpers.is_already_locked(request)` after a failed `authenticate()`.
      Return 423 with `{"error": "account locked — too many failed attempts"}` for lockout,
      401 with `{"error": "invalid credentials"}` for plain failure.
    - If user returned: call `login(request, user)` (creates session, cycles key). Return
      200 with `{"user": {"id": user.id, "username": user.username, "email": user.email}}`.
  - **Implementation note on axes lockout detection:** `authenticate()` returns `None` for
    both bad password and axes lockout. To distinguish, call
    `axes.helpers.is_already_locked(request)` (or check
    `axes.backends.AxesStandaloneBackend.is_already_locked`) before or after the
    `authenticate()` call. The axes docs describe two patterns; use the post-`authenticate()`
    check: if `user is None`, then if `is_already_locked(request)` → 423, else → 401.

  **A-9c** `api_auth_logout(request)`:
  - Method: POST only.
  - NOT `@csrf_exempt`.
  - Call `logout(request)` (flushes session regardless of auth state — safe to call when
    anonymous).
  - Return `JsonResponse({}, status=204)`.

  **A-9d** `api_auth_me(request)`:
  - Method: GET.
  - If `request.user.is_authenticated`: return 200
    `{"id": user.id, "username": user.username, "email": user.email}`.
  - Else: return 401 `{"error": "not authenticated"}`.
  - No `@api_login_required` decorator — the 401 response is the gate behavior itself.

- [ ] **A-10** `apps/backend/events/urls.py` — add four auth URL patterns. Wire them above
  the existing `api/` patterns (they are a separate path group). Add:
  ```
  path("api/auth/csrf", views.api_auth_csrf, name="api_auth_csrf"),
  path("api/auth/login", views.api_auth_login, name="api_auth_login"),
  path("api/auth/logout", views.api_auth_logout, name="api_auth_logout"),
  path("api/auth/me", views.api_auth_me, name="api_auth_me"),
  ```
  Note: no trailing slash — these are JSON API endpoints; keep consistent with the style
  used by the SvelteKit caller (`api.ts` omits trailing slashes on POST targets).
  Verify this is acceptable: Django's `APPEND_SLASH` behavior may redirect GETs without
  trailing slash. If `APPEND_SLASH = True` (default), Django redirects `GET /api/auth/me`
  to `/api/auth/me/` — which may break the SvelteKit hooks `/me` call. **Decision:** add
  trailing slashes to all four URL patterns to be consistent with the rest of `urls.py` and
  avoid the redirect issue. The SvelteKit caller must use the same trailing-slash form.

- [ ] **A-11** Run `python manage.py makemigrations` (should produce nothing new for the
  events app) and `python manage.py migrate axes` (creates the `axes_accesslog` and
  `axes_accessfailurelog` tables). This is a plan note for the executor — include as a step.

---

### Area B — Django route guarding (defense-in-depth)

*(File: `apps/backend/events/views.py`)*

- [ ] **B-1** Apply `@api_login_required` to all view functions listed with "Yes" in the
  Guard column of the endpoint table above. Use the decorator directly on the function
  definition (same style as `@csrf_exempt` is used today). The decorator must be applied
  AFTER any existing `@require_POST` or `@require_GET` decorators (innermost), so that
  method enforcement happens before auth enforcement. Decorator order (outermost first):
  `@api_login_required`, then `@require_POST` if present.

  **Exact list of views receiving `@api_login_required`** (verify each line number before
  applying — line numbers may shift after A-9's additions):
  - `api_stats`
  - `api_events_by_source`
  - `api_events_by_category`
  - `api_agent_categories`
  - `api_events`
  - `api_organizers_export`
  - `api_leads`
  - `api_organizer_detail`
  - `api_organizers`
  - `api_venue_types`
  - `api_venues_map`
  - `api_venue_detail`
  - `api_venues`
  - `api_proxy_setting`
  - `api_scraper_trigger`
  - `api_dedup_trigger`
  - `api_script_trigger`
  - `api_scraper_run_all`
  - `api_scraper_runs_active`
  - `api_scraper_run_cancel`
  - `api_scraper_run_detail`
  - `api_scraper_runs`
  - `api_scrapers`
  - `api_search_query_run`
  - `api_search_query_detail`
  - `api_search_queries`
  - `api_tracker_notes`
  - `api_tracker_note_detail`

  **Views NOT receiving `@api_login_required`** (do not touch):
  - `scraper_webhook` — keep `@csrf_exempt` + X-Scraper-Key
  - `ingest_events_webhook` — keep `@csrf_exempt` + X-Scraper-Key
  - `review_dashboard`, `review_venue_detail`, `review_set_status` — keep `@staff_member_required`
  - New auth views (`api_auth_csrf`, `api_auth_login`, `api_auth_logout`, `api_auth_me`)

- [ ] **B-2** Remove `@csrf_exempt` from all view functions listed with "Yes" in the CSRF
  column of the endpoint table above. Specifically (current decorator locations from research):
  - Line ~632: `api_organizer_detail` — remove `@csrf_exempt`
  - Line ~832: `api_proxy_setting` — remove `@csrf_exempt`
  - Line ~859: `api_scraper_trigger` — remove `@csrf_exempt`
  - Line ~917: `api_scraper_run_all` — remove `@csrf_exempt`
  - Line ~954: `api_dedup_trigger` — remove `@csrf_exempt`
  - Line ~1002: `api_script_trigger` — remove `@csrf_exempt`
  - Line ~1070: `api_scraper_run_cancel` — remove `@csrf_exempt`
  - Line ~1164: `api_search_queries` — remove `@csrf_exempt`
  - Line ~1197: `api_search_query_run` — remove `@csrf_exempt`
  - Line ~1220: `api_search_query_detail` — remove `@csrf_exempt`
  - Line ~1267: `api_tracker_notes` — remove `@csrf_exempt`
  - Line ~1299: (second block around tracker-notes) — verify exact function and remove
  - Line ~1381: `api_tracker_notes` list — remove (the second `@csrf_exempt` block around
    line 1381 — verify which view this is; may be `api_tracker_note_detail`)
  - Line ~1419: `api_tracker_note_detail` — remove `@csrf_exempt`

  **Keep `@csrf_exempt`:**
  - `scraper_webhook` (line ~1267)
  - `ingest_events_webhook` (line ~1299)
  (Verify these line numbers after A-9's additions shift the file.)

  **Views that never had `@csrf_exempt` (no change needed):**
  - All pure GET-only read views that lacked the decorator: `api_stats`, `api_events`,
    `api_organizers`, `api_venues`, `api_venue_types`, `api_venues_map`, `api_scrapers`,
    `api_scraper_runs`, `api_scraper_runs_active`, `api_scraper_run_detail`, `api_leads`,
    `api_events_by_source`, `api_events_by_category`, `api_agent_categories`

---

### Area C — SvelteKit auth rework

*(Files: `apps/frontend/src/hooks.server.ts`, `apps/frontend/src/routes/login/+page.svelte`,
`apps/frontend/src/routes/login/+page.server.ts`, `apps/frontend/src/routes/logout/+server.ts`,
`apps/frontend/src/routes/+layout.svelte`, `apps/frontend/src/lib/api.ts`,
`apps/frontend/src/lib/session.ts`)*

- [ ] **C-1** `apps/frontend/src/lib/session.ts` — delete the file (or replace with an
  empty module if TypeScript compilation requires a module to exist at the import path).
  Verify: `session.ts` is imported in `hooks.server.ts` (line 2) and
  `routes/login/+page.server.ts` (line 3). Both files are being rewritten in C-2 and C-4,
  so the import will be removed there. Once both imports are gone, the file can be safely
  deleted. Delete it as the LAST step of Area C, after C-4 is complete, to avoid dangling
  import errors during incremental implementation.

- [ ] **C-2** `apps/frontend/src/hooks.server.ts` — rewrite the auth gate section. Keep:
  - The `DJANGO_URL` and `NODE_URL` constants (lines 6–7).
  - The `IS_PRODUCTION` constant (line 8).
  - The `proxyRequest` function (lines 29–60) — unchanged.
  - The `/node-api/*` proxy block.
  - The `/api/*` proxy block.
  - The `/tracker` redirect at the end.
  - The dev bypass structure (`if (IS_PRODUCTION) { ... }`).

  Remove:
  - The `SESSION_SECRET` constant and its startup warning.
  - The `verifyToken` import from `$lib/session`.
  - The `sess` cookie check.

  Add:
  - A `PUBLIC_PATHS` set that includes `/login`, `/logout`, `/favicon.ico` AND also
    `/api/auth/login`, `/api/auth/logout`, `/api/auth/csrf` (these must be reachable
    pre-auth because the login form action POSTs to them). `/api/auth/me` does NOT need to
    be in public paths — it is callable pre-auth but returns 401, which the gate interprets.
  - Auth check: for protected routes, call `GET {DJANGO_URL}/api/auth/me/` forwarding the
    browser's `Cookie` header. If response is 401, redirect to `/login`. If 200, allow.
  - The `/me` check is per-request (every non-public, non-asset path makes one outbound
    HTTP call to Django on the same host). This is acceptable for this admin dashboard's
    traffic. Note it in a code comment.
  - Keep the `/_app/` prefix bypass (static assets).
  - Structure: `isPublicPath()` check runs first → return `resolve(event)` for public paths.
    Then, if `IS_PRODUCTION`, call `/me` → if 401 → redirect to `/login`. Then continue
    to proxy logic.

  **Critical proxy flow note:** When the gate calls `GET /me`, it must forward only the
  `Cookie` header from `event.request.headers`, not the full request headers (to avoid
  sending the request body or content-type). The `/me` fetch is a simple HEAD-style check:
  ```
  const meRes = await fetch(`${DJANGO_URL}/api/auth/me/`, {
    headers: { Cookie: event.request.headers.get('Cookie') ?? '' }
  });
  ```
  If `meRes.status === 401`, redirect to `/login`. Any other error (502, 503) should let
  the request through with a log warning rather than locking users out of a temporarily
  unavailable backend.

- [ ] **C-3** `apps/frontend/src/routes/login/+page.svelte` — replace the single-password
  form with a username + password form. Changes:
  - Remove the `<p>Enter the dashboard password to continue.</p>` text.
  - Replace the single `<input name="password">` with two inputs:
    - `<input id="username" name="username" type="text" autocomplete="username" required>`
    - `<input id="password" name="password" type="password" autocomplete="current-password" required>`
  - Add a `<label for="username">Username</label>` before the username input.
  - Rename the existing label to `<label for="password">Password</label>`.
  - Keep the existing error display block; update the error text from "Incorrect password"
    to "Invalid username or password." Also add a second error variant for lockout:
    `?error=locked` → "Account locked — too many failed attempts. Try again later."
  - Keep the form `method="POST"` and submit button unchanged.
  - Keep all existing Tailwind classes (same design language as the deploy-readiness plan).

- [ ] **C-4** `apps/frontend/src/routes/login/+page.server.ts` — full rewrite of the
  `default` action. Remove the HMAC/`signToken` import and the `DASHBOARD_PASSWORD` /
  `SESSION_SECRET` env reads. New logic:
  1. Read `username` and `password` from `formData`.
  2. Call `GET {DJANGO_URL}/api/auth/csrf/` to obtain the CSRF token. Extract the
     `csrftoken` cookie value from the response's `Set-Cookie` header (or parse the
     `set-cookie` header string). This gives us the token to use in the POST header.
  3. Call `POST {DJANGO_URL}/api/auth/login/` with:
     - `Content-Type: application/json`
     - `X-CSRFToken: <token from step 2>`
     - `Cookie: csrftoken=<token>` (the CSRF double-submit — Django's middleware needs
       the cookie AND the header to match)
     - JSON body: `{username, password}`
  4. If the response is 401 → `redirect(303, '/login?error=1')`.
  5. If the response is 423 → `redirect(303, '/login?error=locked')`.
  6. If the response is 200 → relay all `Set-Cookie` headers from the Django response to
     the browser. This sets `sessionid` and `csrftoken` on the browser. Then
     `redirect(303, '/')`.
  7. For unexpected errors (5xx, network) → `throw error(502, 'Login service unavailable')`.

  **Cookie relay mechanics:** SvelteKit's `+page.server.ts` actions can set cookies via the
  `cookies` API. However, relaying `Set-Cookie` headers from a fetch response is best done
  by reading `djangoResponse.headers.getSetCookie()` (returns an array of raw `Set-Cookie`
  strings) and using `event.setHeaders({'set-cookie': value})` for each one, OR by parsing
  the cookie attributes and using `cookies.set()` for each cookie. The `cookies.set()`
  approach is cleaner and respects SvelteKit's type safety. Parse the `Set-Cookie` header
  values to extract `name`, `value`, `httpOnly`, `secure`, `sameSite`, `maxAge`, and
  `path` attributes, then call `cookies.set(name, value, options)`.

  Alternatively, since the SvelteKit server action runs on the server and the response is
  redirected, the `Set-Cookie` headers on the redirect response can be set directly via
  `redirect(303, '/', { headers: { 'set-cookie': rawCookieHeader } })` if SvelteKit
  supports it (check: SvelteKit `redirect` does not accept a headers arg in all versions).
  **Safest approach:** use `event.cookies.set(name, value, { ... })` after parsing each
  Django `Set-Cookie` header. This handles `sessionid` and `csrftoken` separately. Executor
  must verify the SvelteKit version's cookie API supports this.

  Remove the `IS_PRODUCTION` import (was used for cookie `secure` flag in the old code; now
  the cookie security comes from Django's settings).

- [ ] **C-5** `apps/frontend/src/routes/logout/+server.ts` — replace the GET/POST handlers
  with a POST-only handler that calls Django logout. New logic:
  - `POST` handler only (remove `GET`).
  - Call `POST {DJANGO_URL}/api/auth/logout/` with:
    - `Cookie: <browser's Cookie header>` (forward session cookie)
    - `X-CSRFToken: <csrftoken cookie value from browser>` (extract from `event.cookies.get('csrftoken')`)
    - `Content-Type: application/json`
  - After the Django call, delete local cookies: `event.cookies.delete('sessionid', { path: '/' })` and
    `event.cookies.delete('csrftoken', { path: '/' })`.
  - Redirect to `/login`.
  - If Django logout fails (network error), still delete local cookies and redirect (logout
    should succeed locally even if the backend is unreachable).

- [ ] **C-6** `apps/frontend/src/routes/+layout.svelte` — update the logout link. The
  current `<a href="/logout">Logout</a>` issues a GET request. Since the new logout handler
  only accepts POST (step C-5), replace the link with a minimal inline form:
  ```svelte
  <form method="POST" action="/logout" style="display:inline">
    <button type="submit" class="text-sm text-muted hover:text-text">Logout</button>
  </form>
  ```
  Keep the same Tailwind classes on the button for visual consistency. The form submits to
  `/logout` via POST; SvelteKit routes this to the `POST` export in `logout/+server.ts`.
  Note: SvelteKit form actions POST with `Content-Type: application/x-www-form-urlencoded`
  by default and SvelteKit handles CSRF for its own form actions. The SvelteKit POST to
  `/logout` will then call Django's logout endpoint server-side (step C-5).

- [ ] **C-7** `apps/frontend/src/lib/api.ts` — add `credentials: 'include'` to the `get()`
  function (currently missing, present in `post()`, `postJson()`, `patch()`, `del()`). This
  ensures that when `get()` is called from `+page.server.ts` load functions (SSR context),
  the `sessionid` cookie is forwarded to Django so authenticated data loads correctly. The
  fix: add `credentials: 'include'` to the `fetchFn(...)` call inside `get()`. Verify that
  the SSR context for `fetchFn` (the SvelteKit-provided `fetch`) also forwards cookies when
  `credentials: 'include'` is set (it does in SvelteKit's SSR fetch implementation).

- [ ] **C-8** `apps/frontend/src/lib/session.ts` — delete this file after C-2 and C-4
  remove the two import sites. Confirm no other file in `apps/frontend/src/` imports from
  `$lib/session` before deleting.

  **Per-route load function guards:** the hooks gate in C-2 covers ALL routes (the
  `handle` function runs before any `+page.server.ts` load). Individual load functions
  do NOT need their own auth guards. This is the correct and sufficient architecture.
  Document this in a code comment in `hooks.server.ts`.

---

### Area D — Env, migrations, seeding, docs

*(Files: `apps/backend/.env.example`, `apps/frontend/.env.example`,
`docs/deployment/README.md`)*

- [ ] **D-1** `apps/backend/.env.example` — add the following variables in a new
  `# ── Auth / session ────────────────────────────────────────────────────────────` section
  near the top (after the Django section):
  ```
  # Axes brute-force lockout tunables (optional — defaults shown)
  # AXES_FAILURE_LIMIT=5
  # AXES_COOLOFF_HOURS=1
  # Session lifetime in seconds (default 8 hours = 28800)
  # SESSION_COOKIE_AGE_SECONDS=28800
  ```
  These are commented out because the defaults are sensible. Operators only need to set them
  to override the defaults.

- [ ] **D-2** `apps/frontend/.env.example` — remove the `DASHBOARD_PASSWORD` and
  `SESSION_SECRET` variables and their surrounding comment block (the `# ── Auth gate ...`
  section). These env vars are retired. No new frontend env vars are needed — the auth gate
  now validates against Django's `/api/auth/me/` endpoint using `DJANGO_API_URL` (already
  present). Update the comment on `ENVIRONMENT` to: `# "production" enables per-user auth
  (validates against Django session). Any other value runs in dev mode with no auth gate.`

- [ ] **D-3** Migration: executor must run:
  ```
  cd apps/backend
  python manage.py migrate axes
  ```
  This creates the `axes_accesslog` and `axes_accessfailurelog` tables. These tables are
  used by django-axes to record failed login attempts. No events-app migration is needed
  (no model changes in this plan).

- [ ] **D-4** User seeding: the plan does NOT create users automatically. Operators must
  create users manually after deploy using:
  ```
  cd apps/backend
  python manage.py createsuperuser
  ```
  Or for a non-staff operator account:
  ```
  python manage.py shell -c "from django.contrib.auth.models import User; User.objects.create_user('ops', '', 'securepassword')"
  ```
  Document both options. Staff users (`is_staff=True`, via `createsuperuser`) can also
  access the `/admin/` and `/review/` UIs. Regular users (`is_staff=False`) can only access
  the SvelteKit dashboard (the `/api/*` views use `@api_login_required` which only checks
  `is_authenticated`, not `is_staff`).

- [ ] **D-5** `docs/deployment/README.md` — add or update the following sections:
  - **Auth model (new section):** "The auth gate is now per-user. Django session auth
    (sessionid cookie) is used. The shared-password gate (`DASHBOARD_PASSWORD` +
    `SESSION_SECRET`) has been removed. Set up user accounts with `createsuperuser` before
    first deploy."
  - **User management:** document `createsuperuser` and the `create_user` shell command.
    Note staff vs. regular user distinction.
  - **Axes lockout:** "After 5 failed login attempts from the same username + IP, the
    account is locked for 1 hour. To unlock early: `python manage.py axes_reset --username <name>`
    or `python manage.py axes_reset_logs`."
  - **Belt-and-suspenders note:** "All `/api/*` endpoints now enforce session auth at
    the Django layer (JSON 401 for unauthenticated direct requests). Even if nginx or the
    SvelteKit proxy is misconfigured, a direct hit to Django:8000 is rejected."
  - **Remove:** the `DASHBOARD_PASSWORD` and `SESSION_SECRET` environment variable docs
    from the frontend env section.
  - **Update:** the §6.3 note about nginx routing to confirm `/api/` still goes to port 3000
    (SvelteKit), and that Django:8000 has its own auth layer too.

---

## Verification Evidence

> This is a high-risk area (auth flows, session handling, CSRF, brute-force protection).
> An evidence pack must be produced before calling the work production-ready.
> Save artifacts to: `process/general-plans/reports/per-user-auth-lockdown-harness/`

### Automated verification (run after implementation)

- [ ] **V-1** Backend test suite: `cd apps/backend && python manage.py test --verbosity=2`
  with `DEBUG=true` in env. All 197 tests must pass. Axes is disabled in debug mode (A-6),
  so no test failures from lockout side effects.
- [ ] **V-2** SvelteKit type check: `pnpm --filter frontend check`. Must produce zero errors.

### Manual verification (run in browser against running stack)

- [ ] **V-3** Unauthenticated SvelteKit access: visit `http://localhost:3000/` in production
  mode (`ENVIRONMENT=production`). Must redirect to `/login`. Repeat for `/events`,
  `/scrapers`. Must all redirect.
- [ ] **V-4** Unauthenticated direct Django access: `curl -s http://localhost:8000/api/events/`
  Must return `{"error": "authentication required"}` with HTTP 401. No redirect.
- [ ] **V-5** Login flow: submit correct username + password on `/login`. Must land on `/`
  (or `/tracker` per the production redirect). Browser must have `sessionid` and `csrftoken`
  cookies set (check DevTools → Application → Cookies).
- [ ] **V-6** Login with wrong password: submit wrong password. Must return to `/login?error=1`
  with error message. The failure count must be recorded in Django (check
  `python manage.py shell -c "from axes.models import AccessFailureLog; print(AccessFailureLog.objects.count())"`)
- [ ] **V-7** Axes lockout: attempt login 5 times with wrong password for the same username.
  The 6th attempt must return to `/login?error=locked` with the lockout message. Direct
  `curl -X POST http://localhost:8000/api/auth/login/ ...` with the same bad credentials
  must return HTTP 423.
- [ ] **V-8** Successful logout: click Logout. Must redirect to `/login`. Attempt to visit
  `/` — must redirect back to `/login`. The `sessionid` cookie must be gone (check DevTools).
- [ ] **V-9** Dev bypass: with `ENVIRONMENT=development`, visit `http://localhost:3000/`.
  Must not redirect to `/login`. Auth gate is fully skipped in dev.
- [ ] **V-10** Authed SPA mutations: when logged in, trigger a scraper run from the UI.
  Must succeed (HTTP 200). Verify `ScraperRun.triggered_by` is set: `python manage.py shell -c "from events.models import ScraperRun; r = ScraperRun.objects.latest('created_at'); print(r.triggered_by)"`
- [ ] **V-11** n8n webhook still works: `curl -X POST http://localhost:8000/webhooks/scrape/ -H "X-Scraper-Key: <key>" -d '{"source":"test"}'`. Must NOT return 401 (should return 400 "unknown source" if `test` is not a real scraper, which proves the auth layer is not blocking it).
- [ ] **V-12** `/review/` staff UI: visit `http://localhost:8000/review/` in a browser (direct Django access). Must redirect to Django admin login — not to SvelteKit's `/login`.

### Evidence pack artifacts
- `risk-gate.json` — risk class: HIGH (auth flow); evidence gathered Y/N
- `verification.json` — V-1 through V-12 results
- `adversarial-validation.json` — results of adversarial checks (see Security Context and Risks)

---

## Acceptance Criteria

1. An unauthenticated browser request to any protected SvelteKit route redirects to `/login`.
2. The `/login` page accepts `username` + `password`. Correct credentials log the user in
   and redirect to the app. Wrong credentials return to `/login?error=1`.
3. After 5 failed attempts (same username + IP), subsequent attempts return to
   `/login?error=locked`.
4. A direct `curl` to `http://localhost:8000/api/events/` (unauthenticated) returns
   JSON `{"error": "authentication required"}` with status 401.
5. n8n webhook endpoints (`/webhooks/scrape/`, `/webhooks/ingest-events/`) continue to
   accept `X-Scraper-Key` and are NOT blocked by the new auth layer.
6. The `/review/*` staff UI works via Django admin login, unchanged.
7. `pnpm --filter frontend check` passes with zero type errors.
8. `python manage.py test` passes all 197 tests with `DEBUG=true`.
9. Dev mode (`ENVIRONMENT != 'production'`) requires no login.
10. `ScraperRun.triggered_by` is populated for UI-triggered runs when logged in as a real user.
11. Logout clears the `sessionid` cookie and subsequent requests to protected routes redirect
    to `/login`.
12. The SPA's `api.ts` `get()` function includes `credentials:'include'` so SSR loads work
    with the Django session.

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| AxesMiddleware placement wrong (e.g. before `AuthenticationMiddleware`) → axes cannot check `request.user` | Medium | High — lockout may not work or may error | Strictly follow A-4 order; verify with V-7 |
| `CSRF_TRUSTED_ORIGINS` doesn't include the SvelteKit server's outbound origin → login POST rejected as CSRF failure | Medium | High — no one can log in | The server-side login call sends `X-CSRFToken` + `Cookie: csrftoken=...`; Django's middleware checks the header against the cookie value (double-submit pattern) without checking origin for the header check. Verify CSRF check passes in V-5. |
| `Set-Cookie` relay from Django to browser in `+page.server.ts` drops cookie flags (`HttpOnly`, `Secure`, `SameSite`) | Medium | Medium — cookies may be insecure in prod | Parse `Set-Cookie` header manually and re-apply `HttpOnly`, `Secure` (if `IS_PRODUCTION`), `SameSite: Lax` when calling `cookies.set()` |
| axes `is_already_locked()` helper import path differs across axes versions | Low | Medium — lockout detection broken | Check axes version installed; consult axes docs or source for exact import. Alternative: check HTTP status code from `authenticate()` wrapper if axes provides a hook. |
| Removing `@csrf_exempt` on existing views while axes is active breaks existing tests that POST without CSRF token | Low (tests use Django test client which handles CSRF) | Low | Django test client sets `enforce_csrf_checks=False` by default; existing test POSTs will still work. Verify in V-1. |
| `get()` in `api.ts` with `credentials:'include'` in SSR context doesn't forward cookies correctly | Low | Medium — data fails to load on page open | SvelteKit's `event.fetch` (the `f` arg) handles cookie forwarding in SSR; test with V-5 (page must load data after login) |
| Axes lockout parameters use IP from `REMOTE_ADDR` instead of `X-Forwarded-For` behind nginx → all users share the server IP and lock each other out | Medium | High — catastrophic in production | `AXES_IPWARE_META_PRECEDENCE_ORDER` setting (A-5) forces axes to read `HTTP_X_FORWARDED_FOR` first. Verify nginx sets this header. |
| Logout GET link in `+layout.svelte` breaks (form replaces link) — accessible users who tab-navigate may notice the change | Low | Low | Button in form is focusable and tab-navigable. Visual parity maintained via Tailwind classes. |
| Sessions created before this plan (the `sess` HMAC cookie) remain in browsers → they do no harm (the gate that checked them is removed) but may confuse browser DevTools | Low | None | `sess` cookies persist in browsers until expiry; they are ignored. No cleanup needed. |

---

## Resume and Execution Handoff

**Selected plan file:** `process/general-plans/active/per-user-auth-lockdown_PLAN_16-07-26.md`

**Execution order:** A → B → C → D. Do NOT start C until A's new endpoints exist and can be
called (C-2's `/me` check requires A-9d). Do NOT start the SvelteKit rework until the Django
login endpoint is verified to return a session cookie (manual test after A-9b is complete).

**Dependency gates:**
- A-1 through A-7 must all be complete before running the axes migration (A-11).
- A-8 and A-9 must be complete before B-1 can apply `@api_login_required` (the decorator doesn't exist yet).
- B-1 and B-2 can be done in any order relative to each other (they are separate decorator changes).
- C-1 (delete session.ts import) must come LAST in Area C, after C-2 and C-4 remove the
  import sites. Do C-2, C-3, C-4, C-5, C-6, C-7 first, then C-8.
- D-3 (migrate axes) must be run before starting the app in production; it's a one-time
  setup step the executor must note.

**On startup after implementation:**
1. `cd apps/backend && python manage.py migrate axes`
2. `cd apps/backend && python manage.py createsuperuser` (create at least one user)
3. Start Django: `gunicorn config.wsgi:application --bind 127.0.0.1:8000`
4. Start SvelteKit (with `ENVIRONMENT=production`): `node apps/frontend/build/index.js`
5. Run the V-1 through V-12 verification evidence steps.

**Rollback:** If the gate logic in hooks.server.ts is broken and users are locked out:
- Set `ENVIRONMENT=development` in the frontend env and restart SvelteKit. This disables
  the auth gate entirely and restores access.
- Alternatively, temporarily revert `hooks.server.ts` to the previous `sess`-cookie version
  (git checkout) and set `DASHBOARD_PASSWORD` + `SESSION_SECRET` in frontend env.

**Evidence pack destination:**
`process/general-plans/reports/per-user-auth-lockdown-harness/`
(Create this directory as part of the EXECUTE phase; populate with `risk-gate.json`,
`verification.json`, and `adversarial-validation.json` before calling the work production-ready.)

**Post-execute follow-up:**
- Rotate Django `SECRET_KEY` if not already done (from deploy-readiness follow-ups).
- Remove the operator note about `DASHBOARD_PASSWORD` / `SESSION_SECRET` from the nginx/ops
  runbook — these vars are retired.
- Consider `vc-code-reviewer` agent as a pre-PR quality gate for `views.py` decorator changes.

---

*Plan created: 2026-07-16. Ready for EXECUTE mode.*
