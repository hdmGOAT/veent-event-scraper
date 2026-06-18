# Scraping Protocols — Deduplication

Rules and conventions for scraper authors to minimise the creation of cross-source duplicates. Following these protocols reduces the number of groups the dedup script needs to merge on each run.

---

## Core rule: always populate identity fields

The within-source dedup constraints (`unique_source_external_id`, `unique_venue_source_place_id`) only fire when identity fields are non-empty. An empty `external_id` or `place_id` bypasses the constraint entirely — every scrape creates a new row.

| Entity | Identity field | Must be populated |
|---|---|---|
| `Event` | `external_id` | Yes — always, when the source provides a stable ID |
| `Venue` | `place_id` | Yes — always, when sourced from Google Places |
| `Organizer` | `external_id` | Yes — always, when the source provides a stable ID |

### What counts as a stable identity

- A numeric or UUID primary key from the source platform API (`event_id`, `eid`, `id`)
- A stable URL path segment that won't change (`/e/my-event-123` → use `my-event-123`)
- A subdomain + path combination for multi-tenant platforms (TicketSpice: `/subdomain/event-slug`)

### What does NOT count

- A generated slug based on the event title — titles change on re-scrape
- The full source URL — too fragile; query params and redirects change
- A row count or offset — meaningless across scrape runs

---

## Event scraper requirements

### 1. Populate `external_id`

Every event scraper must set `ScrapedEvent.external_id` to a non-empty string when the source platform exposes one. If the platform has no stable ID:

- Use the URL path segment (the last non-numeric path part, or the slug)
- Document in the scraper why `external_id` is derived rather than native

```python
# Good — native platform ID
scraped_event = ScrapedEvent(
    external_id=str(event_data["id"]),   # "8842193"
    ...
)

# Acceptable — stable URL path when no native ID
scraped_event = ScrapedEvent(
    external_id=urlparse(event_url).path.strip("/"),  # "events/charity-gala-2025"
    ...
)

# Bad — do not leave empty
scraped_event = ScrapedEvent(
    external_id="",   # bypasses dedup; creates duplicates on every scrape
    ...
)
```

### 2. Populate `url` with the canonical ticket/event page

The dedup script's **Pass 1** groups events by normalized URL. A consistent `url` field dramatically reduces cross-source duplicates — two scrapers that both set `url` to the same Eventbrite or Luma page will produce one row, not two.

- Always set `url` to the deepest stable event URL (e.g. `https://www.eventbrite.com/e/event-name-123456`)
- Do not set `url` to a listing page or search result page
- Do not include session tokens, tracking params, or redirect wrappers in `url`

### 3. Populate `organizer` and `organizer_url`

Even when a scraper cannot resolve to an `Organizer` FK, populate the denormalized `organizer` (name) and `organizer_url` (website) fields. These are used by `_resolve_organizer` to link events to existing `Organizer` rows across sources.

---

## Venue scraper requirements

### 1. Use Google Places `place_id` where available

The `Venue.place_id` field is the strongest cross-source venue identity. Any scraper that fetches venue data via the Google Places API **must** set `ScrapedVenue.place_id`.

The `google_places` scraper is authoritative for venue identity. Other scrapers that look up a venue by name/address on Places should carry the `place_id` through to the `ScrapedVenue`.

### 2. Normalize venue names consistently

Venue name variations are the primary cause of duplicate venue rows. Before setting `ScrapedVenue.name`, strip any suffix that is not part of the official venue name:

```python
# Bad — venue name with event-specific suffix
name = "SM Mall of Asia Arena – VIP Section"

# Good — canonical venue name only
name = "SM Mall of Asia Arena"
```

### 3. Always set `city` and `country`

Both the `_upsert_venue` fallback path and the dedup Pass 2 (`name + city`) require a non-empty `city` to group correctly. A venue without a city can only be matched by exact name.

### 4. Set `source_url` to the venue's own page

Not the event page. This is used as a fallback identity signal.

---

## Organizer scraper requirements

### 1. Populate `external_id` when available

Same rule as events. Platform-issued organizer IDs (e.g. `/org/my-org/12345`) must be used.

### 2. Populate `website` with the canonical domain

The dedup Pass 1 for organizers groups by normalized website URL. A consistent `website` across scrapers (e.g. always `https://myorg.com`, not `https://myorg.com/about`) maximises the chance of cross-source matching.

- Strip paths, query params, and trailing slashes from `website` before storing: only the root domain matters for identity
- If the organizer's website is the same as their Facebook or Instagram page, prefer the standalone domain if available

```python
# Good — root domain only
organizer_website = "https://myorganization.com"

# Acceptable — if only social media exists
organizer_website = "https://www.facebook.com/myorganization"

# Bad — event-specific path
organizer_website = "https://myorganization.com/events/2025/charity-gala"
```

### 3. Do not overwrite confirmed organizer status

The `Organizer.status` field (`pending` / `confirmed` / `rejected`) is set by admin. The `save_organizers` function already protects this field — do not bypass it with direct ORM writes in scraper code.

---

## Cross-source duplicate prevention checklist

Use this checklist when writing or reviewing a new scraper:

- [ ] `ScrapedEvent.external_id` is set to a non-empty stable ID for every event
- [ ] `ScrapedEvent.url` is set to the deepest canonical event URL
- [ ] `ScrapedEvent.organizer` and `organizer_url` are populated where available
- [ ] `ScrapedVenue.place_id` is populated when the venue was resolved via Google Places
- [ ] `ScrapedVenue.name` does not include event-specific suffixes
- [ ] `ScrapedVenue.city` is always set
- [ ] `ScrapedOrganizer.external_id` is set when the platform provides one
- [ ] `ScrapedOrganizer.website` is the canonical root domain (not an event-specific path)

---

## Source key uniqueness

Each scraper has a `source` string (e.g. `"eventbrite"`, `"luma"`). This key is the namespace for all `(source, external_id)` dedup constraints.

**Rule:** No two active scrapers may share the same `source` key.

The `AllEventsPHScraper` and `AllEventsAPIScraper` both declare `source = "allevents_in"`. `AllEventsAPIScraper` is imported in `__init__.py` but intentionally **not registered** in `SCRAPERS` to avoid this collision. Do not re-register it without first assigning a distinct `source` key.

---

## When cross-source dedup runs

Understanding the two layers helps scrapers be written correctly:

```
Scraper runs
    │
    ▼
save_events / save_venues / save_organizers
    │   Within-source dedup (unique constraint: source + external_id)
    │
    ▼
_dedup_after_save (Layer 1 — inline)
    │   Fast URL-only cross-source pass on newly saved IDs
    │   Merges obvious duplicates immediately
    │
    ▼
deduplicate.py script (Layer 2 — on demand)
    │   Full two-pass cross-source pass across entire table
    │   Catches anything Layer 1 missed (name+date+city grouping)
    ▼
Clean DB
```

If a scraper consistently produces `external_id = ""` for certain event types, those events will never benefit from Layer 1 dedup and will accumulate duplicates until the Layer 2 script is run.
