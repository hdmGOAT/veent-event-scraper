# Deduplication System — Implementation Plan

**Date:** 18-06-26
**Complexity:** COMPLEX (multiple new files, DB mutations, FK remapping, test additions)
**Status:** READY FOR EXECUTE

---

## Objective

Build a cross-source deduplication system for `Event`, `Venue`, and `Organizer` records.
The system detects duplicate rows using URL normalization and exact field-match grouping,
selects a winner based on field richness, merges the best non-null fields from all losers
into the winner, remaps all FK references from losers to the winner, and hard-deletes the
losing rows. Deduplication runs both on demand (management command) and automatically as
a post-save hook during scraping.

---

## Scope

### In scope
- `apps/backend/events/dedup.py` — shared normalization + duplicate-finder + merge utilities
- `apps/backend/events/management/commands/deduplicate.py` — `manage.py deduplicate` command
- `apps/backend/events/scrapers/base.py` — add `_dedup_after_save` hook called from `save_events`, `save_venues`, `save_organizers`
- `apps/backend/events/tests.py` — new test classes for all dedup code paths

### Out of scope (deferred)
- Fuzzy / Levenshtein name matching
- Admin UI review queue before merging
- `EventGroup` canonical model or any new DB schema
- Frontend changes in `apps/frontend/`
- Celery / async dedup job scheduling

---

## Key Files

| File | Action | Estimated lines |
|---|---|---|
| `apps/backend/events/dedup.py` | CREATE | ~260 |
| `apps/backend/events/management/commands/deduplicate.py` | CREATE | ~130 |
| `apps/backend/events/scrapers/base.py` | MODIFY — add `_dedup_after_save`, wire into `save_events`, `save_venues`, `save_organizers` | +65 |
| `apps/backend/events/tests.py` | MODIFY — add 4 new test classes | +200 |

---

## Model Reference

Key model fields (from `apps/backend/events/models.py`):

**Venue**: `id`, `name`, `slug` (unique), `city`, `website`, `place_id`, `source`, `agents_primary_types` (protected), `verification_status` (protected), `created_at`, `updated_at`

**Event**: `id`, `name`, `slug` (unique), `url`, `starts_at`, `venue` (FK→Venue), `organizer_ref` (FK→Organizer), `external_id`, `source`, `agent_categories` (protected), `created_at`, `updated_at`

**Organizer**: `id`, `name`, `slug` (unique), `website`, `city`, `source`, `external_id`, `status` (protected), `agents_primary_types` (protected), `created_at`, `updated_at`

**ScraperRun**: Has no FK to `Event`, `Venue`, or `Organizer` — no remapping needed.

---

## Architecture Decisions (locked)

1. **Merge strategy:** Hard-delete losers. Before deletion, merge best non-null fields from ALL losers into winner. Remap all FK references from losers to winner before deleting.
2. **Winner selection:** Row with the highest richness score (count of non-null, non-empty fields). Tiebreak = oldest `created_at`.
3. **Protected fields (never overwritten on merge):** `agent_categories`, `agents_primary_types`, `verification_status`, `status` (Organizer), `slug`, `created_at`, `updated_at`.
4. **Inline auto-dedup scope:** Only URL-normalized exact match triggers auto-merge in `_dedup_after_save`. Name+date match is management command only (too expensive at scrape time).
5. **Failure isolation:** `_dedup_after_save` is wrapped in `try/except` — failure must never abort a scrape run.
6. **Transaction safety:** Each merge group in the management command is wrapped in `transaction.atomic()`.

---

## Implementation Order

### Step 1 — Create `apps/backend/events/dedup.py`

**1a. Module docstring and imports**
- `from __future__ import annotations`
- Imports: `re`, `unicodedata`, `urllib.parse`, `datetime`, `logging`, Django ORM (`Event`, `Venue`, `Organizer`)

**1b. Normalization helpers**

`normalize_name(name: str) -> str`
- Lowercase the input
- Apply `unicodedata.normalize("NFKD", name)` then encode/decode to drop combining characters (strip accents)
- `re.sub(r"[^\w\s]", "", name)` to strip punctuation
- `re.sub(r"\s+", " ", name).strip()` to collapse whitespace
- Return empty string if input is None or blank

`normalize_url(url: str) -> str`
- Extend the existing `_normalize_url` in `base.py` — do NOT copy it; call `base._normalize_url` as a first pass, then apply additional steps below
- Use `urllib.parse.urlparse` on the already-lowercased/stripped result
- Strip the protocol/scheme entirely: keep only netloc + path + query (produce a scheme-less key so `http://` and `https://` match)
- Strip UTM params: remove any query key whose name starts with `utm_`
- Sort remaining query params alphabetically
- Strip trailing slash from the path component
- Return empty string for blank input

`normalize_date(dt) -> date | None`
- Accept `datetime` or `date` or `None`
- If `datetime`, convert to UTC via `dt.astimezone(timezone.utc)` then return `.date()`
- If already a `date`, return as-is
- Return `None` for `None` input

`normalize_city(city: str) -> str`
- Lowercase, strip whitespace
- Return empty string for None/blank

**1c. Richness score helper**

`_richness_score(obj) -> int`
- Iterate over `obj._meta.get_fields()`; count fields that are `CharField`, `TextField`, `URLField`, `EmailField`, `FloatField`, `JSONField` and have a non-null, non-empty, non-default value
- For JSONField: skip if value equals the field's `default` (empty list `[]` or empty dict `{}`)
- For FloatField/nullable fields: count if not None
- Return integer count

**1d. Winner selection helper**

`_select_winner(pks: list[int], model) -> tuple[int, list[int]]`
- Fetch all objects for `pks` using `model.objects.filter(pk__in=pks)`
- Score each with `_richness_score`
- Sort by `(-score, created_at)` — highest score first, oldest creation tiebreak
- Return `(winner_pk, [loser_pk, ...])` where losers = all non-winner PKs

**1e. Duplicate-finder functions**

`find_event_duplicates(queryset=None) -> list[list[int]]`
- Default `queryset = Event.objects.all()`
- **Pass 1 — URL normalized match (high confidence):**
  - Build `{normalize_url(e.url): [pk, ...]}` mapping over all events with non-blank `url`
  - Any key with 2+ PKs forms a duplicate group
- **Pass 2 — name + date + city exact match:**
  - Build `{(normalize_name(e.name), normalize_date(e.starts_at), normalize_city(e.venue.city if e.venue else "")): [pk, ...]}` — requires prefetch of `venue` via `queryset.select_related("venue")`
  - Any key with 2+ PKs forms a duplicate group
- De-duplicate groups: if two groups from Pass 1 and Pass 2 share any PKs, merge them into one group
- For each merged group, call `_select_winner(pks, Event)` to order as `[winner_pk, *loser_pks]`
- Return list of these ordered lists; skip singleton groups

`find_venue_duplicates(queryset=None) -> list[list[int]]`
- Default `queryset = Venue.objects.all()`
- **Pass 1 — website URL normalized match:**
  - Build `{normalize_url(v.website): [pk, ...]}` for venues with non-blank `website`
  - Any key with 2+ PKs → group
- **Pass 2 — name + city exact match:**
  - Build `{(normalize_name(v.name), normalize_city(v.city)): [pk, ...]}` for all venues
  - Any key with 2+ PKs → group
- Merge overlapping groups; select winner; return ordered lists

`find_organizer_duplicates(queryset=None) -> list[list[int]]`
- Default `queryset = Organizer.objects.all()`
- **Pass 1 — website URL normalized match:**
  - Build `{normalize_url(o.website): [pk, ...]}` for organizers with non-blank `website`
- **Pass 2 — name exact match:**
  - Build `{normalize_name(o.name): [pk, ...]}` for all organizers
- Merge overlapping groups; select winner; return ordered lists

**1f. Merge functions**

`_merge_fields(winner, losers: list, protected_fields: set[str]) -> None`
- `_SKIP_FIELDS = {"id", "slug", "created_at", "updated_at"} | protected_fields`
- For each field in `winner._meta.get_fields()`: skip if field name in `_SKIP_FIELDS` or is a relation
- For each remaining field: if winner's value is null/empty AND any loser has a non-null/non-empty value for that field, set winner's value to the first such non-null loser value
- Do NOT call `winner.save()` — caller handles save

`merge_events(winner_id: int, loser_ids: list[int]) -> Event`
- `PROTECTED = {"agent_categories"}`
- Fetch `winner = Event.objects.get(pk=winner_id)` and `losers = list(Event.objects.filter(pk__in=loser_ids))`
- If winner's `venue` is None and any loser has a non-null `venue`, set `winner.venue = first_non_null_loser_venue`
- If winner's `organizer_ref` is None and any loser has a non-null `organizer_ref`, set `winner.organizer_ref = first_non_null_loser_organizer_ref`
- Call `_merge_fields(winner, losers, PROTECTED)`
- `winner.save()`
- No FK remapping needed (Event is the entity being merged; nothing else has a FK to Event in current schema)
- `Event.objects.filter(pk__in=loser_ids).delete()`
- Return `winner`

`merge_venues(winner_id: int, loser_ids: list[int]) -> Venue`
- `PROTECTED = {"agents_primary_types", "verification_status"}`
- Fetch winner and losers
- Call `_merge_fields(winner, losers, PROTECTED)`
- `winner.save()`
- Remap FK: `Event.objects.filter(venue__in=loser_ids).update(venue_id=winner_id)`
- `Venue.objects.filter(pk__in=loser_ids).delete()`
- Return `winner`

`merge_organizers(winner_id: int, loser_ids: list[int]) -> Organizer`
- `PROTECTED = {"agents_primary_types", "status"}`
- Fetch winner and losers
- Call `_merge_fields(winner, losers, PROTECTED)`
- `winner.save()`
- Remap FK: `Event.objects.filter(organizer_ref__in=loser_ids).update(organizer_ref_id=winner_id)`
- `Organizer.objects.filter(pk__in=loser_ids).delete()`
- Return `winner`

---

### Step 2 — Create `apps/backend/events/management/commands/deduplicate.py`

**2a. Command class definition**
- Subclass `BaseCommand`
- `help = "Find and merge duplicate Event, Venue, and Organizer records."`

**2b. `add_arguments`**
```
--entity   choices: events, venues, organizers, all   default: all
--dry-run  store_true — find and report, no DB writes
--verbose  store_true — print each merged group
```

**2c. `handle` method structure**
- Dispatch to `_run_events`, `_run_venues`, `_run_organizers` based on `--entity`
- Print a final summary table:
  ```
  Entity       Groups  Merged  Deleted
  Events           N       N        N
  Venues           N       N        N
  Organizers       N       N        N
  ```

**2d. `_run_entity(self, finder_fn, merger_fn, label, options)` generic helper**
- Call `finder_fn()` to get list of groups
- If `dry_run`: print each group, return counts without touching DB
- For each group: wrap in `transaction.atomic()`:
  - `winner_id, loser_ids = group[0], group[1:]`
  - Call `merger_fn(winner_id, loser_ids)`
  - If `verbose`: log `Merged {loser_ids} → winner {winner_id} ({label})`
- Return `(groups_found, merged_count, deleted_count)`

**2e. Error handling per group**
- If `merger_fn` raises, catch the exception inside the `transaction.atomic()` block, log `logger.error(...)`, increment an error counter, and continue to the next group (the atomic block rolls back only the failed group)

---

### Step 3 — Modify `apps/backend/events/scrapers/base.py`

**3a. Add import at top**
- Add `from events import dedup as _dedup` inside a `try/except ImportError` block (dedup module may not exist yet during initial migration) — no, actually use a plain import since dedup.py will always exist after this plan executes. Use a conditional import only if needed for circular import safety. Prefer importing inside the function body to avoid any circular import risk.

**3b. Add `_dedup_after_save` function** (after `_categorize_after_save`, same pattern)

```
def _dedup_after_save(entity: str, ids: list[int]) -> None:
```
- `entity` is one of `"events"`, `"venues"`, `"organizers"`
- Signature mirrors `_categorize_after_save` — takes the relevant PKs
- Dispatch table:
  - `"events"`: `queryset = Event.objects.filter(pk__in=ids)` → `find_event_duplicates(queryset)` → URL-match groups only (discard name+date groups; too expensive inline) — filter groups where the match was URL-based by checking if any two events in the group share a `normalize_url(url)` value
  - `"venues"`: `queryset = Venue.objects.filter(pk__in=ids)` → `find_venue_duplicates(queryset)` (both passes are cheap) → merge any found groups
  - `"organizers"`: `queryset = Organizer.objects.filter(pk__in=ids)` → `find_organizer_duplicates(queryset)` → merge any found groups
- For each group in results: call corresponding `merge_*` function
- Entire function body wrapped in `try/except Exception` — log warning, swallow

**Implementation note for inline event dedup — URL-only filter:**
- In `_dedup_after_save("events", ...)`, after calling `find_event_duplicates(queryset)`, filter the returned groups to only those where the duplicate was detected via URL match. The simplest approach: run only a URL-based pass inline rather than the full `find_event_duplicates`. Extract the URL-grouping logic from `find_event_duplicates` into a private helper `_group_by_url(qs, url_field)` that both `find_event_duplicates` and the inline path can use.

**3c. Wire `_dedup_after_save` into save functions**

In `save_events`:
- After the existing call to `_categorize_after_save(result)` in `BaseScraper.run()` — actually, `_dedup_after_save` should be called from within `save_events` itself (not `BaseScraper.run`) so it also fires when `save_events` is called directly (e.g., from tests or other scrapers)
- At the end of `save_events`, before `return`, add: `_dedup_after_save("events", event_ids)`
- This must be outside the per-event for-loop

In `save_venues`:
- Collect venue IDs during `_upsert_venue` calls (already returns `(venue, created)` — collect the PK)
- At the end of `save_venues`, add: `_dedup_after_save("venues", venue_ids)`
- Requires small refactor: build `venue_ids: list[int]` alongside the `created`/`updated` counters

In `save_organizers`:
- Collect organizer IDs created/updated during the loop (already track `existing.pk` and new org PK)
- At the end, add: `_dedup_after_save("organizers", organizer_ids)`
- Requires small refactor: build `organizer_ids: list[int]` alongside counters

---

### Step 4 — Add tests to `apps/backend/events/tests.py`

**4a. `NormalizationTests(TestCase)`** — no DB needed, all pure function calls
- `test_normalize_name_empty_string` — assert `normalize_name("") == ""`
- `test_normalize_name_none` — assert `normalize_name(None) == ""`
- `test_normalize_name_accents` — assert `normalize_name("Café Évènement") == "cafe evenement"`
- `test_normalize_name_punctuation` — assert `normalize_name("Hello, World!") == "hello world"`
- `test_normalize_name_extra_whitespace` — assert `normalize_name("  foo  bar  ") == "foo bar"`
- `test_normalize_url_empty` — assert `normalize_url("") == ""`
- `test_normalize_url_strips_protocol` — `normalize_url("https://example.com/")` and `normalize_url("http://example.com/")` return the same value
- `test_normalize_url_strips_trailing_slash` — `normalize_url("https://example.com/page/")` == `normalize_url("https://example.com/page")`
- `test_normalize_url_strips_utm_params` — `normalize_url("https://example.com?utm_source=fb&id=1")` == `normalize_url("https://example.com?id=1")`
- `test_normalize_url_sorts_query_params` — `normalize_url("https://x.com?b=2&a=1")` == `normalize_url("https://x.com?a=1&b=2")`
- `test_normalize_date_datetime` — assert returns correct UTC date
- `test_normalize_date_none` — assert returns `None`
- `test_normalize_city_strips_whitespace` — assert lowercase + strip

**4b. `FindDuplicatesTests(TestCase)`** — uses DB; sets up known duplicate groups
- `setUp` — create known duplicate venues, organizers, events using `Venue.objects.create(...)` with controlled data
- `test_find_venue_duplicates_by_website` — two venues with same website URL (different case, trailing slash), assert one group returned with both PKs
- `test_find_venue_duplicates_by_name_city` — two venues with same name+city, assert group found
- `test_find_venue_duplicates_no_duplicates` — distinct venues, assert empty list returned
- `test_find_organizer_duplicates_by_website` — two organizers same website
- `test_find_organizer_duplicates_by_name` — two organizers same name
- `test_find_event_duplicates_by_url` — two events with same URL (one has trailing slash), assert group
- `test_find_event_duplicates_by_name_date_city` — two events same name, same date, same venue city, assert group
- `test_find_duplicates_winner_is_first` — seed two rows where one clearly has more filled fields; assert winner (first PK in group) is the richer row

**4c. `MergeTests(TestCase)`** — uses DB; tests actual merge + delete
- `test_merge_venues_remaps_fk` — create two duplicate venues; link an event to the loser venue; call `merge_venues(winner, [loser])`; assert event now points to winner; assert loser venue deleted
- `test_merge_organizers_remaps_fk` — same pattern for organizer_ref FK
- `test_merge_events_hard_deletes_loser` — create two duplicate events; call `merge_events(winner, [loser])`; assert loser event deleted; assert DB count decremented by 1
- `test_merge_fills_missing_fields` — winner has blank `description`, loser has description; after merge winner has loser's description
- `test_merge_does_not_overwrite_existing_fields` — winner already has `description`; loser has different description; after merge winner still has its own description
- `test_merge_protected_fields_not_overwritten_venue` — winner has `verification_status=VERIFIED`, loser has `verification_status=REJECTED`; after merge winner still `VERIFIED`
- `test_merge_protected_fields_not_overwritten_event` — winner has `agent_categories=["Music"]`; loser has `agent_categories=["Sports"]`; after merge winner still `["Music"]`
- `test_merge_protected_fields_not_overwritten_organizer` — winner has `status=confirmed`; loser has `status=pending`; after merge winner still `confirmed`
- `test_merge_slug_preserved` — winner's slug unchanged after merge

**4d. `DedupCommandTests(TestCase)`** — tests management command invocation
- `test_dry_run_makes_no_db_changes` — seed two duplicate venues; call `call_command("deduplicate", "--entity", "venues", "--dry-run")`; assert venue count unchanged
- `test_entity_venues_only_deduplicates_venues` — seed duplicate venues AND duplicate events; run with `--entity venues`; assert venues deduped but event count unchanged
- `test_entity_events_only_deduplicates_events` — inverse of above
- `test_entity_all_runs_all_three` — seed duplicates for all three entities; run without `--entity`; assert all three reduced
- `test_summary_output_format` — capture stdout; assert output contains "Groups", "Merged", "Deleted" header line
- `test_error_in_one_group_does_not_abort_others` — mock `merge_venues` to raise on first call; assert second group still processed; assert no crash

---

## Touchpoints

| Surface | Change |
|---|---|
| `apps/backend/events/dedup.py` | New module — pure library, imported by command and base.py |
| `apps/backend/events/management/commands/deduplicate.py` | New management command |
| `apps/backend/events/scrapers/base.py` | `save_events`, `save_venues`, `save_organizers` each gain a `_dedup_after_save` call at their end; `save_venues` and `save_organizers` gain a `venue_ids`/`organizer_ids` accumulator |
| `apps/backend/events/tests.py` | 4 new test classes appended |

---

## Public Contracts

- `dedup.normalize_name(s: str | None) -> str` — deterministic, pure
- `dedup.normalize_url(url: str) -> str` — deterministic, pure; scheme-stripped, UTM-stripped, query-sorted
- `dedup.normalize_date(dt) -> date | None` — UTC date extraction
- `dedup.normalize_city(city: str | None) -> str` — deterministic, pure
- `dedup.find_event_duplicates(queryset=None) -> list[list[int]]` — first PK in each sub-list is winner
- `dedup.find_venue_duplicates(queryset=None) -> list[list[int]]`
- `dedup.find_organizer_duplicates(queryset=None) -> list[list[int]]`
- `dedup.merge_events(winner_id: int, loser_ids: list[int]) -> Event`
- `dedup.merge_venues(winner_id: int, loser_ids: list[int]) -> Venue`
- `dedup.merge_organizers(winner_id: int, loser_ids: list[int]) -> Organizer`
- Management command: `manage.py deduplicate [--entity events|venues|organizers|all] [--dry-run] [--verbose]`

---

## Blast Radius

**FK constraint risk:** `merge_venues` calls `Event.objects.filter(venue__in=loser_ids).update(venue_id=winner_id)` before deleting losers. If any new model ever adds a FK to `Venue` or `Organizer`, that FK will NOT be remapped automatically. Mitigation: the merge functions must be reviewed and updated if the schema gains new FKs in the future.

**Slug uniqueness:** Hard-deleting a losing row releases its slug; the winner keeps its own slug. No slug reassignment is needed. Risk: very low.

**`unique_source_external_id` / `unique_venue_source_place_id` constraints:** Two rows in the same duplicate group may have the same `(source, external_id)` pair, which should be impossible given the existing unique constraint — but if constraint enforcement was ever bypassed, `merge_events` will attempt to save the winner with a conflicting `(source, external_id)`. The merge must not copy `source` or `external_id` from a loser onto the winner. These fields are effectively identity fields; add `"source"`, `"external_id"`, `"place_id"` to `_SKIP_FIELDS` inside `_merge_fields`.

**Transaction isolation:** Each merge group in the management command runs in its own `transaction.atomic()`. A failure in one group rolls back only that group and logs an error; subsequent groups continue. This prevents partial-merge corruption.

**`_dedup_after_save` failure does not abort scraping:** Entire function is try/except. A bug in dedup code will emit a warning log but will not raise to the caller, preserving the existing `_categorize_after_save` isolation pattern.

**Hard deletes are irreversible:** Once `merge_*` is called outside `--dry-run`, the losing rows are permanently deleted. See Rollback section.

**Auto_now fields:** `updated_at` uses `auto_now=True` — it is automatically updated when `winner.save()` is called. This is correct and expected behavior.

---

## Failure Modes and Mitigations

| Failure | Mitigation |
|---|---|
| Merge function crashes mid-group | `transaction.atomic()` per group rolls back; error logged; next group continues |
| `_dedup_after_save` crashes | `try/except Exception` swallows; warning logged; scrape continues |
| Two rows with same `(source, external_id)` somehow exist | `source`, `external_id`, `place_id` in `_SKIP_FIELDS` prevents copying identity fields; unique constraint prevents re-creation |
| Winner deletion race (concurrent scrape + dedup) | No concurrent execution path exists (no Celery, single-thread Django dev server); Neon Postgres row-level locking provides safety for WSGI multi-worker scenarios |
| `find_event_duplicates` called on large table (performance) | The management command path loads PKs into memory; for very large tables this may be slow. Mitigation: queryset filtering by `--entity` and future addition of `--source` flag (not in this plan). No index changes needed for the current data volume. |

---

## Rollback Plan

Hard deletes are not reversible through application logic. Before the first real (non-dry-run) execution:

1. Take a full database dump: `pg_dump $DATABASE_URL > dedup_pre_run_$(date +%Y%m%d).sql`
2. Run `manage.py deduplicate --dry-run` and review the output
3. Only after reviewing the dry-run report, execute without `--dry-run`
4. If a restore is needed: `psql $DATABASE_URL < dedup_pre_run_<date>.sql`

There is no application-level "undo" — the backup is the only rollback path.

---

## Verification Evidence

### Automated tests
- Run `python manage.py test events.tests.NormalizationTests` — all pass
- Run `python manage.py test events.tests.FindDuplicatesTests` — all pass
- Run `python manage.py test events.tests.MergeTests` — all pass
- Run `python manage.py test events.tests.DedupCommandTests` — all pass
- Run full test suite `python manage.py test events` — all 97 existing tests + new tests pass; no regressions

### Manual verification steps
1. `python manage.py deduplicate --dry-run --verbose` — inspect output; confirm groups are sensible
2. `python manage.py deduplicate --entity venues --dry-run` — check venue group count
3. Note venue/event/organizer row counts before and after:
   - `python manage.py shell -c "from events.models import *; print(Venue.objects.count(), Event.objects.count(), Organizer.objects.count())"`
4. Run `python manage.py deduplicate --entity venues --verbose` and confirm row count decreased
5. Run full test suite again post-execution to confirm no FK violations

### Success criteria (observable)
- Dry-run produces output without error and shows at least 0 groups (no crash is the minimum bar)
- At least one known duplicate pair (seed data or real data) is merged correctly: FK remapped, loser deleted, winner fields enriched
- All 97 pre-existing tests continue to pass
- New test suite reaches at least 120 total tests (97 + ~23 new)
- No `IntegrityError` or `OperationalError` raised during merge run on staging data

---

## Resume and Execution Handoff

**Plan file:** `process/general-plans/active/deduplication_PLAN_18-06-26.md`

**Execution order for vc-execute-agent:**
1. Create `apps/backend/events/dedup.py` (Step 1 — all sub-steps 1a through 1f in order)
2. Create `apps/backend/events/management/commands/deduplicate.py` (Step 2)
3. Modify `apps/backend/events/scrapers/base.py` (Step 3)
4. Add test classes to `apps/backend/events/tests.py` (Step 4)
5. Run tests and verify

**Critical execution notes:**
- Read `apps/backend/events/scrapers/base.py` before modifying it (the existing `_normalize_url` and `_categorize_after_save` are authoritative templates)
- Read `apps/backend/events/management/commands/categorize_events.py` as the structural template for the new management command
- Read `apps/backend/events/tests.py` before adding new test classes (understand existing test style, imports, and helpers like `_fake_cli`)
- Do NOT remove or modify any existing tests
- The `save_venues` and `save_organizers` refactor (adding `_ids` accumulators) must preserve existing return dict structure exactly: `{"source": ..., "created": ..., "updated": ...}`
- The `save_events` return dict must also remain unchanged: `{"source": ..., "created": ..., "updated": ..., "event_ids": [...]}`

---

## Implementation Checklist

1. Create `apps/backend/events/dedup.py` — add module docstring and all imports
2. Implement `normalize_name(name)` in `dedup.py`
3. Implement `normalize_url(url)` in `dedup.py` (builds on `base._normalize_url`, scheme-stripping, UTM removal, query sort)
4. Implement `normalize_date(dt)` in `dedup.py`
5. Implement `normalize_city(city)` in `dedup.py`
6. Implement `_richness_score(obj)` in `dedup.py`
7. Implement `_select_winner(pks, model)` in `dedup.py`
8. Implement `_group_by_url(qs, url_field)` private helper in `dedup.py` (shared by `find_event_duplicates` and `_dedup_after_save` inline path)
9. Implement `find_event_duplicates(queryset=None)` in `dedup.py`
10. Implement `find_venue_duplicates(queryset=None)` in `dedup.py`
11. Implement `find_organizer_duplicates(queryset=None)` in `dedup.py`
12. Implement `_merge_fields(winner, losers, protected_fields)` in `dedup.py` — include `source`, `external_id`, `place_id` in `_SKIP_FIELDS`
13. Implement `merge_events(winner_id, loser_ids)` in `dedup.py`
14. Implement `merge_venues(winner_id, loser_ids)` in `dedup.py`
15. Implement `merge_organizers(winner_id, loser_ids)` in `dedup.py`
16. Create `apps/backend/events/management/commands/deduplicate.py` — `Command` class with `add_arguments`
17. Implement `_run_entity` helper in `deduplicate.py` — finder→groups→atomic merge loop with error handling
18. Implement `handle` in `deduplicate.py` — dispatch by `--entity`, print summary table
19. Read `apps/backend/events/scrapers/base.py` fully before modifying
20. Add `_dedup_after_save(entity, ids)` function to `base.py` — with try/except, dispatching to dedup functions by entity name; inline events path uses URL-only via `_group_by_url`
21. Refactor `save_venues` in `base.py` — add `venue_ids: list[int]` accumulator; call `_dedup_after_save("venues", venue_ids)` before return
22. Refactor `save_organizers` in `base.py` — add `organizer_ids: list[int]` accumulator; call `_dedup_after_save("organizers", organizer_ids)` before return
23. Add `_dedup_after_save("events", event_ids)` call in `save_events` in `base.py` before the return statement
24. Read `apps/backend/events/tests.py` fully before modifying
25. Add `NormalizationTests` class to `tests.py` with all 13 test methods
26. Add `FindDuplicatesTests` class to `tests.py` with all 8 test methods
27. Add `MergeTests` class to `tests.py` with all 9 test methods
28. Add `DedupCommandTests` class to `tests.py` with all 6 test methods
29. Run `python manage.py test events` and confirm all tests pass
30. Run `python manage.py deduplicate --dry-run --verbose` and confirm no crash and readable output
