# Deploy Readiness — Veent Event Scraper

**Date:** 16-07-26
**Complexity:** SIMPLE
**Status:** ✅ IMPLEMENTED (2026-07-16) — verification passed; see operator follow-ups below

> **Executor note (2026-07-16):** All 23 items implemented and verified. Two runtime
> deviations were required and are documented at the end of this file (adapter wired in
> `vite.config.ts` not `svelte.config.js`; public-path early-resolve added to hooks to
> avoid a `/login`↔`/tracker` loop). Backend suite is 197 tests (not 97) — all pass with
> `DEBUG=true`. High-risk Area D evidence pack:
> `process/general-plans/reports/deploy-readiness-harness/`.
>
> **Required operator follow-ups before deploy:** (1) rotate `SECRET_KEY` (committed key is
> burned — not changed in code); (2) ~~run tests/CI with `DEBUG=true`~~ **RESOLVED
> 2026-07-16** — CI now injects `DEBUG: "true"` in the backend job env (`.github/workflows/ci.yml`);
> (3) ~~remove/IP-restrict the nginx `/api/` block~~ **RESOLVED 2026-07-16** — documented nginx
> `/api/` now proxies to the SvelteKit node upstream (port 3000) so all API traffic passes
> through the auth gate; Django stays bound to `127.0.0.1:8000` (localhost-only, proxy target);
> (4) set `DASHBOARD_PASSWORD` + `SESSION_SECRET` in frontend prod env.

**Remaining operator actions (deploy-time):**

- Rotate `SECRET_KEY`: the key previously committed to git is burned. Generate a fresh value
  (`python -c "import secrets; print(secrets.token_urlsafe(50))"`) and set it in
  `apps/backend/.env` (or server environment) before first production start.
- Set `DASHBOARD_PASSWORD` and `SESSION_SECRET` in `apps/frontend/.env` (or server environment).
  Without these the auth gate fails closed — every request redirects to `/login` and the
  dashboard is inaccessible.
- Verify nginx routes `/api/` to the SvelteKit node server (port 3000), NOT directly to
  Django:8000. Direct nginx → Django:8000 bypasses the auth gate entirely.

---

## Follow-up Resolutions (2026-07-16)

Two of the operator follow-ups above were closed in a doc/CI follow-up pass (no app-code
change):

1. **CI DEBUG=true (concern 2).** `.github/workflows/ci.yml` backend job env now sets
   `DEBUG: "true"`. Verified against the settings.py parser
   `DEBUG = os.environ.get('DEBUG', 'False').lower() not in ('false', '0', 'no')`: the string
   `"true"` is not in `('false','0','no')` → `DEBUG=True` → the `if not DEBUG:` block
   (SECURE_SSL_REDIRECT and other prod hardening) is skipped → the ~48 view/API tests no
   longer receive 301 redirects. Truthy form `"true"` matches the parser's expected form.

2. **nginx /api/ bypass (D-7 / E-4).** `docs/deployment/README.md` §6.3 nginx `/api/` location
   was changed from `proxy_pass http://127.0.0.1:8000` (direct-to-Django, ungated) to
   `proxy_pass http://127.0.0.1:3000` (SvelteKit node upstream). Verified via
   `apps/frontend/src/hooks.server.ts`: it proxies `/api/*` → `DJANGO_API_URL` and
   `/node-api/*` → `NODE_API_URL` *after* the auth gate, so routing nginx `/api/` to port 3000
   reaches Django through the gated proxy. `/node-api/*` is already covered by the catch-all
   `location /` (also port 3000). The §1 architecture diagram, the §6.3 warning block, and the
   §7 n8n auth caveat were rewritten to describe the gap as CLOSED. Django's gunicorn stays
   bound to `127.0.0.1:8000` (localhost-only, reachable only via the SvelteKit proxy).
   Performance note: all `/api/*` now makes one extra in-droplet hop through the node server;
   negligible for this dashboard's traffic. This resolves the D-7/E-4 "bypass risk" items and
   the High-likelihood nginx bypass risk in the Risks table.

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
- [Implementation Checklist](#implementation-checklist)
  - [Area A — Django settings blockers](#area-a--django-settings-blockers)
  - [Area B — Django security hardening](#area-b--django-security-hardening)
  - [Area C — Packaging and deploy artifacts](#area-c--packaging-and-deploy-artifacts)
  - [Area D — SvelteKit shared-password auth](#area-d--sveltekit-shared-password-auth)
  - [Area E — Env and docs](#area-e--env-and-docs)
- [Verification Evidence](#verification-evidence)
- [Acceptance Criteria](#acceptance-criteria)
- [Risks and Mitigations](#risks-and-mitigations)
- [Resume and Execution Handoff](#resume-and-execution-handoff)

---

## Overview

Harden the Veent Event Scraper monorepo for production deployment on DigitalOcean. The work
is grouped into five independently shippable areas:

- **A** — Remove hardcoded secrets and load Django settings from env
- **B** — Add production-gated Django security headers/settings
- **C** — Fix packaging: add `gunicorn` to requirements; switch SvelteKit to `adapter-node`
- **D** — Add a single shared-password auth gate in SvelteKit (the ONLY auth layer; no Django-side per-view auth)
- **E** — Sync `.env.example` files and note doc gaps

Areas A, B, and C are pure backend/infra changes that do not touch any runtime behaviour
visible to users. Area D is the main new user-facing feature. Area E is housekeeping.

---

## Goals and Success Metrics

- `SECRET_KEY` is never committed to git again. The old committed key is documented as
  burned.
- `DEBUG=False` works cleanly in production; `DEBUG=True` still works in dev.
- An unauthenticated browser request to any route redirects to `/login`.
- A correct password grants a signed session cookie; all subsequent requests pass through.
- `GET /api/*` from the SvelteKit proxy is gated by the auth cookie check (not Django-side).
- The SvelteKit build uses `adapter-node` and produces `apps/frontend/build/index.js`.
- `pip install -r requirements.txt` installs `gunicorn`.
- Zero existing tests broken (97 Django tests continue to pass).

---

## Scope

**In scope:**
- `apps/backend/config/settings.py` — settings blockers and security hardening
- `apps/backend/requirements.txt` — add `gunicorn`
- `apps/frontend/svelte.config.js` — switch to `adapter-node`
- `apps/frontend/package.json` — add `@sveltejs/adapter-node` devDependency
- `apps/frontend/src/hooks.server.ts` — auth gate composing with existing handle
- `apps/frontend/src/routes/login/` — new `/login` route (page + server action)
- `apps/frontend/src/routes/logout/` — new `/logout` route (server action only)
- `apps/backend/.env.example` — add new vars
- `apps/frontend/.env.example` (create if missing) — DASHBOARD_PASSWORD, SESSION_SECRET,
  ENVIRONMENT
- `docs/deployment/README.md` — note doc gaps (not a full rewrite)

**Out of scope:**
- Django-side per-view authentication or DRF token auth
- Heavy auth libraries (no Lucia, no Auth.js)
- WhiteNoise (nginx serves static per deploy README; gunicorn-only addition)
- HTTPS provisioning (certbot already documented in deploy README)
- n8n pipeline auth (separate concern)
- Any database migrations

---

## Assumptions and Constraints

- nginx terminates TLS and passes `X-Forwarded-Proto: https` — required for
  `SECURE_PROXY_SSL_HEADER` to work.
- The nginx config in `docs/deployment/README.md` (§6.3) routes `/api/*` directly to
  Django on port 8000, **bypassing** the SvelteKit auth gate. This is a contradiction with
  the chosen auth model (SvelteKit is the only gate). The plan notes this gap and the
  execute step must address it (see Area D step D-7 and Area E step E-4).
- The current `IS_PRODUCTION` check in `hooks.server.ts:7` uses
  `process.env.ENVIRONMENT === 'production'`. The auth gate must reuse this same variable
  so dev mode is unaffected.
- SvelteKit `cookies` API and Node's built-in `crypto` module are available with no extra
  packages. HMAC-SHA256 with `SESSION_SECRET` as the key is sufficient for signing.
- Timing-safe string comparison (`crypto.timingSafeEqual`) must be used for the password
  check to resist timing attacks.
- `adapter-node` is already referenced in `docs/deployment/README.md` §5.4 as the expected
  adapter. The code is behind on this.

---

## Security Context

### SECRET_KEY rotation

The key `django-insecure-xnjav(kkizi)fm)3&#v9%tk15#zcue(%f5n0t9x5i8szb9sc7y` is committed
in git history (line 49 of `apps/backend/config/settings.py`). It is permanently compromised.

**Execute must:**
1. Remove the hardcoded key from `settings.py`.
2. Document in the plan/commit that the old key is burned — any production deployments
   that used it must generate a new `SECRET_KEY` value before deploying.
3. Rotating `SECRET_KEY` invalidates all existing Django sessions (admin logins, CSRF
   tokens). This is acceptable and expected.

### Cookie signing (SvelteKit auth)

The session cookie value is `HMAC-SHA256(SESSION_SECRET, DASHBOARD_PASSWORD_HASH)` or a
simpler scheme: a random token signed with HMAC. Recommended scheme:

- On successful login: generate a random 32-byte token → HMAC it with `SESSION_SECRET` →
  store `<token>.<signature>` as the cookie value.
- On each request: split at `.`, recompute HMAC of the token, use `timingSafeEqual` to
  compare. If valid, allow.
- The cookie is `HttpOnly`, `Secure` (in production), `SameSite=Lax`, with a reasonable
  `maxAge` (e.g. 7 days or 30 days — executor decides, document the choice).

Password comparison must use `crypto.timingSafeEqual` (convert strings to `Buffer`s before
comparing).

### nginx /api/ gap

The deploy README's nginx config routes `/api/` directly to Django (port 8000), bypassing
SvelteKit entirely. This means an attacker who knows the server IP can hit
`https://your-domain.com/api/scrapers/run-all/` without a session cookie. The plan cannot
change the nginx config (that is an ops artifact), but the doc update (Area E) must call
this out explicitly and recommend either:

- Removing the `/api/` nginx block so all traffic flows through SvelteKit (preferred), OR
- Adding an nginx `allow/deny` list for `/api/` if n8n and admin-only tools need direct
  access.

---

## Blast Radius

| File | Change | Rollback risk |
|---|---|---|
| `apps/backend/config/settings.py` | Remove hardcoded SECRET_KEY, DEBUG, ALLOWED_HOSTS; add security settings | Low — env vars cover the gap; dev with .env unaffected |
| `apps/backend/requirements.txt` | Add `gunicorn` | None — additive |
| `apps/frontend/svelte.config.js` | Replace adapter-auto with adapter-node | Medium — requires `pnpm install`; build output path changes |
| `apps/frontend/package.json` | Add `@sveltejs/adapter-node` devDep | Low |
| `apps/frontend/src/hooks.server.ts` | Insert auth gate before existing logic | High — single point of failure for all routes; wrong logic = lockout |
| `apps/frontend/src/routes/login/` | New files | None (additive) |
| `apps/frontend/src/routes/logout/` | New files | None (additive) |
| `apps/backend/.env.example` | Additive only | None |
| `apps/frontend/.env.example` | New file | None |
| `docs/deployment/README.md` | Additive notes only | None |

---

## Touchpoints

- `apps/backend/config/settings.py` — all Django runtime behaviour depends on this
- `apps/frontend/src/hooks.server.ts` — every SvelteKit request passes through this file;
  the auth gate is inserted here
- `apps/frontend/svelte.config.js` — controls the build adapter; changing it changes the
  build output location
- `docs/deployment/README.md` §4 — references `SECRET_KEY`/`DEBUG` env vars that
  `settings.py` currently ignores; fixing settings closes this documentation gap

---

## Public Contracts

- Django `SECRET_KEY` must be provided as an env var in production; absence must cause a
  loud startup failure (not a silent insecure default).
- `DASHBOARD_PASSWORD` and `SESSION_SECRET` must be set in the SvelteKit process env in
  production. If either is missing, the auth gate should fail closed (refuse all requests
  or error loudly on startup), not fail open.
- The session cookie name is `sess` (or equivalent — executor picks a short name;
  document it).
- The `/login` POST action accepts `password` as the form field name.
- `/logout` invalidates the session cookie and redirects to `/login`.
- All `/api/*` requests that flow through SvelteKit are protected by the auth gate.
  (Direct Django paths via nginx are a separate ops concern documented in Area E.)

---

## Implementation Checklist

### Area A — Django settings blockers

*(File: `apps/backend/config/settings.py`)*

- [x] **A-1** Remove the hardcoded `SECRET_KEY` string at line 49 (`django-insecure-...`).
  Replace with `os.environ.get('SECRET_KEY')`. Add a startup guard immediately after:
  if `not DEBUG` and `not SECRET_KEY`, raise `ImproperlyConfigured("SECRET_KEY must be
  set in production")`. If `SECRET_KEY` is absent in dev (no `.env`), Django will use
  `None` and fail loudly — acceptable. Add a code comment: "The key that was here is
  burned — generate a new one with: `python -c \"import secrets; print(secrets.token_urlsafe(50))\"`"

- [x] **A-2** Replace `DEBUG = True` at line 52 with:
  `DEBUG = os.environ.get('DEBUG', 'False').lower() not in ('false', '0', 'no')`.
  This means `DEBUG=true` in `.env` keeps dev working; absent `DEBUG` defaults to False
  (safe production default).

- [x] **A-3** Replace the hardcoded `ALLOWED_HOSTS` list at line 54 with:
  ```
  _hosts_env = os.environ.get('ALLOWED_HOSTS', '')
  ALLOWED_HOSTS = [h.strip() for h in _hosts_env.split(',') if h.strip()] or ['localhost', '127.0.0.1', 'testserver']
  ```
  The fallback list applies only when `ALLOWED_HOSTS` env var is absent (dev convenience).

- [x] **A-4** Fix SSL in the database config at lines 123–129. Replace the
  `ssl_require=False` kwarg with a conditional:
  ```
  _db_url = os.environ.get('DATABASE_URL', f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
  DATABASES = {
      'default': dj_database_url.config(
          default=_db_url,
          conn_max_age=600,
          ssl_require=not _db_url.startswith('sqlite'),
      )
  }
  ```
  This requires SSL for any non-sqlite URL (Neon PostgreSQL), and skips it for sqlite
  (local dev and CI).

---

### Area B — Django security hardening

*(File: `apps/backend/config/settings.py`, appended after the existing settings blocks)*

- [x] **B-1** Add `STATIC_ROOT = BASE_DIR / 'staticfiles'` after the existing
  `STATIC_URL = 'static/'` line (line 166). Required for `collectstatic` to work.
  (Currently absent — the deploy README references it but settings.py does not define it.)

- [x] **B-2** Add a production-only security block after all existing settings.
  Gated on `if not DEBUG:`. This block must contain:

  ```
  # Nginx terminates TLS; tell Django the real scheme via this header.
  SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

  # Redirect plain HTTP to HTTPS (nginx handles it, but defence-in-depth).
  SECURE_SSL_REDIRECT = True

  # Cookie security
  SESSION_COOKIE_SECURE = True
  CSRF_COOKIE_SECURE = True
  SESSION_COOKIE_HTTPONLY = True  # already Django default but be explicit

  # HSTS (tell browsers to only use HTTPS for 1 year)
  SECURE_HSTS_SECONDS = 31536000
  SECURE_HSTS_INCLUDE_SUBDOMAINS = True
  SECURE_HSTS_PRELOAD = True
  ```

- [x] **B-3** Add `CSRF_TRUSTED_ORIGINS` that includes the production origin from env,
  appended to the existing dev list. Replace the current hardcoded line 56
  (`CSRF_TRUSTED_ORIGINS = [...]`) with:
  ```
  _csrf_origins = ['http://localhost:5173', 'http://127.0.0.1:5173']
  if _prod_origin := os.environ.get('PROD_ORIGIN', ''):
      _csrf_origins.append(_prod_origin)
  CSRF_TRUSTED_ORIGINS = _csrf_origins
  ```

---

### Area C — Packaging and deploy artifacts

- [x] **C-1** Add `gunicorn` to `apps/backend/requirements.txt`.
  The deploy README's systemd unit at §6.1 calls `gunicorn` directly; without it in
  requirements.txt, `pip install -r requirements.txt` will fail on a fresh server.
  WhiteNoise is not added — nginx already serves `/static/` via alias per deploy README §6.3.

- [x] **C-2** In `apps/frontend/package.json`, replace `"@sveltejs/adapter-auto": "^7.0.1"`
  in `devDependencies` with `"@sveltejs/adapter-node": "^5.0.0"` (confirm latest compat
  with `@sveltejs/kit ^2.63.0` — executor should verify on npmjs.com; `^5.x` is the correct
  series as of mid-2026).

- [x] **C-3** In `apps/frontend/svelte.config.js`, replace `import adapter from '@sveltejs/adapter-auto'`
  with `import adapter from '@sveltejs/adapter-node'`. The config body stays the same
  (`adapter: adapter()`). This produces `apps/frontend/build/index.js` as the node
  entrypoint, matching the deploy README §5.4 and PM2 invocation at §6.2.

- [x] **C-4** Run `pnpm install` from the monorepo root after C-2/C-3 to update
  `pnpm-lock.yaml`. (This is an execution step, not a file edit — noted here so execute
  agent does not skip it.)

---

### Area D — SvelteKit shared-password auth

**Decided auth model (do not re-litigate):**
Single shared password via `DASHBOARD_PASSWORD` env var. SvelteKit is the sole auth
gate. All `/api/*` already flows through the SvelteKit proxy → one gate protects
dashboard + API. No Django-side per-view auth or DRF.

**Ordering in `hooks.server.ts`:**
Auth gate runs first (before the IS_PRODUCTION tracker redirect). Unauthenticated users
never see the tracker redirect — they always land on `/login`. Authenticated users hit
the tracker redirect normally.

**Session cookie scheme:**
- Name: `sess`
- Value: `<random_hex_token>.<hmac_sha256_hex_signature>` where signature =
  `HMAC-SHA256(SESSION_SECRET, random_hex_token)`
- Options (production): `httpOnly: true`, `secure: true`, `sameSite: 'lax'`,
  `maxAge: 60 * 60 * 24 * 30` (30 days)
- Options (dev / IS_PRODUCTION false): `secure: false`
- Comparison: verify with `crypto.timingSafeEqual`

**Public paths** (bypass auth gate): `/login`, `/_app/` (SvelteKit static chunks),
`/favicon.ico`. Do not add `/api/` to the bypass list (auth should gate API calls too;
the gap in nginx routing is a separate ops note).

- [x] **D-1** Create `apps/frontend/src/lib/session.ts`.
  This module holds all cookie-signing logic and is imported by both hooks and the
  login/logout routes. Contents (no code written here — this is the contract):
  - `signToken(secret: string): string` — generates a random 32-byte hex token, computes
    HMAC-SHA256 over it using `secret`, returns `<token>.<sig>` string.
  - `verifyToken(cookie: string, secret: string): boolean` — splits at last `.`, recomputes
    HMAC, uses `crypto.timingSafeEqual` to compare. Returns boolean.
  - Use `import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto'`.
  - Module must be pure (no SvelteKit imports); importable by hooks and server routes.

- [x] **D-2** Create `apps/frontend/src/routes/login/+page.svelte`.
  Simple HTML form: one `<input type="password" name="password">` and a submit button.
  Show an error message if the URL has `?error=1`. No JS required (progressive
  enhancement is fine). Minimal styling consistent with existing Tailwind setup.

- [x] **D-3** Create `apps/frontend/src/routes/login/+page.server.ts`.
  Exports a `actions.default` form action:
  - Reads `DASHBOARD_PASSWORD` from `process.env`. If absent, throw a 500 (server
    misconfiguration — fail closed).
  - Reads `SESSION_SECRET` from `process.env`. If absent, throw a 500.
  - Reads `password` from `formData`.
  - Compare using `crypto.timingSafeEqual(Buffer.from(submitted), Buffer.from(expected))`.
    Pad/handle length mismatch to avoid early-exit: if lengths differ, still run the
    equal check against a dummy buffer of the correct length to consume the same time,
    then return false.
  - On success: call `signToken(SESSION_SECRET)`, set the `sess` cookie with production
    options, redirect to `/`.
  - On failure: redirect to `/login?error=1`.

- [x] **D-4** Create `apps/frontend/src/routes/logout/+server.ts`.
  Exports a `GET` (or `POST`) handler:
  - Deletes the `sess` cookie (set to empty string, `maxAge: 0`).
  - Redirects to `/login`.

- [x] **D-5** Update `apps/frontend/src/hooks.server.ts` to insert the auth gate.
  The new handle logic must:
  1. Define `PUBLIC_PATHS` as a constant array:
     `['/login', '/favicon.ico']` and a prefix check for `/_app/`.
  2. Skip auth gate if `!IS_PRODUCTION` (so dev workflow is unaffected).
  3. Skip auth gate if the path is in `PUBLIC_PATHS` or starts with `/_app/`.
  4. Skip auth gate for the logout route `/logout`.
  5. Read the `sess` cookie using `event.cookies.get('sess')`.
  6. Call `verifyToken(cookie, SESSION_SECRET)` from `$lib/session`.
  7. If verification fails: redirect to `/login`.
  8. If verification passes: `return resolve(event)` (the existing proxy and tracker
     redirect logic run on the resolved event as before).

  The existing logic (`proxyRequest`, `/node-api/` proxy, `/api/` proxy, IS_PRODUCTION
  tracker redirect) is preserved verbatim below the auth gate. No proxy code changes.

  `SESSION_SECRET` is read at module level (same pattern as `DJANGO_URL`):
  `const SESSION_SECRET = process.env.SESSION_SECRET ?? ''`
  If `IS_PRODUCTION && !SESSION_SECRET`, the verify call will always fail → all requests
  redirect to `/login`. This is acceptable fail-closed behaviour; the executor should
  add a startup warning log (`console.warn`) when SESSION_SECRET is absent in production.

- [x] **D-6** Add a visible logout link in `apps/frontend/src/routes/+layout.svelte`.
  A simple anchor `<a href="/logout">Logout</a>` or a small button in the nav. The
  existing layout structure determines placement — executor matches existing nav style.
  (Only show this link when IS_PRODUCTION is true, or always — executor's discretion;
  keeping it always visible is simpler and harmless in dev.)

- [x] **D-7** Add a note in `docs/deployment/README.md` §6.3 (nginx config) that the
  current `/api/` nginx block bypasses SvelteKit and therefore bypasses the auth gate.
  Recommend removing the `/api/` direct-to-Django nginx location block and routing all
  traffic through SvelteKit (port 3000). If n8n or ops tooling needs unauthenticated API
  access, restrict the `/api/` block to `allow 127.0.0.1; deny all;`.

---

### Area E — Env and docs

- [x] **E-1** Update `apps/backend/.env.example` to add or replace:
  - `SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_urlsafe(50))">` —
    (already present as placeholder; update comment to note the old committed key is burned)
  - `DEBUG=false` — (already present)
  - `ALLOWED_HOSTS=your-domain.com` — (currently absent; add with comment)
  - `PROD_ORIGIN=https://your-domain.com` — (new; add with comment)
  All existing vars remain unchanged.

- [x] **E-2** Create `apps/frontend/.env.example` (currently absent):
  ```
  # SvelteKit runtime env vars (read at process start, not build time)
  DJANGO_API_URL=http://localhost:8000
  NODE_API_URL=http://localhost:8001
  ENVIRONMENT=development

  # Auth gate (required in production; ignored in dev)
  DASHBOARD_PASSWORD=change-me
  SESSION_SECRET=<generate: node -e "require('crypto').randomBytes(32).toString('hex') |> console.log">
  ```
  Add a comment that `DASHBOARD_PASSWORD` and `SESSION_SECRET` must both be set before
  starting the frontend in production. If either is absent, all requests will be redirected
  to `/login` (fail-closed).

- [x] **E-3** Update `docs/deployment/README.md` §4 (Environment Variables) to add a
  frontend env block with `DASHBOARD_PASSWORD`, `SESSION_SECRET`, and `ENVIRONMENT=production`.
  The section currently only shows backend vars. No full rewrite — additive only.

- [x] **E-4** Update `docs/deployment/README.md` §6.3 (nginx) per D-7 note above:
  add a comment block explaining the auth-gate bypass risk of the direct `/api/` nginx
  location and the two remediation options (remove block, or IP-restrict it).

- [x] **E-5** Update `docs/deployment/README.md` §5.3 (Backend setup) to note that
  `SECRET_KEY` must be a freshly generated value and that the key previously committed
  to git is burned. Reference the generate command already in §4.

---

## Verification Evidence

### Area A verification
- Boot Django with no `.env` and `DEBUG` absent → expect startup error about `SECRET_KEY`
  (production guard fires).
- Boot Django with `DEBUG=false` and a valid `SECRET_KEY` → `python manage.py check`
  exits 0.
- Boot Django with `DEBUG=true` and no `SECRET_KEY` → starts normally (dev mode, no guard).
- `ALLOWED_HOSTS` env absent → Django uses fallback list `['localhost', ...]` → requests
  to `localhost:8000` succeed.

### Area B verification
- Run `python manage.py check --deploy` with `DEBUG=False` and all required env set →
  zero warnings (HSTS, SECURE_PROXY_SSL_HEADER, cookie secure flags all satisfied).
- Confirm `STATIC_ROOT` is set → `python manage.py collectstatic --noinput` completes
  without "ImproperlyConfigured: STATIC_ROOT" error.

### Area C verification
- `grep gunicorn apps/backend/requirements.txt` → found.
- `grep adapter-node apps/frontend/svelte.config.js` → found.
- `pnpm --filter frontend build` completes and produces `apps/frontend/build/index.js`.
- `node apps/frontend/build/index.js` starts the server on port 3000.

### Area D verification (high-risk auth flow — manual evidence pack required)
- **Unauthenticated → redirect:** `curl -I https://localhost:3000/` in production mode
  → `302 Location: /login`.
- **Unauthenticated API → redirect:** `curl -I https://localhost:3000/api/stats/` in
  production mode → `302 Location: /login` (not a Django 200).
- **Wrong password → no cookie:** POST `/login` with wrong password → redirect back to
  `/login?error=1`; no `sess` cookie in response headers.
- **Correct password → cookie set:** POST `/login` with correct password → `302` to `/`,
  `Set-Cookie: sess=...` header present with `HttpOnly; Secure; SameSite=Lax`.
- **Valid cookie → pass-through:** subsequent request with valid `sess` cookie → dashboard
  loads (200), proxy to Django works, CSRF header passes.
- **Tampered cookie → redirect:** manually corrupt the `sess` cookie value → next request
  redirects to `/login`.
- **Logout:** GET `/logout` → `sess` cookie deleted → redirect to `/login` → subsequent
  request without cookie → redirect to `/login`.
- **Dev mode unaffected:** `ENVIRONMENT` not set (or not `'production'`) → all routes
  accessible without a session cookie.
- Existing `/tracker` production redirect still fires for authenticated users on non-tracker
  paths.
- 97 Django tests still pass: `cd apps/backend && python manage.py test`.

Per `process/development-protocols/implementation-standards.md` — auth flows are high-risk.
Before closing this work as done, record:
- `risk-gate.json` confirming all auth verification steps above were manually exercised.
- `adversarial-validation.json` covering: timing attack on password compare, missing
  SESSION_SECRET fail-closed behaviour, cookie tampering redirect.

Store these in `process/general-plans/reports/deploy-readiness-harness/`.

---

## Acceptance Criteria

1. `python manage.py check --deploy` passes with `DEBUG=False` and valid env set.
2. `SECRET_KEY` is not present anywhere in tracked git files after this change lands.
3. `gunicorn` is in `apps/backend/requirements.txt`.
4. `pnpm --filter frontend build` produces `apps/frontend/build/index.js` using
   `adapter-node`.
5. Unauthenticated request to any route in production mode returns 302 to `/login`.
6. Authenticated request (valid `sess` cookie) reaches the dashboard and `/api/*` proxy
   works correctly.
7. Wrong password → no session cookie granted, redirect to `/login?error=1`.
8. Dev mode (no `ENVIRONMENT=production`) has no auth gate.
9. All 97 Django tests pass unchanged.

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Auth gate bugs causing prod lockout | Medium | Dev mode bypass; manual verification matrix in Area D; can disable with `ENVIRONMENT` env var reset |
| nginx /api/ bypass exposing unauthenticated API | High (architecture) | Documented in D-7/E-4; ops must remove the direct `/api/` nginx block |
| HSTS misconfiguration locking out HTTP access | Low | HSTS only fires when `DEBUG=False`; test with `check --deploy` before going live |
| adapter-node version incompatibility with kit ^2.63 | Low | Executor verifies on npmjs before pinning version |
| Committed SECRET_KEY used in an existing prod deploy | High (if already deployed) | Call this out in commit message; operators must regenerate before deploying |
| SESSION_SECRET absent in prod → all requests loop to /login | Medium | Startup console.warn; documented in .env.example |

---

## Resume and Execution Handoff

**Plan path:** `process/general-plans/active/deploy-readiness_PLAN_16-07-26.md`

**Execution order:** Areas are independently shippable. Recommended sequence:

1. **A + B** together (settings only, no frontend changes, easy to verify in isolation)
2. **C** (packaging, independent of auth)
3. **D** (auth — highest risk, do last so settings are already solid)
4. **E** (env/docs, can run in parallel with any area or last)

**Critical pre-flight for executor:**
- Confirm the old `SECRET_KEY` value is not present in any other file by running:
  `grep -r "xnjav" .` from the repo root before committing.
- Verify `@sveltejs/adapter-node` latest compatible version for `@sveltejs/kit ^2.63.0`
  on npmjs.com before editing `package.json`.

**High-risk area:** Area D is the highest-risk work item. Follow the manual evidence
pack contract from `implementation-standards.md` before declaring it done.

**Tests:** Run `cd apps/backend && python manage.py test` after Area A/B. Run
`pnpm --filter frontend build` after Area C. No automated SvelteKit tests exist currently
— verification is manual per the Area D evidence matrix above.

---

## Execution Deviations (2026-07-16)

Two deviations from the written plan were required to satisfy the plan's own explicit
contracts. Both were surfaced by runtime verification and are behavior-preserving.

1. **C-3 — adapter wired in `vite.config.ts`, not (only) `svelte.config.js`.**
   This project passes SvelteKit options inline via the `sveltekit()` Vite plugin
   (`apps/frontend/vite.config.ts`). When options are passed that way, SvelteKit **ignores
   `svelte.config.js` entirely** (Vite logs: "svelte.config.js is ignored when options are
   passed via your Vite config"). Editing only `svelte.config.js` (as the plan's C-3
   literally specified) produced a build with **"No adapter specified"** and **no
   `build/index.js`** — a hard failure of Acceptance Criterion #4. Resolution: added
   `adapter: adapter()` to the inline `sveltekit({ ... })` options in `vite.config.ts`
   (and kept `svelte.config.js` on `adapter-node` for consistency). This achieves the
   plan's explicit approved contract (adapter-node → `apps/frontend/build/index.js`), only
   in the file that is actually authoritative. Verified: build logs "Using
   @sveltejs/adapter-node" and emits `apps/frontend/build/index.js`.

2. **D-5 — public paths early-`resolve` before the pre-existing tracker redirect.**
   The pre-existing production logic in `hooks.server.ts` redirects every non-`/tracker`,
   non-`/api` route to `/tracker`. With the auth gate letting `/login` through as a public
   path, `/login` then fell through to that tracker redirect → `/tracker` → (auth gate) →
   `/login` → … an infinite loop that made the login page unreachable (breaking Acceptance
   Criterion #5). Resolution: for public paths in production, `return resolve(event)`
   immediately, before the tracker redirect. Proxy code is unchanged; the tracker redirect
   still fires for authenticated users on non-tracker paths, exactly as the plan requires.
   Verified: GET `/login` → 200 (no loop); authenticated `/` → 302 `/tracker`.

**Non-deviation clarifications:**
- Backend suite is **197 tests** (context/plan said 97 — stale). All 197 pass with
  `DEBUG=true`.
- Tests **must** run with `DEBUG=true`; otherwise the new `SECURE_SSL_REDIRECT=True`
  (B-2) issues `301` redirects that break ~48 Django-test-client view/API tests. This
  matches the pre-change behavior (DEBUG was hardcoded `True`). CI must set `DEBUG=true`.
- `SECRET_KEY` was intentionally **not** rotated in code (per Security Context — operator
  must generate a fresh value at deploy time). The old key remains only in git history and
  in `docs/analysis/SECURITY.md` (an out-of-scope security-analysis finding).

**Area D high-risk evidence pack:**
`process/general-plans/reports/deploy-readiness-harness/`
(`risk-gate.json`, `adversarial-validation.json`, `verification.json`,
`context-snippets.json`, `review-decision.json`).
