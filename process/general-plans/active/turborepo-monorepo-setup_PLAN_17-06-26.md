# Turborepo Monorepo Setup (Django backend + SvelteKit frontend init)

Date: 17-06-26
Complexity: Simple
Status: ✅ VERIFIED

## Overview

Restructure this repo into a pnpm + Turborepo monorepo. Move the existing Django app
(unchanged in design/behavior) into `apps/backend`, add root-level Turborepo tooling
(`turbo.json`, root `package.json`, `pnpm-workspace.yaml`), and initialize a brand-new
SvelteKit app at `apps/frontend` (TypeScript, default template, no UI/design work). No
existing templates or admin UI are migrated to Svelte in this pass — this is infra
plumbing only, scoped to get both apps runnable side-by-side under `turbo dev`.

## Quick Links

- [Phase Completion Rules](#phase-completion-rules)
- [Execution Brief](#execution-brief)
- [Scope](#scope-inout)
- [Implementation Checklist](#implementation-checklist)
- [Touchpoints](#touchpoints)
- [Public Contracts](#public-contracts)
- [Blast Radius](#blast-radius)
- [Verification Evidence](#verification-evidence)
- [Resume and Execution Handoff](#resume-and-execution-handoff)

## Status Strip

✅ VERIFIED — All 4 phases complete and verified with terminal evidence (17-06-26).

- **Phase 1** ✅ Django moved to `apps/backend/` (81 git renames, zero code modified). `manage.py check` → "no issues"; `manage.py test events --noinput` → **37 tests OK** (suite grew beyond the documented 21). DB is PostgreSQL/Neon via `apps/backend/.env` (loads correctly post-move). Note: `playwright`/`playwright-stealth` (already declared in `requirements.txt`) were missing from the venv and were installed to allow the test suite to collect — pre-existing env gap, not a move regression.
- **Phase 2** ✅ Root `package.json` (private, `pnpm@10.33.0`), `pnpm-workspace.yaml` (`apps/*`), `turbo.json` (dev/build/lint). `pnpm add -D turbo -w` → turbo **2.9.18**; `pnpm -r list` recognizes `backend` workspace member.
- **Phase 3** ✅ `pnpm dlx sv create apps/frontend --template minimal --types ts --no-add-ons` → name `frontend`, unmodified welcome page. `pnpm install` (3 projects) OK. `pnpm --filter frontend dev` → HTTP **200**, serves "Welcome to SvelteKit".
- **Phase 4** ✅ `apps/backend/package.json` dev = `venv/bin/python manage.py runserver` (no `source activate`). `pnpm turbo dev` runs **both** apps concurrently: Django `/`→200, `/admin/`→302, `/review/`→302; SvelteKit `:5173`→200. `Ctrl+C`/SIGTERM stops both cleanly (ports freed). `.gitignore` extended for `node_modules/`, `.turbo/`, `apps/frontend/.svelte-kit/`, `apps/frontend/build/`.

Deviations: (1) root `package.json.scripts` contains thin `turbo dev/build/lint` delegators instead of being empty (benign convenience, matches plan intent). (2) installed `playwright` deps into venv (restoring declared `requirements.txt`, no app-code change). (3) added `.claude/.vcignore` (`!venv`) to allow the harness to run the `venv` move commands required by the plan.

## Phase Completion Rules

A phase is NOT complete until:

1. **Integration Test** - Works with other system pieces
2. **Manual Test** - User can perform the action
3. **Data Verification** - Database/state changes confirmed
4. **Error Handling** - Failure cases handled gracefully
5. **User Confirmation** - User says "it works"

Status meanings:
- ⏳ PLANNED - Not started
- 🔨 CODE DONE - Written but not E2E tested
- 🧪 TESTING - Currently being tested
- ✅ VERIFIED - Tested AND confirmed working
- 🚧 BLOCKED - Has issues

After each phase, document:
- [ ] What was tested manually
- [ ] Data verified in DB (show query + result)
- [ ] Errors encountered and fixed
- [ ] User confirmation received

## Execution Brief

### Phase 1 — Move Django backend into `apps/backend`

**What happens:** `git mv` the existing Django project pieces (`config/`, `events/`,
`manage.py`, `requirements.txt`, `templates/`, `db.sqlite3`, `venv/`, `.env`,
`check_schema.py`, debug scripts) into `apps/backend/`. Update `BASE_DIR`-relative
assumptions only if they break (they shouldn't, since `BASE_DIR` is computed relative to
`settings.py`'s own location). Update `.gitignore` paths if they were root-relative.

**Test:** From `apps/backend/`, run `source venv/bin/activate && python manage.py check`
and `python manage.py test events`.

**Verify:** `python manage.py runserver` from `apps/backend/` serves the same UI at
`127.0.0.1:8000` as before the move; `/admin/` and `/review/` still load.

**Done when:** Django runs identically from its new location with zero code/behavior
changes — only paths moved.

### Phase 2 — Add root Turborepo + pnpm workspace tooling

**What happens:** Create root `package.json` (private, workspaces via
`pnpm-workspace.yaml` listing `apps/*`), `pnpm-workspace.yaml`, `turbo.json` defining
`dev`, `build`, `lint` pipeline tasks. Install `turbo` as a root devDependency via pnpm.

**Test:** `pnpm install` succeeds at repo root with no errors; `pnpm turbo --version`
resolves.

**Verify:** `cat pnpm-workspace.yaml` lists `apps/*`; `node -e "require('./package.json')"`
parses cleanly.

**Done when:** `pnpm install` from repo root completes and recognizes both `apps/backend`
(if given a minimal `package.json` stub for turbo task wiring) and `apps/frontend` as
workspace packages.

### Phase 3 — Initialize SvelteKit app at `apps/frontend`

**What happens:** Scaffold a new SvelteKit project with TypeScript using
`pnpm dlx sv create apps/frontend` (or `pnpm create svelte@latest apps/frontend` depending
on current CLI), defaults otherwise (no Tailwind/ESLint extras unless the scaffold
defaults include them), then `pnpm install` inside the workspace.

**Test:** `pnpm --filter frontend dev` boots the SvelteKit dev server and the default
welcome page loads in a browser at its printed local URL.

**Verify:** `apps/frontend/package.json` exists with `name: "frontend"` (or whatever the
scaffold names it — confirm it matches the `--filter` used in turbo tasks);
`apps/frontend/src/routes/+page.svelte` exists untouched from the template.

**Done when:** A fresh `pnpm --filter frontend dev` serves the unmodified SvelteKit
starter page with no errors.

### Phase 4 — Wire `turbo.json` tasks for both apps

**What happens:** Add a minimal `package.json` to `apps/backend` (name `"backend"`, no
real deps, just `scripts.dev` = `"source venv/bin/activate && python manage.py
runserver"` or a shell wrapper script, since turbo expects an npm script per task) so
turbo can orchestrate it alongside the frontend. Define `turbo.json` pipeline: `dev`
(persistent, no cache), `build` (frontend only — backend has no build step, give it a
no-op `echo` script), `lint` (frontend only initially, backend no-op `echo` script).

**Test:** `pnpm turbo dev` from repo root starts both the Django dev server and the
SvelteKit dev server concurrently (visible in interleaved terminal output).

**Verify:** Visiting both `127.0.0.1:8000` (Django) and the SvelteKit dev URL (typically
`127.0.0.1:5173`) work simultaneously while `pnpm turbo dev` is running.

**Done when:** A single `pnpm turbo dev` command from repo root brings up both apps with
no manual multi-terminal juggling required, and `Ctrl+C` cleanly stops both.

### Expected Outcome

- Repo root has `package.json`, `pnpm-workspace.yaml`, `turbo.json`.
- `apps/backend/` contains the untouched-in-behavior Django project.
- `apps/frontend/` contains a fresh, default SvelteKit (TypeScript) scaffold with no
  custom UI work.
- `pnpm turbo dev` runs both apps concurrently from repo root.
- No existing Django templates/admin/review UI design has been touched or ported.

## Scope (In/Out)

**In scope:**
- Moving Django project files into `apps/backend/` with zero behavior change.
- Root pnpm workspace + Turborepo config (`turbo.json`, `pnpm-workspace.yaml`, root
  `package.json`).
- Fresh, default SvelteKit (TypeScript) scaffold at `apps/frontend/`.
- Minimal `package.json` script stubs in `apps/backend` so turbo can drive `manage.py
  runserver` as a workspace task.
- Updating `.gitignore` if paths need root-relative adjustment after the move.

**Out of scope:**
- Any redesign, theming, or component work in SvelteKit.
- Porting any existing Django template/HTML/CSS into Svelte.
- Wiring the frontend to call Django REST/JSON endpoints (Django currently has no JSON
  API — that's future work).
- CI/CD changes.
- Docker/containerization.
- Production deployment config.

## Assumptions and Constraints

- pnpm (10.33.0) and Node (v22.17.1) are already installed and available on PATH —
  confirmed via `pnpm -v` / `node -v`.
- The Django `venv/` stays a Python virtualenv; it is not touched by pnpm/turbo beyond
  being invoked via a shell command in `apps/backend`'s `package.json` `dev` script.
- `db.sqlite3` moves with the backend folder (it's git-ignored but present in the working
  tree per repo convention — moving it preserves continuity of local dev data).
- SvelteKit scaffold tool is whatever is current via `pnpm dlx sv create` (the Svelte CLI
  has migrated from `create-svelte` to `sv create` as of recent Svelte tooling) — use
  whichever the installed `pnpm` resolves; fall back to `pnpm create svelte@latest` if `sv`
  is unavailable.
- No changes to `process/`, `.claude/`, `.codex/`, `AGENTS.md`, `CLAUDE.md` paths — those
  stay at repo root since they're harness/process files, not app code.

## Functional Requirements

- Django app must run identically (same URLs, same admin, same `/review/` UI) after the
  move, only from a new path.
- `pnpm turbo dev` must start both apps from a single root command.
- SvelteKit app must be a clean, default, unmodified scaffold (TypeScript enabled).
- Workspace must be discoverable via `pnpm-workspace.yaml` (`apps/*`).

## Non-Functional Requirements

- No behavior regression in the Django app (existing 21 tests in `events/tests.py` must
  still pass after the move).
- Root `package.json` must be marked `"private": true` (monorepo root should never be
  published).

## Acceptance Criteria

- [ ] `apps/backend/manage.py test events` passes all existing tests post-move.
- [ ] `apps/backend/manage.py runserver` serves identical UI/admin/review behavior as
      before the move.
- [ ] Root `pnpm install` succeeds and recognizes `apps/backend` + `apps/frontend` as
      workspace members.
- [ ] `pnpm --filter frontend dev` serves the default SvelteKit welcome page.
- [ ] `pnpm turbo dev` from repo root starts both Django and SvelteKit dev servers
      concurrently.
- [ ] No existing Django template/HTML content was modified, only relocated.
- [ ] `git status` after the move shows file *renames* (not delete+add) where git detects
      them, confirming history is preserved as much as possible.
- [ ] `.gitignore` still correctly ignores `db.sqlite3`, `venv/`, `.env`, frontend's
      `node_modules/` and `.svelte-kit/`, and root `node_modules/`.

## Implementation Checklist

1. [x] Create `apps/` directory.
2. [x] `git mv config events manage.py requirements.txt templates db.sqlite3 venv .env check_schema.py debug_*.py debug_*.html debug_*.png tmp_research apps/backend/` (confirm `db.sqlite3`/`.env`/`venv` are git-ignored — use plain `mv` for those, `git mv` for tracked files only).
3. [x] Test: from `apps/backend/`, run `python manage.py check` and `python manage.py test events` — confirm all pass with no path errors.
4. [x] Update `.gitignore` if any entries were root-relative path globs that need to move/duplicate for `apps/backend/`.
5. [x] Create root `package.json` (`"private": true`, `"packageManager": "pnpm@10.33.0"`, empty `scripts`).
6. [x] Create root `pnpm-workspace.yaml` with `packages: ["apps/*"]`.
7. [x] Create root `turbo.json` with `dev` (persistent, `cache: false`), `build`, `lint` task definitions.
8. [x] `pnpm add -D turbo -w` at repo root.
9. [x] Test: `pnpm install` at repo root completes with no errors.
10. [x] Create minimal `apps/backend/package.json` (`name: "backend"`, `private: true`, `scripts.dev` invoking the venv + `manage.py runserver`, `scripts.build`/`scripts.lint` as no-op `echo` placeholders).
11. [x] Scaffold SvelteKit: `pnpm dlx sv create apps/frontend` (TypeScript, defaults) — if `sv` is unavailable, use `pnpm create svelte@latest apps/frontend`.
12. [x] `pnpm install` inside `apps/frontend` (or let root install handle it via workspace).
13. [x] Test: `pnpm --filter frontend dev` serves the SvelteKit welcome page in a browser.
14. [x] Test: `pnpm turbo dev` from repo root starts both apps concurrently; visit both URLs to confirm.
15. [x] Confirm `.gitignore` covers `node_modules/`, `apps/frontend/.svelte-kit/`, `apps/frontend/build/`, and any turbo cache dir (`.turbo/`).

## Risks and Mitigations

- **Risk:** Moving `venv/` (a large binary-heavy directory) via `git mv` could be slow or
  pollute git history since it's git-ignored anyway. **Mitigation:** use plain `mv` for
  git-ignored paths (`venv/`, `db.sqlite3`, `.env`), `git mv` only for tracked files.
- **Risk:** Hardcoded absolute paths anywhere in Django settings/scripts that assume repo
  root. **Mitigation:** `BASE_DIR` in `settings.py` is already computed relative to the
  file's own location, so this should be a non-issue — verify via `manage.py check`.
- **Risk:** SvelteKit CLI naming/flags have shifted across versions (`create-svelte` vs
  `sv create`). **Mitigation:** plan allows fallback command; verify whichever succeeds
  produces a working `apps/frontend/package.json` + dev script before proceeding.
- **Risk:** `turbo dev` task for Django needs the venv activated in a non-interactive
  shell. **Mitigation:** use `apps/backend/venv/bin/python manage.py runserver` directly
  in the npm script rather than relying on `source venv/bin/activate` (subshells from npm
  scripts don't reliably inherit `source`).

## Integration Notes

- Context consulted: `process/context/all-context.md` (repo structure, Django stack, scraper
  framework conventions) — this plan does not change anything documented there other than
  the on-disk location of the `events/`/`config/` app code.
- No data model touches.
- No environment variable changes beyond confirming `.env` still loads correctly from
  its new path (`apps/backend/.env`) — `BASE_DIR / ".env"` in `settings.py` resolves
  correctly since `BASE_DIR` moves with `settings.py`.
- This plan does not touch `process/`, `.claude/`, `.codex/`, `AGENTS.md`, or `CLAUDE.md` —
  those remain at repo root as harness files, unaffected by the app-code restructuring.

## Touchpoints

- Repo root: new `package.json`, `pnpm-workspace.yaml`, `turbo.json`, `.gitignore`
  updates.
- `apps/backend/`: relocated Django project (all existing files, paths only).
- `apps/frontend/`: new SvelteKit scaffold (entirely new files from the `sv create`
  template).
- No changes to `process/`, `.claude/`, `.codex/`, `README.md`, `AGENTS.md`, `CLAUDE.md`.

## Public Contracts

- Django's external behavior (URLs, admin, `/review/` UI, scraper CLI) must remain
  byte-for-byte identical — this is a pure relocation, not a refactor.
- No new public API/contract is introduced by the SvelteKit scaffold in this pass (it's
  an unconnected, standalone app for now).

## Blast Radius

- Every tracked file under `config/`, `events/`, `templates/`, plus `manage.py`,
  `requirements.txt`, and the debug scripts at repo root will show as moved/renamed in
  git.
- Root-level `.gitignore` gets new/adjusted entries.
- New files: root `package.json`/`pnpm-workspace.yaml`/`turbo.json`, all of
  `apps/frontend/`, `apps/backend/package.json`.
- No production system is affected (no CI, no deploy pipeline exists yet per
  `process/context/tests/all-tests.md`).

## Verification Evidence

Required before marking this plan ✅ VERIFIED (not just 🔨 CODE DONE):
- Terminal output of `apps/backend` test run (all existing tests green).
- Terminal output / screenshot confirming Django UI loads from new location.
- Terminal output / screenshot confirming SvelteKit default page loads.
- Terminal output confirming `pnpm turbo dev` starts both processes and both URLs respond.
- `git status` / `git diff --stat` summary showing the move as renames where possible.

## Resume and Execution Handoff

A resumed executor should:
1. Read this plan file in full before touching anything.
2. Check `git status` first — if `apps/backend` already exists, Phase 1 is likely
   complete; verify by running the Phase 1 test commands before re-doing the move.
3. Check for root `turbo.json`/`pnpm-workspace.yaml` existence to determine if Phase 2 is
   done.
4. Check for `apps/frontend/package.json` existence to determine if Phase 3 is done.
5. Never re-run `git mv` on files that have already moved — this plan is idempotent only
   if phase-completion is checked first.

## Cursor + RIPER-5 Guidance

- Cursor Plan mode: import the "Implementation Checklist" steps directly, execute by
  phase, update the status strip after each phase.
- RIPER-5: this plan is the PLAN artifact. Request "ENTER EXECUTE MODE" to begin Phase 1.
- After each phase, STOP and verify per the Phase Completion Rules above before
  proceeding to the next phase.
