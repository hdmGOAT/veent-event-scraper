# Event → Organizer Foreign Key PLAN

**Date:** 2026-06-17
**Complexity:** SIMPLE (one session)
**Status:** ⏳ PLANNED

---

## Overview

Add a nullable `organizer_ref` FK from `Event` to `Organizer`, migrate existing data using URL
and name matching, wire the FK into `save_events` for future scrape runs, and surface it in
`EventAdmin`. The existing `organizer` (CharField) and `organizer_url` (URLField) columns are
**kept as denormalized fallback** — scrapers that yield organizer names without a matching
`Organizer` record still need them. This change reduces redundancy for events that do have a
matching `Organizer` row while preserving backward compatibility everywhere.

---

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
- [Integration Notes](#integration-notes)
- [Touchpoints](#touchpoints)
- [Public Contracts](#public-contracts)
- [Blast Radius](#blast-radius)
- [Verification Evidence](#verification-evidence)
- [Resume and Execution Handoff](#resume-and-execution-handoff)

---

## Goals and Success Metrics

- `Event.organizer_ref` FK exists and is populated wherever a matching `Organizer` row is found.
- The data migration links rows correctly (URL match first, name match as fallback).
- `save_events` resolves and sets `organizer_ref` on every new or updated Event going forward.
- `EventAdmin` exposes `organizer_ref` for editing alongside the read-only denormalized fields.
- The `organizer_display_name` property works correctly in templates and the shell.
- All existing tests pass; the migration applies cleanly on a fresh `migrate`.

---

## Phase Completion Rules

A phase is NOT complete until:

1. **Integration Test** — Works with the existing scraper framework and Django ORM end-to-end.
2. **Manual Test** — Admin UI shows `organizer_ref` and linked records correctly.
3. **Data Verification** — Django shell query confirms matched counts match expected values.
4. **Error Handling** — Ambiguous name matches are skipped (not raised); `organizer_ref` stays
   `None` rather than pointing to the wrong organizer.
5. **User Confirmation** — User visually confirms the admin and shell spot-check outputs.

Status markers:

| Marker | Meaning |
|--------|---------|
| ⏳ PLANNED | Not started |
| 🔨 CODE DONE | Written, not E2E tested |
| 🧪 TESTING | Currently being tested |
| ✅ VERIFIED | Tested and user confirmed |
| 🚧 BLOCKED | Blocker exists |

---

## Execution Brief

### Phase A — Schema migration ⏳ PLANNED

**What happens:** Add `organizer_ref` FK field to `Event` in `models.py`, generate the schema
migration (`0008_…`), and add the `organizer_display_name` property. No data is touched.

**Test:** `./venv/bin/python manage.py migrate --run-syncdb` on a clean DB must succeed with
zero errors. `./venv/bin/python manage.py test events` must still be all green.

**Verify:** In Django shell — `from events.models import Event; print(Event._meta.get_field('organizer_ref'))` should return a `ForeignKey` instance.

**Done when:** Migration applied, all tests green, FK visible in shell introspection.

---

### Phase B — Data migration ⏳ PLANNED

**What happens:** Write a hand-coded Django data migration (`0009_…`) that runs two passes over
existing `Event` rows: URL-normalized match against `Organizer.website`, then case-insensitive
unambiguous name match. Prints matched/unmatched counts via `schema_editor.connection`.

**Test:** Run `./venv/bin/python manage.py migrate` (applies both 0008 and 0009). Then in shell
verify a sample of linked events has `organizer_ref` set and unlinked events have `organizer_ref=None`.

**Verify (shell):**
```
from events.models import Event
Event.objects.filter(organizer_ref__isnull=False).count()   # > 0 if Organizers exist
Event.objects.filter(organizer_ref__isnull=True, organizer__gt='').count()  # expected unlinked
```

**Done when:** Migration applies without error; spot-check shows plausible match counts.

---

### Phase C — save_events update ⏳ PLANNED

**What happens:** Extend `save_events` in `events/scrapers/base.py` to attempt organizer
resolution (URL then name) immediately after the event upsert. Only links to existing
`Organizer` rows — never creates new ones.

**Test:** Trigger a dry run by calling `save_events` in the shell with a `ScrapedEvent` whose
`organizer_url` matches an existing `Organizer.website`. Confirm the saved `Event.organizer_ref`
is populated.

**Verify:**
```
from events.scrapers.base import ScrapedEvent, save_events
save_events("test_src", [ScrapedEvent(name="Test", organizer_url="<known organizer URL>")])
from events.models import Event
print(Event.objects.get(source="test_src").organizer_ref)
```

**Done when:** `organizer_ref` is set for events with a matching organizer; `None` otherwise.

---

### Phase D — Admin update ⏳ PLANNED

**What happens:** Add `organizer_ref` to `EventAdmin` fieldsets in the "Host / Organizer" group
with `raw_id_fields` (avoids loading all organizers in a select). Keep `organizer` and
`organizer_url` visible as `readonly_fields`.

**Test:** Open `/admin/events/event/` in the browser, open any event. Confirm the "Host /
Organizer" section shows the `organizer_ref` widget and the read-only denormalized fields.

**Done when:** Admin loads without error; FK widget renders; read-only fields remain visible.

---

### Expected Outcome

- `Event` has a `organizer_ref` FK (nullable, `SET_NULL`).
- Data migration has linked all matchable events to their organizer.
- Future scrape runs auto-link events during `save_events`.
- Admin exposes the FK with read-only fallback fields visible.
- `organizer_display_name` property usable from any template or shell expression.
- All tests green; both migrations apply cleanly from scratch.

---

## Scope

**In scope:**
- `events/models.py` — add FK field and property
- `events/migrations/0008_event_organizer_ref.py` — schema migration
- `events/migrations/0009_link_event_organizer.py` — data migration
- `events/scrapers/base.py` — resolve FK in `save_events`
- `events/admin.py` — expose FK in `EventAdmin`

**Out of scope:**
- Removing `organizer` or `organizer_url` CharField/URLField (kept as denormalized fallback)
- Creating new `Organizer` records from event scrapers
- Modifying the `Venue` review UI or any template files
- Cross-source fuzzy dedup across organizers

---

## Assumptions and Constraints

- Django 6.0.6 + SQLite dev DB. FK with `SET_NULL` is safe on SQLite.
- URL normalization uses Python `urllib.parse` — no third-party lib added.
- Name match is unambiguous-only: if two `Organizer` rows share the same name (different
  sources), skip — do not link.
- `organizer_ref` is never written by `save_organizers`; only by `save_events` and the data
  migration.
- The `status` field on `Organizer` is never touched by this change.
- Running `manage.py test events` is the full test gate (21 existing tests).

---

## Functional Requirements

- `Event.organizer_ref` is a nullable FK to `Organizer`, `on_delete=SET_NULL`,
  `related_name="events"`, `null=True`, `blank=True`.
- Data migration Pass 1: normalize `Event.organizer_url` and `Organizer.website` by
  lower-casing scheme+host and stripping a trailing slash. Match on equality.
- Data migration Pass 2: for still-unlinked events, case-insensitive match on
  `Event.organizer` vs `Organizer.name`. Skip if `Organizer.objects.filter(name__iexact=name)`
  returns more than one result.
- `save_events` runs the same two-pass resolution on every event after upsert.
  Uses `update_fields=["organizer_ref"]` when updating an existing event row.
- `Event.organizer_display_name` property returns `organizer_ref.name` if FK set, else
  `organizer` (the CharField).
- `EventAdmin`: `organizer_ref` in the "Host / Organizer" fieldset; `raw_id_fields`
  (or `autocomplete_fields` — see note in Integration Notes); `organizer` and `organizer_url`
  moved to `readonly_fields`.

---

## Non-Functional Requirements

- No new pip dependency introduced.
- URL normalization is pure stdlib (`urllib.parse.urlparse`).
- Data migration is idempotent: re-running it (rollback + re-apply) produces the same result.
- `save_events` resolution adds at most two additional DB reads per event (one `filter` for
  URL, one `filter` for name if URL misses) — acceptable at current scraping volume.

---

## Acceptance Criteria

1. `python manage.py migrate` applies migrations 0008 and 0009 cleanly on a fresh SQLite DB.
2. `python manage.py test events` exits zero (all 21 existing tests pass, plus any new tests).
3. `Event.objects.filter(organizer_ref__isnull=False).count()` returns a number greater than
   zero after the data migration (assuming Organizer rows exist in the DB).
4. An `Event` whose `organizer_url` matches an `Organizer.website` (URL-normalized) has its
   `organizer_ref` set after re-running `save_events` with the same scraped data.
5. An `Event` whose `organizer` name is shared by two Organizer rows has `organizer_ref=None`
   (ambiguous match skipped).
6. `event.organizer_display_name` returns `organizer_ref.name` when FK is set; falls back to
   `event.organizer` when not.
7. Django admin `/admin/events/event/<id>/change/` renders without error and shows
   `organizer_ref` widget alongside read-only `organizer` / `organizer_url`.
8. `organizer` and `organizer_url` are still present on `Event._meta` (not removed).
9. `Organizer.status` is unchanged by the data migration and by `save_events`.
10. Running both migrations in reverse (`migrate events 0007`) and forward again completes
    without error.

---

## Implementation Checklist

- [ ] **1. Update `events/models.py`**
  - Add `organizer_ref = models.ForeignKey("Organizer", on_delete=models.SET_NULL, null=True, blank=True, related_name="events")` to the `Event` class, after the existing `organizer_url` field.
  - Add `organizer_display_name` property to `Event`.
  - No other field changes.

- [ ] **2. Generate schema migration**
  - Run `./venv/bin/python manage.py makemigrations events --name event_organizer_ref`
  - Confirm the generated file is `events/migrations/0008_event_organizer_ref.py` and contains only the `AddField` for `organizer_ref`.

- [ ] **3. Write data migration `0009_link_event_organizer.py`**
  - Create `events/migrations/0009_link_event_organizer.py` by hand (not auto-generated).
  - Dependencies: `[("events", "0008_event_organizer_ref")]`.
  - `forwards` function:
    - Import `urllib.parse` (inside function to keep migration self-contained).
    - Define `normalize_url(url)` — lowercases scheme+host, strips trailing slash, returns `""` for blank.
    - Build a dict `{normalized_website: organizer_pk}` from `Organizer.objects.all()` (use `apps.get_model`).
    - Pass 1: for each `Event` with non-blank `organizer_url`, normalize it and look up in the dict. Set `organizer_ref_id = pk` and `bulk_update` in batches of 500.
    - Pass 2: for still-unlinked events with non-blank `organizer`, group Organizer names (case-insensitive); for unambiguous matches set `organizer_ref_id`; bulk_update.
    - Print counts: URL-matched, name-matched, unmatched (use `print` — acceptable in data migration).
  - `backwards` function: sets `organizer_ref_id = None` for all events (reversible).

- [ ] **4. Apply both migrations and verify**
  - Run `./venv/bin/python manage.py migrate`
  - Confirm no errors. Open the shell and run:
    ```python
    from events.models import Event
    print(Event.objects.filter(organizer_ref__isnull=False).count())
    print(Event.objects.filter(organizer_ref__isnull=True, organizer__gt='').count())
    ```
  - Record the counts.

- [ ] **5. Update `events/scrapers/base.py` — `save_events`**
  - Add a private helper `_resolve_organizer(organizer_url: str, organizer_name: str) -> Organizer | None` at module level (below `_upsert_venue`).
    - Same two-pass logic as data migration (normalize URL, then name).
    - Returns an `Organizer` instance or `None`.
    - Uses `Organizer.objects.filter(...)` — already imported at top of file.
  - In `save_events`, after the event create/update block, call `_resolve_organizer(se.organizer_url, se.organizer)`.
  - For a newly created event: the `Event.objects.create(...)` call already has `organizer_ref=None` by default; after create, if resolution returns an organizer, set and save with `update_fields=["organizer_ref"]`.
  - For an updated existing event: include `organizer_ref` in the `fields` dict so it is overwritten on each re-scrape (resolution is deterministic).
  - Do not create or modify any `Organizer` row.

- [ ] **6. Run tests**
  - Run `./venv/bin/python manage.py test events`
  - All 21 tests must pass. Fix any failures before proceeding.

- [ ] **7. Update `events/admin.py` — `EventAdmin`**
  - In the `"Host / Organizer"` fieldset, change `fields` to `("organizer_ref", "organizer", "organizer_url")`.
  - Add `organizer_ref` to `raw_id_fields` (tuple). Note: `autocomplete_fields` would require `search_fields` on `OrganizerAdmin` — that already exists, so either option is valid; `raw_id_fields` requires no extra config and avoids loading all organizers into a `<select>`.
  - Move `organizer` and `organizer_url` into `readonly_fields` (append to the existing tuple).
  - Keep all other fieldsets unchanged.

- [ ] **8. Manual admin spot-check**
  - Start dev server: `./venv/bin/python manage.py runserver`
  - Open `/admin/events/event/` — list view loads.
  - Open any event — form renders with `organizer_ref` widget and read-only `organizer`/`organizer_url`.
  - If an event has a linked organizer, the FK widget shows the organizer pk/name.

- [ ] **9. Final test run**
  - Run `./venv/bin/python manage.py test events` — must still be all green.
  - Optionally add one new `TestCase` in `events/tests.py` covering:
    - `_resolve_organizer` returns correct organizer on URL match.
    - `_resolve_organizer` returns `None` on ambiguous name match.
    - `organizer_display_name` property returns FK name when set, CharField fallback when not.

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `related_name="events"` conflicts with `Venue.events` related name | Low — different model source | Both are `related_name="events"` but accessed on different parent models (`venue.events`, `organizer_ref.events` / `organizer.events`); Django allows this | 
| URL normalization false positives (e.g., two different organizers at the same hostname) | Very low for current data | Keep URL match scoped to `Organizer.website` domain-level; if it becomes a problem, scope to full path |
| Name match links to wrong organizer when same name spans sources | Mitigated by ambiguity check | Skip when `count > 1` regardless of source |
| Reverse migration loses data | Acceptable | Backwards just nulls the FK; data can be re-linked by re-running migration forward |
| `raw_id_fields` UX is bare (only pk shown) | Low impact | Acceptable for admin-only surface; can upgrade to `autocomplete_fields` later without a migration |

---

## Integration Notes

- **Migration ordering:** 0008 must be applied before 0009. Both must precede any code that
  reads `organizer_ref`. The standard `migrate` command handles this via `dependencies`.
- **`save_events` helper import:** `Organizer` is already imported at the top of `base.py`
  (`from events.models import Event, Organizer, Venue`) — no new import needed.
- **`autocomplete_fields` alternative:** `OrganizerAdmin` already declares `search_fields`, so
  `autocomplete_fields = ("venue", "organizer_ref")` on `EventAdmin` is a valid choice instead
  of `raw_id_fields`. Either works; plan specifies `raw_id_fields` for simplicity.
- **`urllib.parse` in migration:** must be imported inside the `forwards` function body, not
  at module top level, to keep the migration self-contained per Django conventions.
- **Existing tests:** All 21 tests in `events/tests.py` test the `google_places` scraper, venue
  dedup, `verification_status` invariants, and the `/review/` UI. None of them test
  `organizer_ref` — they will pass unchanged. New tests for `_resolve_organizer` and
  `organizer_display_name` are recommended but not blocking.

---

## Touchpoints

| File | Change type | Notes |
|------|-------------|-------|
| `events/models.py` | Add field + property | `Event.organizer_ref` FK; `organizer_display_name` property |
| `events/migrations/0008_event_organizer_ref.py` | New (auto-generated) | Schema migration |
| `events/migrations/0009_link_event_organizer.py` | New (hand-written) | Data migration |
| `events/scrapers/base.py` | Modify | Add `_resolve_organizer`; extend `save_events` |
| `events/admin.py` | Modify | `EventAdmin` fieldsets and `raw_id_fields` |
| `events/tests.py` | Modify (optional) | New tests for `_resolve_organizer` + property |

---

## Public Contracts

- `Event.organizer_ref` — new nullable FK. Any code reading `Event` objects may now access
  `.organizer_ref` and `.organizer_ref_id`. The CharField `organizer` and URLField
  `organizer_url` remain on the model unchanged.
- `Event.organizer_display_name` — new read-only property. Not a database column; safe to
  call on any `Event` instance.
- `save_events` return value — unchanged (`{"source": str, "created": int, "updated": int}`).
  The FK resolution is a side-effect on the saved rows, not surfaced in the return dict.
- `Organizer.events` (reverse relation) — now accessible as a `RelatedManager` on every
  `Organizer` instance. Previously non-existent.
- Django admin form for `Event` — adds `organizer_ref` widget; `organizer` and `organizer_url`
  become read-only (no longer editable via the form).

---

## Blast Radius

- **`events/models.py`** — adding a field and a property. Additive; existing columns unchanged.
- **`events/migrations/`** — two new files. Standard Django migration; reversible.
- **`events/scrapers/base.py`** — `save_events` gains two extra DB reads per event
  (negligible at current scraping volume). No change to `save_organizers` or `save_venues`.
- **`events/admin.py`** — `EventAdmin` only. `VenueAdmin` and `OrganizerAdmin` untouched.
- **`events/tests.py`** — all existing tests unaffected (they do not create `Event` rows with
  organizer fields). Optional new tests only.
- **Templates** — no template changes required. `organizer_display_name` is available but
  not used by any template unless explicitly adopted later.
- **No migration to any other app.** `config/` and `templates/` are untouched.

---

## Verification Evidence

Before calling implementation done, the executor must produce:

1. Shell output of `python manage.py migrate` — zero errors, shows 0008 and 0009 applied.
2. Shell output of `python manage.py test events` — "OK" with 21+ tests.
3. Shell snippet showing `Event.objects.filter(organizer_ref__isnull=False).count()` value.
4. Admin screenshot or description: event change form shows `organizer_ref` widget and
   read-only `organizer`/`organizer_url` fields.
5. Shell confirmation of `organizer_display_name` property:
   ```python
   e = Event.objects.filter(organizer_ref__isnull=False).first()
   print(e.organizer_display_name, e.organizer_ref.name)  # must match
   e2 = Event.objects.filter(organizer_ref__isnull=True).first()
   print(e2.organizer_display_name, e2.organizer)          # must match
   ```

---

## Resume and Execution Handoff

**If resuming mid-execution**, check migration state first:

```bash
./venv/bin/python manage.py showmigrations events
```

- If 0008 is not applied: start at checklist step 2.
- If 0008 applied but 0009 not: start at checklist step 3.
- If both applied: start at checklist step 5 (base.py update).
- If base.py done: start at checklist step 7 (admin).

**Files to re-read before resuming:**
- `events/models.py` (confirm FK field shape)
- `events/migrations/0008_…` (confirm field name used in migration)
- `events/scrapers/base.py` (confirm `_resolve_organizer` helper presence)

**Do not re-run the data migration** if 0009 is already applied — rolling it back and
re-applying is safe but unnecessary unless the data migration logic changed.

---

## Cursor + RIPER-5 Guidance

- Import the Implementation Checklist above into Cursor Plan mode directly.
- Execute each checkbox in order; do not skip ahead to admin changes before the migrations
  are applied and verified.
- After step 4 (migration verification) and step 6 (test run), stop and confirm green before
  continuing.
- If the test run at step 6 fails: fix the failure before touching admin.py.
- If scope expands (e.g., templates need updating, or organizer creation from events is
  requested), pause and reclassify as COMPLEX before continuing.
- RIPER-5 EXECUTE must follow this plan with 100% fidelity. Any deviation requires a plan
  update first.
