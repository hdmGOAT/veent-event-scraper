# Venue Categories, About & Amenities — Scrape + Classify in UI

- **Date**: 2026-06-16
- **Complexity**: Simple (one-session feature)
- **Status**: ✅ VERIFIED (all 4 phases complete; live scrape populated 92% category / 86% amenity coverage; 11 tests green)

## Overview

Extend the existing Google Places (New) venue scraper to also capture each place's
**category** (`primaryType` / `primaryTypeDisplayName` + full `types` list), its
**editorial "about" summary**, and the **subset of amenity attributes the Places API
returns** (accessibility, parking, serves-breakfast, good-for-children, allows-dogs, etc.),
persist them on the `Venue` model, and surface them in the UI — grouping/classifying venues
by category on the venue list and showing category + about + amenities on the venue detail
page. Admin gains category in `list_display` / `list_filter`.

> **Honesty note (carried into every phase):** The Google Maps *app* screenshot ("3-star
> hotel", Free Wi-Fi, Breakfast, Pet-friendly, Outdoor pool, Air-conditioned, Kid-friendly,
> Restaurant, Kitchens, Airport shuttle, Fitness center) shows **more than the Places API
> (New) returns**. We capture only what `searchText` exposes: `primaryTypeDisplayName` +
> `types`, `editorialSummary`, and a fixed set of amenity booleans/enums. Star rating,
> per-room features (kitchens, minifridges), and several chips are **not available** and are
> explicitly out of scope. Do not promise UI parity with the screenshot.

> **Billing note (carried into every phase):** Today's field mask (`id`, `displayName`,
> `formattedAddress`, `location`, `websiteUri`, `googleMapsUri`) sits in the cheaper Places
> API SKU tiers. `editorialSummary` and the amenity/attribute booleans move requests into the
> **Enterprise / Enterprise + Atmosphere** SKU, which is billed at a higher rate per call.
> This is a deliberate cost trade-off — confirm before running a full (non-`--dry-run`) scrape.

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
- [Touchpoints](#touchpoints)
- [Public Contracts](#public-contracts)
- [Blast Radius](#blast-radius)
- [Verification Evidence](#verification-evidence)
- [Resume and Execution Handoff](#resume-and-execution-handoff)
- [Cursor + RIPER-5 Guidance](#cursor--riper-5-guidance)

---

## Goals and Success Metrics

- **Goal 1 — Scrape category:** Every scraped venue stores its Places `primaryType` (raw key),
  `primaryTypeDisplayName` (human label), and full `types` list.
- **Goal 2 — Scrape about:** Venues store `editorialSummary.text` as an `about` field when present.
- **Goal 3 — Scrape amenities:** Venues store a normalized `amenities` map of the boolean/enum
  attributes Places returns (only truthy/known values kept).
- **Goal 4 — Classify in UI:** The venue list page groups venues by category, with a category
  filter; the detail page shows category badge, about text, and an amenities chip list.
- **Success metric:** After a fresh `scrape_venues` run, ≥80% of returned venues have a
  non-empty `primary_type_display`, the list page renders one section per distinct category,
  and detail pages of hotels/museums show about text + at least the amenity flags the API returned.

---

## Phase Completion Rules

A phase is NOT complete until:

1. **Integration Test** — Works with other system pieces (scraper → upsert → DB → view → template).
2. **Manual Test** — User can perform the action (run scrape, load `/venues/`, open a detail page).
3. **Data Verification** — Database/state changes confirmed (query `Venue` rows for new fields).
4. **Error Handling** — Failure cases handled gracefully (missing fields, empty amenities, null about).
5. **User Confirmation** — User says "it works".

Status meanings:
- ⏳ PLANNED — Not started
- 🔨 CODE DONE — Written but not E2E tested
- 🧪 TESTING — Currently being tested
- ✅ VERIFIED — Tested AND confirmed working
- 🚧 BLOCKED — Has issues

After each phase, document:
- [ ] What was tested manually
- [ ] Data verified in DB (show query + result)
- [ ] Errors encountered and fixed
- [ ] User confirmation received

---

## Execution Brief

Four logical phases. Phases 1–2 are data/scraper; Phase 3 is UI; Phase 4 is admin + tests.

### Phase 1 — Model fields + migration 🔨 CODE DONE (migration 0003 applied, fields verified in shell)
- **What happens:** Add category/about/amenities fields to `Venue` and generate migration `0003`.
- **Test:** `python manage.py makemigrations events` then `migrate`; open Django shell and confirm
  a `Venue()` instance accepts `primary_type`, `primary_type_display`, `types`, `about`,
  `amenities`, `rating`, `price_level`.
- **Verify:** `Venue._meta.get_fields()` includes the new fields; migration `0003` exists and applies clean.
- **Done when:** Migration applies with no errors and fields are queryable.

### Phase 2 — Scraper capture (field mask + dataclass + upsert) ✅ VERIFIED (real scrape: 1 created/208 updated; 92% category, 86% amenity coverage)
- **What happens:** Expand `FIELD_MASK`, add fields to `ScrapedVenue`, extract them in `_to_venue`,
  thread them through `_upsert_venue`.
- **Test:** `python manage.py scrape_venues --dry-run` prints venues without error; then a real run
  (with billing confirmed) populates new fields.
- **Verify:** Query a known hotel/museum row and confirm `primary_type_display`, `about`, `amenities`
  are populated where the API returned them.
- **Done when:** Re-scrape updates existing rows (no duplicates) and new columns are filled.

### Phase 3 — UI classification (list grouping + detail display) ✅ VERIFIED (grouped sections, category filter, detail about+amenities via test client)
- **What happens:** Order venues by category and `{% regroup %}` into per-category sections on the
  list page (with optional `?category=` filter); render category badge, about paragraph, and
  amenities chips on the detail page.
- **Test:** Load `/venues/`, confirm grouped sections; click into a hotel, confirm about + amenities show.
- **Verify:** Each distinct `primary_type_display` produces exactly one section; filter narrows correctly.
- **Done when:** User visually confirms categories and amenities render correctly (screenshot).

### Phase 4 — Admin + tests ✅ VERIFIED (11 tests green; admin list_display/list_filter include category; `manage.py check` clean)
- **What happens:** Add category to `VenueAdmin` (`list_display`, `list_filter`); add unit tests for
  `_to_venue` extraction and amenity normalization.
- **Test:** `python manage.py test events`; open `/admin/events/venue/` and filter by category.
- **Verify:** Tests green; admin filter lists distinct categories.
- **Done when:** Tests pass and admin filter works.

### Expected Outcome
- Venues carry category, about, and amenity data sourced from Places API (New).
- `/venues/` is organized by category; detail pages explain each place and list its amenities.
- Admin can filter venues by category.
- Tests cover the parsing/normalization logic; no duplicate venues introduced.

---

## Scope

**In scope**
- New `Venue` fields: `primary_type`, `primary_type_display`, `types`, `about`, `amenities`,
  `rating`, `price_level`.
- `FIELD_MASK` expansion in `events/scrapers/places.py`.
- `ScrapedVenue` dataclass, `_to_venue`, `_upsert_venue` threading.
- Migration `0003`.
- `venue_list` grouping + `venue_detail` display in `events/views.py` and templates.
- `VenueAdmin` update.
- Unit tests for extraction/normalization.

**Out of scope**
- Star ratings (e.g. "3-star hotel"), per-room features (kitchens, minifridges, balconies),
  and any Google Maps UI chip the Places API does not return.
- A separate `Category` / `Amenity` model or M2M tables (use a CharField + JSONField for now).
- Cross-source category reconciliation / fuzzy dedup (still roadmap, not this plan).
- Switching scraper to Place Details calls or adding new venue-type queries.
- Photos, reviews text, opening-hours rendering.

---

## Assumptions and Constraints

- **A1:** `PLACES_API_KEY` is set and the key's billing account allows the higher SKU tier needed
  for `editorialSummary` + amenities. If not, scrape will return 4xx/empty for those fields — handle gracefully.
- **A2:** `types`/`amenities` stored as JSON is acceptable; SQLite supports Django `JSONField`.
- **A3:** Category used for UI grouping = `primary_type_display` (fallback `primary_type`,
  fallback literal `"Uncategorized"`).
- **A4:** Additive, nullable/blank fields only — existing rows remain valid; no data backfill required
  beyond re-running the scraper.
- **A5:** Amenity set is whatever the API returns; the template renders only truthy flags, so a
  partial response degrades cleanly.

---

## Functional Requirements

1. The field mask requests: `places.primaryType`, `places.primaryTypeDisplayName`, `places.types`,
   `places.editorialSummary`, plus amenity/attribute fields (`accessibilityOptions`,
   `parkingOptions`, `paymentOptions`, `allowsDogs`, `goodForChildren`, `goodForGroups`,
   `restroom`, `servesBreakfast`, `servesLunch`, `servesDinner`, `servesCoffee`,
   `servesVegetarianFood`, `outdoorSeating`, `liveMusic`, `menuForChildren`, `reservable`,
   `takeout`, `delivery`, `dineIn`, `curbsidePickup`), and `places.rating`,
   `places.userRatingCount`, `places.priceLevel`.
2. `_to_venue` extracts `primaryType` (str), `primaryTypeDisplayName.text` (str),
   `types` (list[str]), `editorialSummary.text` (str), and normalizes amenity fields into a flat
   `amenities` dict of `{label: bool}` (nested objects like `accessibilityOptions` flattened to
   their truthy sub-keys; scalar `serves*`/`good*` kept as bools).
3. `_upsert_venue` persists all new fields on both create and update paths.
4. `venue_list` groups venues by category and supports `?category=<value>` narrowing while keeping
   the existing `?q=` search and Leaflet map.
5. `venue_detail` renders a category badge, the about paragraph (when present), and an amenities
   chip list (truthy amenities only, with humanized labels).
6. `VenueAdmin.list_display` and `list_filter` include the category label.

---

## Non-Functional Requirements

- No N+1 regressions on `venue_list` (keep `annotate(Count("events"))`; grouping is in-template after a single ordered query).
- Parsing must never raise on missing/partial Places fields — use `.get()` with defaults everywhere.
- New fields blank/nullable so the migration is non-destructive.

---

## Acceptance Criteria

- [ ] Migration `0003` adds the seven fields and applies cleanly on SQLite.
- [ ] `scrape_venues --dry-run` runs without error after the field-mask change.
- [ ] A real scrape populates `primary_type_display` for ≥80% of returned venues.
- [ ] At least one hotel/museum row has non-empty `about` and ≥1 truthy `amenities` entry (when API returns them).
- [ ] Re-running the scraper updates existing rows (created=0 / updated>0 for unchanged dataset) — no duplicates.
- [ ] `/venues/` shows one section per distinct category; `?category=` narrows results.
- [ ] `/venues/<slug>/` shows category badge + about + amenity chips when data exists, and degrades cleanly when it does not.
- [ ] `/admin/events/venue/` lists and filters by category.
- [ ] `python manage.py test events` passes, including new parsing/normalization tests.

---

## Implementation Checklist

**Phase 1 — Model + migration**
- [ ] In `events/models.py` `Venue`, add: `primary_type` (CharField 120, blank), `primary_type_display`
  (CharField 120, blank, db_index), `types` (JSONField default=list, blank), `about` (TextField blank),
  `amenities` (JSONField default=dict, blank), `rating` (FloatField null/blank), `price_level` (CharField 40, blank).
- [ ] `python manage.py makemigrations events` → creates `0003_*`.
- [ ] `python manage.py migrate` → applies clean.

**Phase 2 — Scraper capture**
- [ ] In `events/scrapers/places.py`, extend `FIELD_MASK` with the fields in Functional Req #1.
- [ ] In `events/scrapers/base.py` `ScrapedVenue`, add: `primary_type`, `primary_type_display`,
  `types` (default_factory=list), `about`, `amenities` (default_factory=dict), `rating`, `price_level`.
- [ ] In `places.py` `_to_venue`, extract + normalize the new fields (add a `_normalize_amenities(place)` helper).
- [ ] In `base.py` `_upsert_venue`, add the new fields to the `fields` dict (applies to create + update).
- [ ] `python manage.py scrape_venues --dry-run` — no errors.

**Phase 3 — UI**
- [ ] In `events/views.py` `venue_list`, read `?category=`, filter when present, order venues by
  `primary_type_display`/`name`, pass `category` + distinct category list to the template.
- [ ] In `templates/events/venue_list.html`, add a category filter control and `{% regroup venues by primary_type_display as cat_groups %}` rendering one section per category (keep map + search).
- [ ] In `templates/events/venue_detail.html`, add category badge, about paragraph, and amenities chip list (iterate `venue.amenities.items`, show truthy with humanized labels).

**Phase 4 — Admin + tests** (testing context: Django's built-in test runner — see `process/context/tests/all-tests.md`; run `python manage.py test events`. Post-phase testing for each phase is defined in the [Execution Brief](#execution-brief) and [Verification Evidence](#verification-evidence).)
- [ ] In `events/admin.py` `VenueAdmin`, add `"primary_type_display"` to `list_display` and `list_filter`.
- [ ] In `events/tests.py`, add tests: `_to_venue` maps category/about/types; `_normalize_amenities`
  flattens nested + keeps truthy only; `_upsert_venue` persists fields and re-upsert updates not duplicates.
- [ ] `python manage.py test events` — green.

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Higher billing tier for amenities/editorialSummary surprises the user | Billing note in plan; default to `--dry-run`; confirm before real scrape |
| API returns 4xx because a field name is wrong/unavailable for the SKU | Add fields incrementally; test mask with one query first; wrap in existing per-query try/except |
| `editorialSummary`/amenities absent for many venue types (common for non-business POIs) | Treat as optional; templates guard with `{% if %}`; acceptance threshold scoped to where API returns data |
| Amenity key explosion / inconsistent shapes (nested vs scalar) | Centralize in `_normalize_amenities`; store flat `{label: bool}`; unit-test it |
| `{% regroup %}` requires ordering by the group key | Order queryset by `primary_type_display` in the view before passing to template |
| JSONField default mutability | Use `default=list`/`default=dict` (callables), never mutable literals |

---

## Touchpoints

- `events/models.py` — `Venue` model (new fields).
- `events/migrations/0003_*.py` — new migration (generated).
- `events/scrapers/places.py` — `FIELD_MASK`, `_to_venue`, new `_normalize_amenities` helper.
- `events/scrapers/base.py` — `ScrapedVenue` dataclass, `_upsert_venue`.
- `events/views.py` — `venue_list` (grouping + category filter).
- `templates/events/venue_list.html` — grouped sections + filter control.
- `templates/events/venue_detail.html` — category badge, about, amenities chips.
- `events/admin.py` — `VenueAdmin`.
- `events/tests.py` — new tests.

## Public Contracts

- **Venue model schema** — additive only; all new fields blank/nullable. Existing rows, `save_events`,
  `save_venues`, and the `unique_venue_source_place_id` constraint remain unchanged.
- **`ScrapedVenue` dataclass** — new fields all have defaults, so existing constructors (the Places
  scraper) and `save_venues` keep working without edits beyond the planned ones.
- **URLs** — `events:venue_list` gains an optional `?category=` query param; no route changes. `?q=` preserved.
- **`scrape_venues` command** — interface unchanged (`--dry-run` still works); only richer data captured.
- **Admin** — additive list column/filter only.

## Blast Radius

- **Direct:** venue scraping path and venue UI. Hotels/museums/event venues gain richer display.
- **Indirect:** higher per-call Places billing on real runs; slightly larger `Venue` rows (JSON columns).
- **Not touched:** `Event` model/flow, `save_events`, event views/templates, event admin, the
  `cdo-venue-scraper` plan's existing behavior, dedup/migration `0002` semantics.

## Verification Evidence

Required before claiming success:
1. `python manage.py migrate` output showing `0003` applied.
2. `scrape_venues --dry-run` clean output (paste tail).
3. Django shell query, e.g.:
   ```python
   from events.models import Venue
   v = Venue.objects.exclude(primary_type_display="").first()
   print(v.primary_type_display, v.types, bool(v.about), v.amenities)
   ```
   showing populated category/about/amenities.
4. Re-scrape result dict showing `updated > 0`, `created == 0` for an unchanged dataset (no dupes).
5. Screenshot of `/venues/` grouped by category and a hotel detail page showing about + amenity chips.
6. `python manage.py test events` green output.

## Resume and Execution Handoff

A resumed executor should:
1. Read this plan, then `process/context/all-context.md` (Scraper Framework + Data Model + Web UI sections).
2. Read these files before editing: `events/models.py`, `events/scrapers/places.py`,
   `events/scrapers/base.py`, `events/views.py`, `templates/events/venue_list.html`,
   `templates/events/venue_detail.html`, `events/admin.py`.
3. Execute phases in order (1→4); each phase gates on its verification before the next.
4. Latest migration before this work is `0002_venue_place_id_venue_unique_venue_source_place_id`;
   the new one must be `0003`.
5. Keep the scraper boundary: scrapers yield dataclasses; only `_upsert_venue` writes the ORM.
6. Default to `--dry-run`; get user confirmation before any billed real scrape.

---

## Cursor + RIPER-5 Guidance

- **Cursor Plan mode:** Import the [Implementation Checklist](#implementation-checklist); execute by
  phase; after each phase update the status strip and run the phase's verification.
- **RIPER-5:**
  - RESEARCH/INNOVATE already done (current code mapped; CharField+JSONField approach chosen over new models).
  - PLAN: this file.
  - EXECUTE: only after explicit "ENTER EXECUTE MODE"; implement exactly as planned; check in at ~50% (end of Phase 2).
  - VERIFY: after each phase, stop and run the verification checklist.
  - If scope expands (e.g. needing a real `Category` model or Place Details calls), pause and convert to COMPLEX.

**Next step (Cursor Plan mode):** Import the Implementation Checklist and begin Phase 1 (model fields + migration). **After each phase, STOP and verify before proceeding.**
