# Deduplication System — Overview

## Why deduplication is needed

Veent runs 17 scrapers across multiple event platforms (Eventbrite, Luma, AllEvents, Ticket2Me, etc.). The same real-world event is often listed on several platforms simultaneously. Without dedup, every scrape creates separate rows for the same event, venue, or organizer.

**Existing within-source dedup** (built into the Django models via unique constraints):

| Entity | Constraint | Behaviour |
|---|---|---|
| `Event` | `(source, external_id)` | Re-scraping the same event from the same source updates the row in place |
| `Venue` | `(source, place_id)` | Same source + same Google Place ID → upsert |
| `Organizer` | `(source, external_id)` | Same source + same ID → upsert |

**What this system adds — cross-source dedup:**

The same event scraped from Eventbrite and from AllEvents used to produce two separate `Event` rows. This system detects and merges them.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  Two-layer dedup system                     │
│                                                             │
│  Layer 1 — Real-time (base.py)                              │
│  After each scrape run, _dedup_after_save() runs a fast     │
│  URL-only pass on the freshly saved records and merges      │
│  any obvious duplicates before the scraper returns.         │
│                                                             │
│  Layer 2 — On-demand (deduplicate.py script)                │
│  Full two-pass matching (URL + name/city/date) across the   │
│  entire table. Run manually or on a schedule to clean up    │
│  existing data and catch anything Layer 1 missed.           │
└─────────────────────────────────────────────────────────────┘
```

### File layout

```
apps/backend/
├── scripts/
│   ├── dedup.py          ← normalization helpers + finders + merge functions
│   │                        pure Python + psycopg2; no Django dependency
│   └── deduplicate.py    ← standalone CLI script (DATABASE_URL via .env)
└── events/
    └── scrapers/
        └── base.py       ← _dedup_after_save() — Layer 1 inline hook
```

---

## Matching strategy

Duplicate detection uses two sequential passes per entity. Passes are merged (union) before a winner is selected.

### Events

| Pass | Key | Guard | Confidence |
|---|---|---|---|
| 1 | `normalize_url(event.url)` | `starts_at` dates must be ≤ 7 days apart | High — same ticket URL + same date means same event |
| 2 | `(normalize_name(name), normalize_date(starts_at), normalize_city(venue.city))` | none | Medium — exact name + date + city |

> **Layer 1 (inline) uses Pass 1 only.** Name+date matching is expensive across large tables and runs in the full script only.

**Why the 7-day date guard on Pass 1:** Some scrapers use a generic registration page URL (e.g. `https://organizer.myruntime.com/register`) shared across every event they host. Without the date guard, all events from that organizer would be incorrectly grouped. True cross-source duplicates (same event scraped from two platforms) always share the same `starts_at` date — scrapers read the same value from the source.

> Note: `normalize_url` preserves the URL fragment (`#slug`). Scrapers like myruntime use `https://base-url/register#/event-slug` to differentiate events; stripping the fragment would collapse all their events into one group.

### Venues

| Pass | Key | Guard | Confidence |
|---|---|---|---|
| 1 | `(normalize_url(website), normalize_city(city))` | Distinct non-empty `place_id` → skip | High |
| 2 | `(normalize_name(name), normalize_city(city))` | Distinct non-empty `place_id` → skip | Medium |

**`place_id` guard (both passes):** Two venues with distinct, non-empty `place_id` values are confirmed to be different Google Places entries and are never merged regardless of name or website match.

**Why city is part of the website key:** A single institution (university, arts complex, shopping mall) may have multiple physically distinct venues under the same domain. Requiring the city alone is not sufficient, but pairing city with the website URL raises the bar: two venues must share website AND be in the same city before being considered duplicates.

### Organizers

| Pass | Key | Guard | Confidence |
|---|---|---|---|
| 1 | `normalize_url(organizer.website)` | Organizer names must share ≥ 1 word | High |
| 2 | `normalize_name(organizer.name)` | none | Medium |

**Why the name-word guard on Pass 1:** Multiple unrelated organizers can legitimately share a venue or mall's website (e.g. a sports organizer listing `gaisanograndmalls.com` as their event location). A shared word in their normalized names is required before a website-URL match triggers a group.

---

## Normalization rules

All string comparison keys are computed through normalization before grouping. This ensures `"Eventbrite.com/"` and `"https://eventbrite.com"` resolve to the same key.

| Function | What it does |
|---|---|
| `normalize_name(s)` | Lowercase → strip accents (NFKD) → strip punctuation → collapse whitespace |
| `normalize_url(url)` | Drop scheme → strip UTM params → sort query params → strip trailing slash → **preserve fragment** |
| `normalize_date(dt)` | Convert datetime to UTC → return `.date()` only |
| `normalize_city(city)` | Lowercase + strip whitespace |

**Example — URL normalization:**
```
"https://Eventbrite.com/e/123?utm_source=fb&ref=home"
→ "//eventbrite.com/e/123?ref=home"

"http://eventbrite.com/e/123?ref=home/"
→ "eventbrite.com/e/123?ref=home"
```

---

## Winner selection

When a group of duplicate rows is found, one row is kept (the winner) and the rest are deleted (the losers).

**Winner = row with the highest richness score.**

Richness score = count of fields that are not `NULL`, not empty string, and not an empty list/dict. Tiebreak: oldest `created_at` (the earliest-scraped row wins).

---

## Merge rules

Before a loser is deleted, its data enriches the winner:

- For each non-protected field on the winner that is `NULL` or empty, the **first non-empty value from any loser** is copied onto the winner.
- **FK remapping** is performed before deletion so no orphaned references remain.

### Protected fields — never overwritten

| Entity | Protected fields |
|---|---|
| `Event` | `agent_categories`, `slug`, `source`, `external_id` |
| `Venue` | `agents_primary_types`, `verification_status`, `slug`, `place_id`, `source` |
| `Organizer` | `agents_primary_types`, `status`, `slug`, `source`, `external_id` |

`agent_categories`, `agents_primary_types`, and `verification_status`/`status` are written by AI/admin processes — scraper merges must never overwrite them.

### FK remapping before deletion

| Loser entity | FK column remapped |
|---|---|
| `Venue` (loser) | `events_event.venue_id` → winner venue id |
| `Organizer` (loser) | `events_event.organizer_ref_id` → winner organizer id |
| `Event` (loser) | No FK remapping needed — nothing foreign-keys into `Event` |

---

## Layer 1 — `_dedup_after_save` (real-time)

Called automatically at the end of `save_events`, `save_venues`, and `save_organizers` in `base.py`. Operates only on the IDs that were just saved by the current scrape run.

```
save_events(scraped_events)
    └── per-event upsert loop
    └── _categorize_after_save(event_ids)   ← AI categorisation
    └── _dedup_after_save("events", event_ids)  ← URL-only dedup
```

**Failure isolation:** `_dedup_after_save` is wrapped in `try/except Exception`. A bug in dedup code emits a warning log but never raises to the caller — scrapes always complete regardless.

**Scope per entity in Layer 1:**

| Entity | What runs inline |
|---|---|
| Events | URL-normalized exact match only |
| Venues | Website URL match + name+city match (with `place_id` guard) |
| Organizers | Website URL match + name match |

---

## Transaction safety

**In the standalone script:** Each duplicate group is merged inside its own transaction. A failure in one group rolls back only that group — the script logs the error and continues to the next group.

**In `_dedup_after_save`:** The function is wrapped in a single try/except. If it fails partway through, any partial Django ORM changes within the function are not explicitly rolled back (they use Django's default autocommit). This is acceptable because the function operates on newly-saved IDs and failure is rare.

---

## What is NOT in scope

- **Fuzzy / Levenshtein matching** — not implemented; too many false positives at scale
- **Admin review queue** — low-confidence matches are not flagged for manual approval (roadmap item)
- **`EventGroup` canonical model** — no multi-source canonical record; one row survives per duplicate group
- **Celery / async dedup scheduling** — dedup runs synchronously inline or via manual script

---

## Rollback

Hard deletes are irreversible. The only rollback path is a database backup.

```bash
# Before any real (non --dry-run) execution:
pg_dump $DATABASE_URL > backup_before_dedup_$(date +%Y%m%d).sql

# To restore:
psql $DATABASE_URL < backup_before_dedup_YYYYMMDD.sql
```
