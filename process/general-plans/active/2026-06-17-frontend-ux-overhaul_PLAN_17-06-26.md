# Frontend UX Overhaul — Implementation Plan

**Plan ID:** frontend-ux-overhaul  
**Created:** 2026-06-17  
**Complexity:** COMPLEX  
**Status:** ACTIVE — awaiting EXECUTE

---

## Overview

Improve the UX and visual consistency of the SvelteKit admin frontend (`apps/frontend`) across
all pages. The highest-priority deliverable is converting the `/organizers` card grid into a
polished, sortable data table. Secondary work standardizes loading/empty/error states, adopts
`lucide-svelte` to eliminate duplicated inline SVG strings, adds a responsive sidebar, and
performs a global polish pass on typography, accessibility, and chart theming.

All work is frontend-only. The Django backend is read-only from the frontend's perspective;
no mutation endpoints are added as part of this plan.

---

## Goals and Success Metrics

| Goal | Measurable Signal |
|---|---|
| Organizers table replaces card grid | `/organizers` renders a `<table>`, cards are gone, sorting chevrons appear in headers |
| Client-side column sort works on organizers | Clicking a column header re-orders rows; active column is visually indicated |
| Consistent loading states | All three list pages (`/events`, `/venues`, `/organizers`) show skeleton rows during fetch |
| Consistent empty + error states | Empty message and error banner render on all list pages; error boundary route exists |
| `lucide-svelte` adopted | Zero inline `<svg>` strings remain in `Sidebar.svelte`; icon import pattern documented |
| Responsive sidebar | Sidebar collapses to icon-only at < 768 px; drawer opens on tap |
| Page titles | Every route has a unique `<title>` via `<svelte:head>` |
| `app.html` cleaned | `<meta name="text-scale">` removed; default `<title>Veent Admin</title>` added |
| Error route | `src/routes/+error.svelte` renders correctly with dark-theme styling |
| Badge category colors | Event-category badges use deterministic distinct colors instead of neutral fallback |
| Build passes | `pnpm --filter frontend build` exits 0 with no type errors |
| Lint passes | `pnpm --filter frontend lint` exits 0 |

---

## Scope

### In scope

- `apps/frontend/src/routes/organizers/+page.svelte` — full rewrite to table
- `apps/frontend/src/lib/components/Sidebar.svelte` — SVG → lucide; responsive collapse/drawer
- `apps/frontend/src/lib/components/Badge.svelte` — deterministic category colors
- `apps/frontend/src/lib/components/BarChart.svelte` — CSS-variable token colors
- `apps/frontend/src/lib/components/DonutChart.svelte` — CSS-variable token colors
- `apps/frontend/src/lib/utils/sort.ts` (new) — generic client-side column sort utility
- `apps/frontend/src/lib/components/TableSkeleton.svelte` (new) — reusable skeleton row component
- `apps/frontend/src/routes/+error.svelte` (new) — styled error boundary
- `apps/frontend/src/app.html` — remove bogus meta, add default title
- `apps/frontend/src/routes/+layout.svelte` — `<svelte:head>` default title fallback
- `apps/frontend/src/routes/+page.svelte` — `<svelte:head>` title
- `apps/frontend/src/routes/events/+page.svelte` — loading skeleton, empty/error states, optional sort
- `apps/frontend/src/routes/venues/+page.svelte` — loading skeleton, empty/error states, optional sort
- `apps/frontend/src/routes/scrapers/+page.svelte` — `<svelte:head>` title
- `apps/frontend/src/routes/organizers/[slug]/+page.svelte` — `<svelte:head>` title

### Out of scope / Non-Goals

- **Backend mutation endpoints** — organizer status is read-only; editing status is a follow-up
  feature requiring a PATCH `/api/organizers/<slug>/status/` endpoint and auth middleware.
- Server-side sorting or pagination (all sort is client-side on the current page).
- Light-mode / theme switching.
- Playwright / E2E test coverage for new UI (unit test additions are optional stretch).
- Migration of `BarChart`/`DonutChart` to a different charting library.
- Any changes to Django backend code.

---

## Design Direction

### Organizers Table Aesthetic

The table replaces the card grid with a dense, scannable layout using existing dark-theme tokens:

| Element | Treatment |
|---|---|
| Table container | `bg-surface` card with `border border-[var(--color-border)] rounded-lg overflow-hidden` |
| `<thead>` | `bg-[var(--color-surface-2)] sticky top-0 z-10` |
| Header cells | `text-muted text-xs font-semibold uppercase tracking-wider px-4 py-3`; sortable headers add sort chevron icon from lucide-svelte |
| Active sort column | Accent-colored chevron (`text-accent`); column text also slightly brighter |
| Body rows | `border-t border-[var(--color-border)] hover:bg-[var(--color-surface-2)] transition-colors duration-100` |
| Row cells | `px-4 py-3 text-sm text-[var(--color-text)]` |
| No zebra striping | Clean dense rows; hover provides the visual cue |
| Organizer column | Name as link → detail page; below it a `<code>` tag `text-xs font-mono text-muted bg-[var(--color-bg)] px-1 rounded` for source key |
| Status column | Existing `<Badge>` component (`pending` → warning, `confirmed` → success, `rejected` → danger) |
| Location column | `city, country` or `—` placeholder |
| Contact column | Email + phone stacked; each as a small anchor or plain text |
| Links column | Website / Facebook / Instagram as icon buttons (lucide `Globe`, `Facebook`, `Instagram`) right-aligned, `gap-2`, open in new tab |
| Row click | Entire row links to `/organizers/[slug]` via `on:click` or wrapping anchor trick |

### Skeleton Rows

`TableSkeleton.svelte` renders N placeholder rows (default 8) of animated pulse bars
using `animate-pulse bg-[var(--color-surface-2)]` utility classes. Accepts a `columns` prop
(number of `<td>` cells to render) and an optional `rows` prop.

### Sort Utility

`src/lib/utils/sort.ts` exports:
- A generic `sortRows<T>(rows: T[], key: keyof T, direction: 'asc' | 'desc'): T[]` function.
- A `SortState<T>` type: `{ key: keyof T | null; direction: 'asc' | 'desc' }`.
- A `toggleSort<T>(current: SortState<T>, key: keyof T): SortState<T>` helper.

Sort is applied reactively in each page via a `$derived` rune on the raw API data.

---

## Implementation Steps

Steps are ordered for safe execution. Steps 1–7 are **core** (must ship). Steps 8–10 are
**stretch** (do if time allows, mark clearly in PR). Each step includes the verification action.

---

### Step 1 — Clean `app.html` and add default `<title>`

**File:** `apps/frontend/src/app.html`

**Change:**
- Remove `<meta name="text-scale" content="scale" />` (invalid, no browser effect).
- Add `<title>Veent Admin</title>` inside `<head>` as a fallback (SvelteKit `<svelte:head>`
  overrides per-route).

**Verification:** `pnpm --filter frontend build` passes. Browser tab shows "Veent Admin" on
any route that does not override it.

---

### Step 2 — Create `src/routes/+error.svelte`

**File:** `apps/frontend/src/routes/+error.svelte` (new)

**Change:** Create an error boundary component that:
- Imports `page` from `$app/stores` to read `$page.error.message` and `$page.status`.
- Renders a full-height centered card using dark-theme tokens (`bg-surface`, `text-heading`,
  `text-muted`, accent-colored status code).
- Includes a "Go to Dashboard" link back to `/`.
- Has a `<svelte:head><title>Error — Veent Admin</title></svelte:head>`.

**Verification:** Navigate to `/nonexistent-route`; error page renders with dark styling.

---

### Step 3 — Create `src/lib/utils/sort.ts`

**File:** `apps/frontend/src/lib/utils/sort.ts` (new)

**Change:** Export `SortState<T>`, `sortRows<T>()`, and `toggleSort<T>()` as described in
Design Direction above. Handle `null` key (return original array). Handle string, number, and
date-string comparison (ISO strings compare lexicographically correctly).

**Verification:** No runtime check needed here — type-checks during `pnpm --filter frontend build`.

---

### Step 4 — Create `src/lib/components/TableSkeleton.svelte`

**File:** `apps/frontend/src/lib/components/TableSkeleton.svelte` (new)

**Change:** Accept props `rows: number = 8` and `columns: number = 5`. Render a `<tbody>` with
`rows` `<tr>` elements, each containing `columns` `<td>` cells with an `animate-pulse` div of
varying widths to simulate content. Use `bg-[var(--color-surface-2)] rounded h-4`.

**Verification:** Import in organizers page (Step 5) and confirm skeleton renders before data loads.

---

### Step 5 — PRIMARY: Rewrite `/organizers` page to sortable table

**File:** `apps/frontend/src/routes/organizers/+page.svelte`

**Change (full rewrite — preserve all existing logic, change only the template and add sort):**

- Keep all existing reactive state: `q`, `status`, `page`, `data` (`$state`), `loading`
  (`$state`), `error` (`$state`).
- Keep the `$effect` on `q`/`status`/`page` → `api.organizers()`.
- Add `import { sortRows, toggleSort } from '$lib/utils/sort.js'`.
- Add `import TableSkeleton from '$lib/components/TableSkeleton.svelte'`.
- Add `import { Globe, Facebook, Instagram, ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-svelte'`.
- Add `let sortState = $state<SortState<Organizer>>({ key: null, direction: 'asc' })`.
- Add `const sorted = $derived(sortRows(data?.results ?? [], sortState.key, sortState.direction))`.
- Template structure:
  1. `<svelte:head><title>Organizers — Veent Admin</title></svelte:head>`
  2. `<PageHeader>` with title "Organizers" and count badge (existing pattern).
  3. Status tabs (existing `pending|confirmed|rejected|all` tabs — keep as-is).
  4. Search input (existing — keep as-is).
  5. `<div class="...card wrapper...">` containing a `<table class="w-full text-left">`.
  6. `<thead>` with sticky header row. Columns: Organizer, Status, Location, Contact, Links.
     Sortable columns (Organizer, Location) get a `<button>` with `on:click` → `toggleSort`.
     Show `ChevronsUpDown` (inactive), `ChevronUp`/`ChevronDown` (active direction) from lucide.
  7. `{#if loading}<TableSkeleton columns={5} />{:else if error}<tr><td colspan="5">error
     banner</td></tr>{:else if sorted.length === 0}<tr><td colspan="5">empty state</td></tr>
     {:else}{#each sorted as org}...row...{/each}{/if}`
  8. Row structure per Design Direction above.
  9. Pagination controls (existing — keep as-is).

**Verification:** Run `pnpm dev`; navigate to `/organizers`. Confirm:
- Table renders with 50 rows (or however many the API returns for the default query).
- Clicking "Organizer" header sorts by name ascending, then descending on second click.
- Status tabs still filter correctly.
- Search still works.
- Each row's organizer name links to `/organizers/[slug]`.
- `pnpm --filter frontend lint` passes.
- `pnpm --filter frontend build` passes.

---

### Step 6 — Add `<svelte:head>` titles to all remaining routes

**Files (one edit each):**
- `apps/frontend/src/routes/+page.svelte` → `<title>Dashboard — Veent Admin</title>`
- `apps/frontend/src/routes/events/+page.svelte` → `<title>Events — Veent Admin</title>`
- `apps/frontend/src/routes/venues/+page.svelte` → `<title>Venues — Veent Admin</title>`
- `apps/frontend/src/routes/scrapers/+page.svelte` → `<title>Scrapers — Veent Admin</title>`
- `apps/frontend/src/routes/organizers/[slug]/+page.svelte` → `<title>{organizer?.name ?? 'Organizer'} — Veent Admin</title>` (reactive)

**Verification:** Each browser tab updates when navigating between routes.

---

### Step 7 — Consistent loading/empty/error states on `/events` and `/venues`

**Files:**
- `apps/frontend/src/routes/events/+page.svelte`
- `apps/frontend/src/routes/venues/+page.svelte`

**Change for each:**
- Import `TableSkeleton`.
- Replace any ad-hoc loading text (e.g. "Loading...") with `<TableSkeleton columns={N} />` where
  N matches the column count of the existing table. Events table: 6 columns. Venues table: 5 columns.
- Add or replace empty state: centered message in a `<td colspan="N">` cell:
  `<p class="text-muted text-sm text-center py-8">No results found.</p>`
- Add or replace error state: same cell wrapper with a red-tinted message:
  `<p class="text-[var(--color-danger)] text-sm text-center py-8">{error}</p>`

**Verification:** Temporarily set a wrong API base URL to trigger error state; confirm banner
renders. Remove the change. Confirm skeleton rows appear on slow network (throttle in DevTools).

---

### Step 8 (STRETCH) — Adopt `lucide-svelte` in `Sidebar.svelte`; replace all inline SVGs

**File:** `apps/frontend/src/lib/components/Sidebar.svelte`

**Change:**
- Add imports for the following lucide icons (mapping from current inline SVGs):
  - Zap (lightning bolt — logo/brand mark)
  - LayoutGrid (dashboard)
  - Radio (scrapers)
  - Calendar (events)
  - Users (organizers)
  - MapPin (venues)
  - User (footer user icon)
- Replace each `<svg>...</svg>` block with the corresponding lucide component, using
  `size={18}` and `strokeWidth={2}` props to match current visual size.
- Add a comment block above the imports: `// Icon convention: use lucide-svelte components.`
  `// Do not add inline <svg> strings. Size: 18px, strokeWidth: 2 for nav icons.`

**NOTE:** `lucide-svelte` is already installed in `package.json`. No new dependency needed.

**Verification:** Visual check — all sidebar nav icons render. `pnpm --filter frontend lint` passes.

---

### Step 9 (STRETCH) — Responsive sidebar (collapse/drawer on mobile)

**File:** `apps/frontend/src/lib/components/Sidebar.svelte`

**Change:**
- Add `let collapsed = $state(false)` controlled by a toggle button visible at all widths
  (hamburger icon from lucide `Menu` / `X`).
- Desktop (>= 768 px): sidebar stays fixed; `collapsed` shrinks it from `w-60` to `w-14`
  (icon-only mode, tooltips on hover via `title` attribute).
- Mobile (< 768 px): sidebar is hidden by default (`-translate-x-full`); toggle button (fixed
  top-left) opens it as an overlay drawer with a semi-transparent backdrop.
- Use Tailwind responsive utilities (`md:`) for breakpoint logic. No JS breakpoint detection;
  use CSS-driven approach with a class toggled by the `$state`.
- Transition: `transition-transform duration-200 ease-in-out`.

**Blast Radius Note:** `Sidebar.svelte` is rendered in `+layout.svelte` and therefore affects
every page. Test all routes after this change.

**Verification:** Resize browser below 768 px. Sidebar hides. Hamburger appears. Tap to open
drawer. Tap backdrop to close. At >= 768 px, collapse button toggles icon-only mode.

---

### Step 10 (STRETCH) — Badge category colors; chart CSS-variable tokens

**File:** `apps/frontend/src/lib/components/Badge.svelte`

**Change:**
- The `variant` prop currently accepts `pending|confirmed|rejected|success|warning|danger|default`.
- Add a `category` prop (optional string). When present, derive a color from a deterministic
  hash of the category string mapped to one of 6 accent colors defined as CSS custom properties
  in `app.css`. Example palette: cyan (`--color-accent`), purple (`#a78bfa`), orange (`#fb923c`),
  pink (`#f472b6`), yellow (`--color-warning`), green (`--color-success`).
- Implement: `const CATEGORY_COLORS = [...]` array of 6 color tokens; hash = sum of char codes
  mod 6; pick color by index.

**File:** `apps/frontend/src/lib/components/BarChart.svelte`  
**File:** `apps/frontend/src/lib/components/DonutChart.svelte`

**Change:**
- Replace hardcoded hex strings (e.g. `#22d3ee`, `#34d399`) with values read from
  `getComputedStyle(document.documentElement).getPropertyValue('--color-accent')` etc.
- Read values inside the `onMount` callback (already used for Chart.js init) to ensure the DOM
  is available when CSS variables are resolved.

**Verification:** Navigate to Dashboard; chart bars/donut segments use token colors. Navigate
to `/events`; category badges for distinct categories show distinct colors.

---

## Touchpoints Table

| File | Change | Risk |
|---|---|---|
| `src/app.html` | Remove bad meta; add default title | Low — global head; no JS impact |
| `src/routes/+error.svelte` | New file — error boundary | Low — only renders on SvelteKit errors |
| `src/lib/utils/sort.ts` | New utility — no side effects | Low |
| `src/lib/components/TableSkeleton.svelte` | New component | Low |
| `src/routes/organizers/+page.svelte` | Full template rewrite | Medium — existing filters/pagination must be preserved |
| `src/routes/+page.svelte` | Add `<svelte:head>` | Low |
| `src/routes/events/+page.svelte` | Add skeleton, empty/error states, `<svelte:head>` | Low-Medium |
| `src/routes/venues/+page.svelte` | Add skeleton, empty/error states, `<svelte:head>` | Low-Medium |
| `src/routes/scrapers/+page.svelte` | Add `<svelte:head>` | Low |
| `src/routes/organizers/[slug]/+page.svelte` | Add `<svelte:head>` | Low |
| `src/lib/components/Sidebar.svelte` (stretch) | Replace SVGs; responsive collapse | High — global layout component, every page affected |
| `src/lib/components/Badge.svelte` (stretch) | Add category color logic | Medium — used on events + organizers pages |
| `src/lib/components/BarChart.svelte` (stretch) | CSS variable chart colors | Low |
| `src/lib/components/DonutChart.svelte` (stretch) | CSS variable chart colors | Low |

---

## Blast Radius

| Component | Pages affected | Regression risk |
|---|---|---|
| `Sidebar.svelte` | Every page (rendered in `+layout.svelte`) | HIGH — regression test all routes visually after Step 8/9 |
| `Badge.svelte` | `/events`, `/organizers`, `/organizers/[slug]` | MEDIUM — category color change is additive; existing variant prop unchanged |
| `TableSkeleton.svelte` | `/events`, `/venues`, `/organizers` | LOW — new component, only renders during loading state |
| `sort.ts` | `/organizers` (Step 5), optional `/events`, `/venues` | LOW — pure function, no side effects |
| `app.html` | All pages | LOW — removing invalid meta and adding title only |

---

## Dependencies

| Dependency | Status | Notes |
|---|---|---|
| `lucide-svelte` | Already installed | Confirmed in `package.json`; no `pnpm add` needed |
| `@tailwindcss/vite` + Tailwind v4 | Already configured | `animate-pulse` is available; verify in `app.css` if not |
| Django backend API | No changes needed | `GET /api/organizers/` already returns all fields needed for table columns |
| Svelte 5 runes | Already enforced | `$state`, `$derived`, `$effect` are the correct primitives |

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Organizers page rewrite accidentally breaks status-tab filtering or pagination | Medium | Keep `$effect` watcher and API call logic verbatim; only replace template markup |
| `Sidebar.svelte` responsive work breaks desktop layout | Medium | Implement desktop collapse first, test, then add mobile drawer; keep `w-60` as the default open state |
| `lucide-svelte` icon names differ from expected | Low | Verify each icon name in lucide-svelte docs before substituting; fall back to `svg` if unavailable |
| `animate-pulse` not available without Tailwind `animation` utilities | Low | Tailwind v4 includes `animate-pulse` by default; confirm with `pnpm --filter frontend build` |
| CSS variable chart color resolution fails (chart renders before DOM) | Low | Read variables inside `onMount` (already the pattern in both chart components) |
| Sort on server-paginated data only sorts current page | Known limitation | Document explicitly in code comment; full cross-page sort requires backend `ordering=` param (out of scope) |

---

## Verification Evidence

After full execution, the following must all be true:

1. `pnpm --filter frontend build` exits 0, no TypeScript errors.
2. `pnpm --filter frontend lint` exits 0.
3. `pnpm dev` → navigate to `/organizers`:
   - Table renders (not card grid).
   - Clicking "Organizer" column header sorts A→Z, then Z→A.
   - Status badge colors: `pending` = warning yellow, `confirmed` = success green, `rejected` = danger red.
   - Monospace source tag visible under each organizer name.
   - Globe/Facebook/Instagram icon links visible in Links column (icons, not SVG blobs).
   - Skeleton rows appear during initial load (throttle network in DevTools to confirm).
   - Empty state message renders when search returns no results.
4. Navigate to `/events` and `/venues`: skeleton rows on load, empty state on no-results.
5. Browser tab title updates correctly on every route.
6. Navigate to `/nonexistent` → dark-themed error page renders.
7. (Stretch) All sidebar icons render via lucide components; no inline SVG visible in DOM inspector.
8. (Stretch) Sidebar collapses on narrow viewport; drawer overlay opens on hamburger click.

---

## Non-Goals (Explicit)

- **No organizer status editing.** The frontend remains read-only. Status is set only through
  Django admin or the `/review/` Django UI. A future plan will add `PATCH /api/organizers/<slug>/status/`
  and a SvelteKit mutation flow.
- **No server-side sort.** Column sort operates only on the current page of results (up to 50).
  Cross-page sort requires a backend `ordering=` query param — out of scope.
- **No light mode.** All tokens remain dark-only.
- **No new scraper integrations.** This is frontend-only work.
- **No Playwright / E2E tests.** Manual visual verification is sufficient for this pass.

---

## Resume and Execution Handoff

**Selected plan file:** `process/general-plans/active/2026-06-17-frontend-ux-overhaul_PLAN_17-06-26.md`

**Execute sequence:**
1. Steps 1–7 are **core** — execute in order, verify each before proceeding.
2. Steps 8–10 are **stretch** — execute only if Steps 1–7 are complete and verified.
3. After each step, run `pnpm --filter frontend build` to catch type errors early.
4. After Steps 1–7 complete, do a full visual regression pass (all routes).
5. After stretch steps, repeat visual pass focusing on Sidebar across all routes.

**Key constraint for executor:** The organizers page rewrite (Step 5) is a template-only
change. Preserve the existing `$state` declarations, the `$effect` watcher, and the
`api.organizers()` call verbatim. Only the markup below the controls section changes.

**Dev command:** `pnpm dev` from repo root (Turbo starts frontend + backend concurrently).
Frontend available at `http://localhost:5173`. Backend at `http://localhost:8000`.

**Lint command:** `pnpm --filter frontend lint`  
**Build command:** `pnpm --filter frontend build`  
**Test command (Django, unrelated):** `./venv/bin/python manage.py test events`
