# Cagayan de Oro Venue Scraper (Google Places) + Map UI — PLAN

- **Date**: 2026-06-16
- **Complexity**: Simple (one-session feature)
- **Status**: ✅ VERIFIED (all 5 phases complete; 214 live CDO venues scraped + displayed)

## Overview

Add a Google Places–backed scraper that collects **event-relevant venues** in Cagayan de Oro
City and persists them as `Venue` rows, then surface that data in the existing UI (enhanced
venue list/detail) plus a new **Leaflet map view** with venue pins. The current scraper
framework is event-centric (venues are only saved when attached to an event), so this plan
adds a **venue-only persistence path**, a **stable Places `place_id` dedup key** on `Venue`,
and **minimal env-var config** for the API key. Coverage is **per-type Text Search**
(one search per venue type) — honest, approximate, not exhaustive (Places caps each query at
~60 results).

## Quick Links

- [Goals and Success Metrics](#goals-and-success-metrics)
- [Phase Completion Rules](#phase-completion-rules)
- [Execution Brief](#execution-brief)
- [Scope](#scope-inout)
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

**Goals**

1. Pull event-relevant venues for Cagayan de Oro City via Google Places and store them as `Venue` rows with full provenance.
2. Make re-running the scraper idempotent (no duplicate venues) via Google `place_id`.
3. Display venues in the existing UI with richer fields **and** a map view of pins.

**Success Metrics**

- `python manage.py scrape_venues` populates `Venue` rows for CDO across all configured types.
- Re-running the command produces `updated` counts, not new duplicate rows.
- `/venues/` shows address/coords/website/source; map renders a pin per geocoded venue.
- New automated tests pass (`save_venues` dedup + scraper parsing with mocked HTTP).

---

## Phase Completion Rules

A phase is NOT complete until:

1. **Integration Test** — Works with other system pieces
2. **Manual Test** — User can perform the action
3. **Data Verification** — Database/state changes confirmed
4. **Error Handling** — Failure cases handled gracefully
5. **User Confirmation** — User says "it works"

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

Five phases. **STOP and verify after each before proceeding.**

### Phase 1 — Env config + `place_id` schema ✅ VERIFIED

- **What happens:** Add minimal env-var reading for `PLACES_API_KEY` in `config/settings.py`
  (via `os.environ`); add a `place_id` field to `Venue` and a unique constraint mirroring
  `Event.external_id`; make the migration.
- **Test:** `python manage.py makemigrations` then `migrate` runs clean; `python manage.py shell -c "from django.conf import settings; print(bool(settings.PLACES_API_KEY))"` reflects the env var.
- **Verify:** `Venue` table has a `place_id` column (`sqlite3 db.sqlite3 ".schema events_venue"` or `python manage.py sqlmigrate events <n>`).
- **Done when:** Migration applied, no model check errors (`python manage.py check`).

### Phase 2 — Venue-only persistence path ✅ VERIFIED

- **What happens:** Add `save_venues(source, venues)` to `events/scrapers/base.py` mirroring
  `save_events`, upserting on `(source, place_id)` first, falling back to `(source, name)`;
  reuse `_unique_slug`. Extend `ScrapedVenue` with `place_id` (+ optional `phone`, `category`).
- **Test:** Unit test inserts two `ScrapedVenue` with same `place_id` → 1 created then 1 updated.
- **Verify:** `Venue.objects.count()` stable across repeated saves of the same `place_id`.
- **Done when:** `save_venues` dedup test green.

### Phase 3 — Google Places scraper + command ✅ VERIFIED (205 venues live; per-query failures now isolated)

- **What happens:** Add `events/scrapers/places.py` (`GooglePlacesVenueScraper`, source
  `google_places`) using `requests`: per-type **Text Search** ("<type> in Cagayan de Oro City,
  Philippines"), paginate `next_page_token` up to the cap, then **Place Details** for
  website/phone/geo/address. Add a `scrape_venues` management command that calls
  `save_venues`. (Keep it separate from `scrape`, which is event-only via `BaseScraper.run()`.)
- **Test:** `PLACES_API_KEY=... python manage.py scrape_venues --dry-run` then a real run; mocked-HTTP unit test for parsing.
- **Verify:** `Venue.objects.filter(source="google_places").count()` > 0; spot-check a row has address + lat/long.
- **Done when:** Command reports created/updated counts; parsing test green.

### Phase 4 — UI: enhanced venue pages ✅ VERIFIED

- **What happens:** Enhance `templates/events/venue_list.html` and `venue_detail.html` to show
  address, city, country, website, source, and coordinates; ensure `venue_list` view orders/
  filters sensibly (existing `?q=` search already covers name/city).
- **Test:** Visit `/venues/` and a venue detail page in the browser.
- **Verify:** New fields render for `google_places` venues; missing fields degrade gracefully.
- **Done when:** User confirms the pages show the scraped data.

### Phase 5 — UI: Leaflet map view ✅ VERIFIED

- **What happens:** Add a map (Leaflet + OpenStreetMap tiles, **no API key**) to the venue list
  page (or a dedicated `/venues/map/`), passing geocoded venues as JSON to the template; render
  one pin per venue with a popup linking to its detail page. Center on Cagayan de Oro.
- **Test:** Load the map page; confirm pins appear and popups link correctly.
- **Verify:** Number of pins == venues with non-null lat/long; clicking a pin opens detail.
- **Done when:** User visually confirms the map renders CDO venues.

**Expected Outcome**

- `scrape_venues` populates CDO event-relevant venues idempotently.
- Venue pages show full Places data; a Leaflet map shows pins.
- API key is read from env, never committed.
- Automated tests cover dedup + parsing.

---

## Scope (In/Out)

**In**

- Google Places Text Search + Place Details for CDO event-relevant venue types.
- Venue-only persistence + `place_id` dedup field/migration.
- Minimal env-var config for `PLACES_API_KEY`.
- Enhanced venue list/detail templates + Leaflet map view.
- Tests for `save_venues` dedup and scraper parsing (mocked HTTP).

**Out**

- Events from Places (not available) — no `Event` changes.
- Grid-tiling / exhaustive coverage (per-type Text Search only).
- Cross-source fuzzy venue merge (separate roadmap item).
- Full env-config system / production secrets management (only the one key here).
- Scheduling/cron (manual command run, per current product decision).

---

## Assumptions and Constraints

- **Provider:** Google Places API (Places API "New" or legacy Text Search — executor confirms which the key enables; plan assumes a Text Search + Details capable key).
- **Key handling:** `PLACES_API_KEY` from `os.environ` only; never hardcoded or committed. `.env` already git-ignored.
- **Coverage cap:** Each Text Search returns ≤ ~60 results (3 pages × 20). Per-type queries widen coverage but the dataset is **approximate, not exhaustive** — document this in command output/help.
- **Billing:** Places Text Search + Details are **billable**. Each venue costs one Search hit (paginated) + one Details hit. Keep the type list small; surface a count estimate before large runs.
- **City scope:** Query string targets "Cagayan de Oro City, Philippines"; results may include nearby spillover — acceptable.
- **Map:** Leaflet + OSM tiles (no key, attribution required). Loaded via CDN.

---

## Functional Requirements

1. A configurable list of event-relevant venue types (stadium, theater/performing-arts, convention/event center, night club, museum, auditorium, hotel-with-function-hall).
2. For each type: Text Search scoped to CDO, paginated to the cap.
3. For each result: fetch Place Details (address, lat/long, website, phone) and yield a `ScrapedVenue` carrying `place_id`.
4. `save_venues` upserts on `(source, place_id)`; no duplicate rows on re-run.
5. `scrape_venues` command runs the scraper and reports created/updated counts; supports `--dry-run`.
6. Venue list/detail templates display address, city, country, website, coords, source.
7. Map view renders one pin per geocoded venue, popup links to detail.

## Non-Functional Requirements

- Resilient HTTP: timeouts on all requests; per-type failures don't abort the whole run (mirror `scrape` command's per-scraper isolation).
- No secrets in code or VCS.
- Map degrades gracefully when a venue lacks coordinates (skipped, not broken).

---

## Acceptance Criteria

1. `PLACES_API_KEY` is read from env; absent key yields a clear error, not a crash.
2. `python manage.py scrape_venues` creates `Venue` rows with `source="google_places"`, populated address + lat/long for most rows.
3. Re-running `scrape_venues` yields `updated` (not duplicate `created`) for unchanged places.
4. `Venue` has a `place_id` column with a uniqueness guarantee per source.
5. `/venues/` shows the new fields; missing fields render gracefully.
6. Map view shows a pin per geocoded venue; clicking opens the venue detail page.
7. `python manage.py test events` passes, including a `save_venues` dedup test and a mocked-HTTP parsing test.
8. `python manage.py check` reports no issues.

---

## Implementation Checklist

1. [ ] Add `PLACES_API_KEY = os.environ.get("PLACES_API_KEY", "")` to `config/settings.py` (add `import os`).
2. [ ] Add `place_id = models.CharField(max_length=255, blank=True, db_index=True)` to `Venue` + `UniqueConstraint(fields=["source","place_id"], condition=Q(place_id__gt=""), name="unique_venue_source_place_id")`.
3. [ ] `python manage.py makemigrations events` → review → `migrate`.
4. [ ] Extend `ScrapedVenue` dataclass with `place_id: str = ""` (and optional `phone`, `category`).
5. [ ] Implement `save_venues(source, venues)` in `events/scrapers/base.py` (upsert on `(source, place_id)`, fallback `(source, name)`, reuse `_unique_slug`); refactor `_upsert_venue` to share logic if clean.
6. [ ] Write test in `events/tests.py`: same `place_id` saved twice → 1 created, 1 updated.
7. [ ] Create `events/scrapers/places.py`: `GooglePlacesVenueScraper(source="google_places")` with configurable type/query list, Text Search + pagination + Place Details, yielding `ScrapedVenue`. Use `requests` with timeouts; read key from `settings.PLACES_API_KEY`.
8. [ ] Add `events/management/commands/scrape_venues.py` calling `save_venues`; support `--dry-run` (fetch + print, no save) and clear error if key missing.
9. [ ] Write test: mocked `requests` responses → scraper yields expected `ScrapedVenue` fields.
10. [ ] Enhance `templates/events/venue_list.html` + `venue_detail.html` to show address/city/country/website/coords/source.
11. [ ] Add Leaflet map: pass `venues_json` (slug, name, lat, lng, url) from `venue_list` view; render Leaflet via CDN centered on CDO with a pin + popup per venue.
12. [ ] `python manage.py check` + `python manage.py test events` — all green.
13. [ ] Manual run: `PLACES_API_KEY=... python manage.py scrape_venues`, verify rows + UI + map.
14. [ ] Update `process/context/all-context.md` (new scraper, venue-only path, `place_id`, env var) during UPDATE PROCESS.

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Places API billing surprise | Small type list; `--dry-run`; document per-run cost; surface result counts before persisting. |
| ~60-result cap misread as "all venues" | Command help + output state coverage is approximate (per-type Text Search). |
| Places "New" vs legacy API shape mismatch | Executor confirms which API the key enables in Phase 3 before wiring full parsing; isolate request/parse in one module. |
| Venue name collisions across sources | Dedup primarily on `place_id`; name fallback only when `place_id` absent. |
| Map fails if no coords | Skip venues without lat/long; map still renders others. |
| Refactoring `_upsert_venue` breaks event scraping | Keep `save_events` behavior identical; cover with existing/added test before refactor. |

---

## Touchpoints

**Modify**
- `config/settings.py` — `import os`, `PLACES_API_KEY`.
- `events/models.py` — `Venue.place_id` + unique constraint.
- `events/scrapers/base.py` — `ScrapedVenue.place_id`, new `save_venues`, optional `_upsert_venue` refactor.
- `events/views.py` — `venue_list` passes `venues_json` for the map.
- `templates/events/venue_list.html`, `templates/events/venue_detail.html` — fields + map.
- `events/tests.py` — dedup + parsing tests (runner/conventions: `process/context/tests/all-tests.md`).

**Create**
- `events/scrapers/places.py` — Google Places venue scraper.
- `events/management/commands/scrape_venues.py` — runner command.
- `events/migrations/0002_*.py` — `place_id` migration (generated).

**Do NOT touch**
- `Event` model, `save_events` behavior, `scrape` command semantics, existing event views/templates.

---

## Public Contracts

- **`save_venues(source: str, venues: Iterable[ScrapedVenue]) -> dict`** — returns `{"source","created","updated"}` (mirrors `save_events`).
- **`ScrapedVenue`** — gains `place_id` (and optional `phone`, `category`); existing fields unchanged so event scrapers keep working.
- **CLI:** `python manage.py scrape_venues [--dry-run]` — new command; `scrape` unchanged.
- **Env:** `PLACES_API_KEY` (read-only at runtime; never committed).
- **URL/UI:** `/venues/` enhanced; map either inline on `/venues/` or new `/venues/map/` (executor picks; document choice).

## Blast Radius

- **Data layer:** new nullable/blank `Venue.place_id` + additive constraint — backward compatible; existing venues keep working (blank `place_id`).
- **Scraper framework:** additive (`save_venues`); event path must remain byte-for-byte behaviorally identical.
- **UI:** venue templates only; event pages untouched.
- **External:** outbound calls to Google Places (billable) + Leaflet/OSM CDN + tiles.

## Verification Evidence

Required before claiming success:
- `python manage.py check` — clean.
- `python manage.py test events` — green (dedup + parsing tests included).
- DB proof: `Venue.objects.filter(source="google_places").count()` > 0 and a sample row with address + lat/long (paste query + result).
- Idempotency proof: run `scrape_venues` twice; second run shows `updated`, `Venue` count stable.
- UI proof: screenshot/observation of `/venues/` with new fields and the map with pins.

## Resume and Execution Handoff

A resumed executor should read, in order:
1. This plan file (status strip + Implementation Checklist for current position).
2. `process/context/all-context.md` (Scraper Framework + Data Model sections).
3. `events/scrapers/base.py` (understand `save_events`/`_upsert_venue` before adding `save_venues`).
4. `events/models.py` (Event's `external_id` pattern to mirror for `Venue.place_id`).

State is tracked by the checklist checkboxes and the per-phase status markers above. Phases are
ordered by dependency: 1 (schema/env) → 2 (persistence) → 3 (scraper/command) → 4 (UI fields) →
5 (map). Do not start a phase until the prior one is ✅ VERIFIED.

---

## Cursor + RIPER-5 Guidance

- **Cursor Plan mode:** import the Implementation Checklist; execute phase by phase; after each phase update the status strip and run the verification checklist.
- **RIPER-5:**
  - RESEARCH/INNOVATE — done (decisions captured above).
  - PLAN — this file; awaiting approval.
  - EXECUTE — implement exactly as planned; check in at ~50% (after Phase 3).
  - VERIFY — after each phase, stop and run the verification checklist.
  - If scope expands (e.g. grid tiling, full env system), pause and convert to COMPLEX.
- **After each phase: STOP and verify before proceeding.**

---

**Next step:** Review this plan. When ready, say **"ENTER EXECUTE MODE"** and name this plan
(`cdo-venue-scraper_PLAN_16-06-26.md`) to begin Phase 1. Each phase requires verification before
proceeding to the next.
