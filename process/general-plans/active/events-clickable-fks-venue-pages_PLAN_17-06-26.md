# Plan: Clickable FK Links in Events Table + Venue Detail Pages

**Date:** 2026-06-17
**Complexity:** SIMPLE (single session, ~12 atomic steps)
**Status:** READY FOR EXECUTE

---

## Overview

Two related UI improvements with minimal backend serialization support:

1. **Events table** — make the venue and organizer cells clickable links to their detail pages. Organizer links are conditional: rendered only when `organizer_slug` is present (i.e. the event has a matched `organizer_ref` FK). Plain text fallback otherwise.
2. **Venue detail pages** — add `/venues/[slug]` route in the SvelteKit frontend, mirroring the existing `/organizers/[slug]` pattern. The venues list rows also link to the new detail page.

Enabling this requires two small backend additions:
- Emit `venue_slug` and `organizer_slug` in the `api_events` JSON payload.
- Add a new `api_venue_detail` view + URL.

No scraper changes. No data backfill. No migrations.

---

## Goals

- Operators can click a venue name in the events table and navigate to a venue detail page.
- Operators can click an organizer name in the events table (when linked) and navigate to the organizer detail page.
- Operators can click a venue name in the venues list and navigate to the venue detail page.
- The venue detail page shows venue metadata + a list of its related events.

---

## Scope

**In scope:**
- `apps/backend/events/views.py` — two field additions to `api_events`, one new view `api_venue_detail`
- `apps/backend/events/urls.py` — one new URL pattern
- `apps/frontend/src/lib/types.ts` — two field additions to `EventRow`, one new `VenueDetail` type
- `apps/frontend/src/lib/api.ts` — one new `api.venue(slug, f?)` wrapper
- `apps/frontend/src/routes/events/+page.svelte` — venue and organizer cells become conditional links
- `apps/frontend/src/routes/venues/+page.svelte` — venue name cell becomes a link
- `apps/frontend/src/routes/venues/[slug]/+page.ts` — new file (load function)
- `apps/frontend/src/routes/venues/[slug]/+page.svelte` — new file (detail page)
- `apps/backend/events/tests.py` — recommended new test coverage (see Verification section)

**Out of scope:**
- Scraper changes or data backfill for `organizer_ref`
- Cross-source dedup/merge
- Mutation endpoints
- Playwright/Vitest end-to-end tests

---

## Touchpoints (Ordered — Backend First, Then Frontend)

### BACKEND GROUP

#### Step 1 — `api_events`: add `select_related` + two slug fields
**File:** `apps/backend/events/views.py`

**Location context:** `api_events` view. The query that feeds `page_obj` at approximately line 279 currently does `Event.objects.select_related("venue")`. The result dict is built at lines 305–318.

**Changes:**
1. Extend the existing `select_related` call to also join `organizer_ref`:
   - Change `Event.objects.select_related("venue")` → `Event.objects.select_related("venue", "organizer_ref")`
   - This avoids N+1 queries for the new `organizer_ref.slug` access.
2. In the result dict (lines 305–318), after `"organizer": e.organizer_display_name,` add:
   - `"venue_slug": e.venue.slug if e.venue else None,`
   - `"organizer_slug": e.organizer_ref.slug if e.organizer_ref_id else None,`

**Null safety:** `e.organizer_ref_id` (the raw FK column) is used for the null check — avoids an extra DB hit even with `select_related`.

#### Step 2 — New `api_venue_detail` view
**File:** `apps/backend/events/views.py`

**Location context:** Insert after the `api_organizer_detail` function (currently ending around line 403), before `api_venues` (line 406).

**Implementation:** Mirror `api_organizer_detail` (lines 370–403) for Venue. Key shape:

```
def api_venue_detail(request, slug):
    venue = get_object_or_404(Venue, slug=slug)
    events = list(venue.events.order_by("-starts_at")[:50])
    return JsonResponse({
        "slug": venue.slug,
        "name": venue.name,
        "city": venue.city,
        "country": venue.country,
        "address": venue.address,
        "website": venue.website,
        "primary_type_display": venue.primary_type_display,
        "rating": venue.rating,
        "lat": venue.lat,
        "lng": venue.lng,
        "verification_status": venue.verification_status,
        "source": venue.source,
        "source_url": venue.source_url,
        "scraped_at": venue.scraped_at.isoformat() if venue.scraped_at else None,
        "events": [
            {
                "slug": e.slug,
                "name": e.name,
                "starts_at": e.starts_at.isoformat() if e.starts_at else None,
                "category": e.category,
                "organizer": e.organizer_display_name,
            }
            for e in events
        ],
    })
```

Note: `venue.events` uses the `related_name="events"` on `Event.venue` FK (confirmed in `models.py` line 87). `primary_type_display`, `rating`, `lat`, `lng`, `address`, `website`, `source`, `source_url`, `scraped_at` are all fields on `Venue` — confirm exact field names against `apps/backend/events/models.py` before writing. The `api_venues` list view (lines 424–437) already serializes `primary_type_display`, `rating`, `city`, `country`, `source` — use those same field accesses.

#### Step 3 — Register `api_venue_detail` URL
**File:** `apps/backend/events/urls.py`

**Location context:** After line 25 (`path("api/venues/", views.api_venues, ...)`), add:
```
path("api/venues/<slug:slug>/", views.api_venue_detail, name="api_venue_detail"),
```

Place it immediately before `api/venues/` so the slug route doesn't shadow the list route — Django matches paths in order top-to-bottom, so the more-specific slug pattern must come first. Final order in the API section:

```
path("api/venues/<slug:slug>/", views.api_venue_detail, name="api_venue_detail"),
path("api/venues/", views.api_venues, name="api_venues"),
```

---

### FRONTEND GROUP

#### Step 4 — `EventRow` type: add `venue_slug` and `organizer_slug`
**File:** `apps/frontend/src/lib/types.ts`

**Location context:** `EventRow` interface at lines 26–37.

**Changes:** Add two optional-null fields after the existing `organizer: string` field (line 35):
```typescript
venue_slug: string | null;
organizer_slug: string | null;
```

#### Step 5 — New `VenueDetail` type
**File:** `apps/frontend/src/lib/types.ts`

**Location context:** Add after `OrganizerDetail` (lines 55–65), before `VenueRow` (line 67).

**Shape** (mirror `OrganizerDetail` extending `VenueRow`, plus address/source_url/events):
```typescript
export interface VenueDetail extends VenueRow {
    address: string;
    website: string;
    lat: number | null;
    lng: number | null;
    source_url: string;
    scraped_at: string | null;
    events: {
        slug: string;
        name: string;
        starts_at: string | null;
        category: string;
        organizer: string;
    }[];
}
```

Note: `VenueRow` already has `slug`, `name`, `city`, `country`, `primary_type_display`, `rating`, `verification_status`, `event_count`, `source` — no need to repeat those in `VenueDetail`. Add only the fields that `api_venue_detail` returns that are NOT in `VenueRow`. Cross-check `VenueRow` (lines 67–77) and `api_venue_detail` (Step 2) for exact match.

#### Step 6 — `api.venue(slug)` wrapper
**File:** `apps/frontend/src/lib/api.ts`

**Location context:** After `organizer:` (line 48), before `venues:` (line 49).

**Change:** Add import of `VenueDetail` to the import block (line 7–17), then add:
```typescript
venue: (slug: string, f?: Fetch) => get<VenueDetail>(`/venues/${slug}/`, f),
```

Mirror the exact signature of `organizer: (slug: string, f?: Fetch) => ...` at line 48.

#### Step 7 — Events table: conditional venue and organizer links
**File:** `apps/frontend/src/routes/events/+page.svelte`

**Location context:** `<td>` cells at lines 87–88.

**Current (line 87):**
```svelte
<td class="px-5 py-3 text-muted">{e.venue ?? '—'}</td>
```

**Replace with:**
```svelte
<td class="px-5 py-3 text-muted">
    {#if e.venue_slug}
        <a href="/venues/{e.venue_slug}" class="hover:text-accent">{e.venue}</a>
    {:else}
        {e.venue ?? '—'}
    {/if}
</td>
```

**Current (line 88):**
```svelte
<td class="px-5 py-3 text-muted">{e.organizer || '—'}</td>
```

**Replace with:**
```svelte
<td class="px-5 py-3 text-muted">
    {#if e.organizer_slug}
        <a href="/organizers/{e.organizer_slug}" class="hover:text-accent">{e.organizer}</a>
    {:else}
        {e.organizer || '—'}
    {/if}
</td>
```

Styling: `hover:text-accent` matches the existing event name link pattern at line 78.

#### Step 8 — Venues list: link venue name to detail page
**File:** `apps/frontend/src/routes/venues/+page.svelte`

**Location context:** Line 100, inside `{#each data.results as v (v.slug)}` block.

**Current (line 100):**
```svelte
<td class="px-5 py-3 font-medium text-heading">{v.name}</td>
```

**Replace with:**
```svelte
<td class="px-5 py-3 font-medium text-heading">
    <a href="/venues/{v.slug}" class="hover:text-accent">{v.name}</a>
</td>
```

`v.slug` is already available in `VenueRow` (confirmed `types.ts` line 68) and already present in the `api_venues` serialization (line 426 of `views.py`). Mirror the organizer list link at `routes/organizers/+page.svelte` lines 154–158: `class="font-medium text-heading hover:text-accent"`.

#### Step 9 — New `routes/venues/[slug]/+page.ts`
**File:** `apps/frontend/src/routes/venues/[slug]/+page.ts` (NEW — create directory + file)

**Content:** Mirror `apps/frontend/src/routes/organizers/[slug]/+page.ts` exactly, substituting `organizer` for `venue`:
```typescript
import { api } from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => {
    const venue = await api.venue(params.slug, fetch);
    return { venue };
};
```

#### Step 10 — New `routes/venues/[slug]/+page.svelte`
**File:** `apps/frontend/src/routes/venues/[slug]/+page.svelte` (NEW)

**Template:** Mirror `apps/frontend/src/routes/organizers/[slug]/+page.svelte` structure.

**Layout:**
- `$props()` to get `data`, `$derived` to get `v = data.venue`
- `svelte:head` — `<title>{v?.name ?? 'Venue'} — Veent Admin</title>`
- `PageHeader` — `title={v.name}` `subtitle="Venue details"`
- Back link — `<a href="/venues">Back to venues</a>` with same chevron SVG + `class="mb-5 inline-flex items-center gap-1 text-sm text-muted hover:text-accent"` (mirror organizer detail line 23–26)
- Two-column grid (`lg:grid-cols-3`):
  - Left (`lg:col-span-1`): venue info card — name heading + `Badge status={v.verification_status}`, optional description (Venue has no description field — omit), `<dl>` with: website (use `safeUrl`), address/city/country, rating, type (`primary_type_display`), lat/lng (only if non-null), source + source_url footer, scraped_at
  - Right (`lg:col-span-2`): events table — name, starts_at, category, organizer columns; empty-state message "No events at this venue yet."
- Import `safeUrl` from `$lib/utils/url` (same as organizer detail line 5) for the website field.
- Use `formatDate` from `$lib/format` (mirror organizer detail line 4) for `starts_at` and `scraped_at`.
- `Badge` component: pass `status={v.verification_status}` (maps to `VenueStatus` values: `pending`/`verified`/`rejected`).

**Fields to display in the left card (all from `VenueDetail`):**
- Name + `Badge status={v.verification_status}`
- Website (linked, using `safeUrl`)
- Address: `[v.address, v.city, v.country].filter(Boolean).join(', ')`
- Rating: `v.rating != null ? \`★ ${v.rating}\` : '—'`
- Type: `v.primary_type_display || '—'`
- Lat/Lng: only show if both non-null (e.g. `{v.lat}, {v.lng}`)
- Source footer: source key + source_url link + scraped_at (mirror organizer detail lines 82–88)

**Events table columns:** Event name, Starts (formatDate), Category (Badge), Organizer (plain text — no slug available in this context)

---

## Blast Radius

| File | Change type |
|---|---|
| `apps/backend/events/views.py` | Modified — 2 field additions to `api_events` dict; 1 new function `api_venue_detail` (~20 lines) |
| `apps/backend/events/urls.py` | Modified — 1 new `path()` entry |
| `apps/frontend/src/lib/types.ts` | Modified — 2 fields on `EventRow`; 1 new `VenueDetail` interface |
| `apps/frontend/src/lib/api.ts` | Modified — 1 new `venue()` wrapper + import |
| `apps/frontend/src/routes/events/+page.svelte` | Modified — 2 `<td>` cells |
| `apps/frontend/src/routes/venues/+page.svelte` | Modified — 1 `<td>` cell |
| `apps/frontend/src/routes/venues/[slug]/+page.ts` | NEW |
| `apps/frontend/src/routes/venues/[slug]/+page.svelte` | NEW |
| `apps/backend/events/tests.py` | Recommended additions (see below) |

**Ripple effects:**
- `EventRow` type change is additive (new optional-null fields) — no existing consumers break.
- The new URL `api/venues/<slug>/` must appear before `api/venues/` in `urls.py` to avoid shadowing (Step 3).
- `api_events` query gains `select_related("organizer_ref")` — small query cost increase but eliminates N+1. Acceptable on paginated 50-row pages.
- No migrations required (no model changes).
- No CORS or auth changes required.

---

## Verification Evidence

### Automated

1. **Backend tests (existing suite):**
   ```
   cd apps/backend && ./venv/bin/python manage.py test events
   ```
   All 49 existing tests must still pass after changes.

2. **Migration drift check (confirm no accidental model change):**
   ```
   cd apps/backend && ./venv/bin/python manage.py makemigrations --check --dry-run
   ```
   Must exit 0 with no pending migrations.

3. **Frontend type check:**
   ```
   pnpm --filter frontend check
   ```
   Must report 0 errors.

4. **Frontend build:**
   ```
   pnpm --filter frontend build
   ```
   Must complete without errors.

### Recommended New Backend Tests (in `apps/backend/events/tests.py`)

Add to the existing `TestCase` suite:

- **`ApiEventsSlugsTest`**: Create an `Event` with a linked `Venue` and a linked `Organizer` (via `organizer_ref`). GET `/api/events/`. Assert response JSON contains `venue_slug` equal to `venue.slug` and `organizer_slug` equal to `organizer.slug`. Also create an event with no venue and no `organizer_ref` — assert both slug fields are `null`.
- **`ApiVenueDetailTest`**: Create a `Venue` and two `Event`s referencing it. GET `/api/venues/<slug>/`. Assert 200, correct venue fields, and `events` list with 2 items containing `slug`, `name`, `starts_at`, `category`, `organizer` keys. Also test 404 with a non-existent slug.

These are recommended, not blocking for EXECUTE.

### Manual Verification

5. **Curl `api_events` for new slug fields:**
   ```
   curl -s "http://localhost:8000/api/events/" | python3 -m json.tool | grep -E "venue_slug|organizer_slug"
   ```
   Expect `venue_slug` and `organizer_slug` keys in at least some rows (null is acceptable for unlinked events).

6. **Curl `api_venue_detail`:**
   ```
   curl -s "http://localhost:8000/api/venues/<a-real-slug>/" | python3 -m json.tool
   ```
   Expect venue fields + `events` array. Also verify 404 for a non-existent slug.

7. **Events table → venue page:**
   - Open `/events`, find a row with a venue name.
   - If the event has a `venue_slug`, the venue cell should be a clickable link.
   - Click it → should navigate to `/venues/<slug>` showing venue detail.
   - If the event has no venue, cell shows `—` (plain text).

8. **Events table → organizer page:**
   - Find a row where the event has a matched organizer (i.e. `organizer_slug` is non-null).
   - Organizer cell should be a clickable link → navigates to `/organizers/<slug>`.
   - Rows with unmatched organizers show plain text name or `—`.

9. **Venues list → venue page:**
   - Open `/venues`, click any venue name.
   - Should navigate to `/venues/<slug>` showing the venue detail page with info card + events table.

10. **Venue detail page empty-state:**
    - Find a venue with zero events. Venue detail page should show "No events at this venue yet." in the events section.

---

## Dependencies and Ordering Rules

- Steps 1–3 (backend) must be complete before manual API verification (steps 5–6).
- Step 4–5 (types) must precede Steps 6–10 (api wrapper and routes use the types).
- Step 6 (`api.venue`) must precede Steps 9–10 (new route files import it).
- Steps 7–8 (template edits) depend on Step 4 (`EventRow` type change) — TypeScript check will fail if types are updated after the template edits reference the new fields.
- Steps 9–10 (new route) are independent of steps 7–8 and can be done in any order relative to each other, but both depend on Steps 4–6.

**Execute order within EXECUTE session:** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → verify.

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| URL route order: `api/venues/<slug>/` shadows `api/venues/` | Medium | Step 3 explicitly orders slug route before list route. Django's router matches top-to-bottom; more-specific route first. |
| `organizer_ref` N+1 in `api_events` | Low | Resolved by adding `select_related("organizer_ref")` in Step 1. |
| Venue has no `description` field (unlike Organizer) | Low | Step 10 explicitly omits description. Execute agent must not copy it blindly. |
| `VenueDetail` extends `VenueRow` — `event_count` in `VenueRow` is annotated at query time but not in `api_venue_detail` response | Low | `event_count` is an annotated field only on the list view. Do NOT extend `VenueRow` if it requires `event_count`. Instead, define `VenueDetail` as a standalone interface that shares fields manually or extends a leaner base. Adjust Step 5 accordingly: if `VenueRow.event_count` causes a TypeScript mismatch, define `VenueDetail` as a standalone type rather than `extends VenueRow`. |
| `Venue` model field names differ from assumed names | Low | Execute agent must verify `Venue` model fields in `apps/backend/events/models.py` before writing `api_venue_detail`. Relevant fields: `address`, `website`, `lat`, `lng`, `primary_type_display`, `rating`, `source`, `source_url`, `scraped_at`. |

**Backwards compatibility:** All `EventRow` additions are new fields (not renames/removals). Existing code that doesn't reference the new fields continues to work without changes.

**Rollback:** All changes are small and localized. If needed, revert `views.py` dict additions (Step 1), delete the new function (Step 2), remove the URL (Step 3), revert the two frontend `types.ts` fields (Step 4), remove `VenueDetail` (Step 5), remove `api.venue` (Step 6), revert the two `<td>` cells (Steps 7–8), and delete the two new route files (Steps 9–10). No DB migration to undo.

---

## Implementation Checklist

1. `apps/backend/events/views.py` — extend `select_related` to include `"organizer_ref"` in the `api_events` query (find the existing `select_related("venue")` call above line 302 and add `"organizer_ref"`).
2. `apps/backend/events/views.py` — add `"venue_slug": e.venue.slug if e.venue else None` and `"organizer_slug": e.organizer_ref.slug if e.organizer_ref_id else None` to the `results` dict at lines 305–318.
3. `apps/backend/events/views.py` — add `api_venue_detail(request, slug)` function after `api_organizer_detail` (~line 403), before `api_venues` (~line 406). Mirror structure of `api_organizer_detail`. Verify `Venue` field names from `models.py` before writing. Return 404 via `get_object_or_404`.
4. `apps/backend/events/urls.py` — insert `path("api/venues/<slug:slug>/", views.api_venue_detail, name="api_venue_detail")` immediately before `path("api/venues/", ...)` (currently line 25).
5. `apps/frontend/src/lib/types.ts` — add `venue_slug: string | null` and `organizer_slug: string | null` to `EventRow` (after `organizer: string` at line 35).
6. `apps/frontend/src/lib/types.ts` — add `VenueDetail` interface (standalone, not extending `VenueRow` if `event_count` mismatch) between `OrganizerDetail` and `VenueRow`. Include all fields returned by `api_venue_detail` plus `events[]` array items with `{ slug, name, starts_at, category, organizer }`.
7. `apps/frontend/src/lib/api.ts` — import `VenueDetail` type (add to line 7–17 import block). Add `venue: (slug: string, f?: Fetch) => get<VenueDetail>('/venues/${slug}/', f)` after `organizer:` line (line 48).
8. `apps/frontend/src/routes/events/+page.svelte` — replace venue `<td>` (line 87) and organizer `<td>` (line 88) with conditional link templates per Step 7 specification.
9. `apps/frontend/src/routes/venues/+page.svelte` — replace venue name `<td>` (line 100) with `<a href="/venues/{v.slug}" class="hover:text-accent">{v.name}</a>` wrapper.
10. Create directory `apps/frontend/src/routes/venues/[slug]/`. Create `+page.ts` mirroring the organizer slug load file, substituting `venue` for `organizer` and calling `api.venue(params.slug, fetch)`.
11. Create `apps/frontend/src/routes/venues/[slug]/+page.svelte` mirroring organizer detail layout: `$props`/`$derived`, `PageHeader`, back link, two-column grid, venue info card (name + Badge + website + address + rating + type + lat/lng + source footer), events table (name + starts_at + category + organizer), empty state.
12. Run verification suite: `cd apps/backend && ./venv/bin/python manage.py test events` (49 tests pass) → `makemigrations --check --dry-run` → `pnpm --filter frontend check` → `pnpm --filter frontend build` → manual curl checks (Steps 5–6) → manual click-through (Steps 7–10 in verification section).

---

## Notes

- **Organizer links are intentionally conditional.** Most events have a raw `organizer` string but no matched `organizer_ref` FK. The `organizer_slug` will be null for the majority of events. This is by design — no backfill or scraper changes are in scope.
- **`safeUrl` import**: The organizer detail page imports `safeUrl` from `$lib/utils/url`. The venue detail page must do the same.
- **`$lib/utils/url`** — verify the file exists at `apps/frontend/src/lib/utils/url.ts` (or `.js`) before referencing in Step 11. It is referenced in `routes/organizers/[slug]/+page.svelte` line 5, so it exists.
- **No `lat`/`lng` on `VenueRow`** — these fields are only in the detail response. Include them only in `VenueDetail`.

---

## Resume and Execution Handoff

**Plan file:** `/Volumes/Extreme_SSD/Projects/Python/veent-event-scraper/process/general-plans/active/events-clickable-fks-venue-pages_PLAN_17-06-26.md`

**To resume:** Pass this plan file path to `vc-execute-agent`. The checklist is ordered; execute steps 1–12 in sequence. Steps 1–4 are backend-only and can be verified independently before moving to frontend steps 5–12.

**Key anchor files for execute agent:**
- `apps/backend/events/views.py` (lines 279–318 for `api_events`, lines 370–403 for `api_organizer_detail` template, line 406 for insertion point of `api_venue_detail`)
- `apps/backend/events/urls.py` (lines 23–26 for URL insertion point)
- `apps/backend/events/models.py` (lines 85–108 for `Event` FK fields, Venue model for field names)
- `apps/frontend/src/lib/types.ts` (lines 26–37 `EventRow`, lines 55–65 `OrganizerDetail`, lines 67–77 `VenueRow`)
- `apps/frontend/src/lib/api.ts` (lines 38–52 for wrapper placement)
- `apps/frontend/src/routes/events/+page.svelte` (lines 74–91 for row cells)
- `apps/frontend/src/routes/venues/+page.svelte` (lines 98–110 for venue list rows)
- `apps/frontend/src/routes/organizers/[slug]/+page.ts` (template for new venue slug `+page.ts`)
- `apps/frontend/src/routes/organizers/[slug]/+page.svelte` (template for new venue slug `+page.svelte`)
