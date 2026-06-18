# API Reference — `scripts/dedup.py`

All public functions in `apps/backend/scripts/dedup.py`. The module has no Django dependency — it can be imported in standalone scripts, tests, or any Python process that has `psycopg2` available.

---

## Normalization helpers

Pure Python functions. No DB connection required.

---

### `normalize_name(name)`

```python
def normalize_name(name: str | None) -> str
```

Lowercase, strip accents (NFKD), strip punctuation, collapse whitespace.

| Input | Output |
|---|---|
| `"Café Évènement!"` | `"cafe evenement"` |
| `"Hello,  World!"` | `"hello  world"` → `"hello world"` |
| `None` | `""` |
| `""` | `""` |

Used as the name comparison key in all three entity duplicate finders.

---

### `normalize_url(url)`

```python
def normalize_url(url: str | None) -> str
```

Scheme-less, UTM-stripped, query-sorted, trailing-slash-stripped URL key.

Steps applied in order:
1. Lowercase and strip surrounding whitespace
2. Parse with `urllib.parse.urlparse`
3. Drop the scheme entirely (`http://` and `https://` both produce the same key)
4. Strip any query key whose name starts with `utm_`
5. Sort remaining query params alphabetically
6. Strip trailing slash from the path

| Input | Output |
|---|---|
| `"https://example.com/page/"` | `"//example.com/page"` |
| `"http://example.com/page"` | `"//example.com/page"` |
| `"https://x.com?b=2&a=1"` | `"//x.com?a=1&b=2"` |
| `"https://x.com?utm_source=fb&id=1"` | `"//x.com?id=1"` |
| `None` | `""` |
| `""` | `""` |

> Note: the output starts with `//` (scheme-relative) because the scheme is dropped but the delimiter is kept by `urlunparse`. This is intentional — the value is a comparison key, not a valid URL.

---

### `normalize_date(dt)`

```python
def normalize_date(dt) -> date | None
```

Converts a timezone-aware or naive `datetime` to a UTC `date`. Passes through an existing `date` unchanged. Returns `None` for `None` input.

| Input | Output |
|---|---|
| `datetime(2025, 6, 18, 23, 0, tzinfo=timezone.utc)` | `date(2025, 6, 18)` |
| `datetime(2025, 6, 18, 1, 0, tzinfo=timezone(timedelta(hours=8)))` | `date(2025, 6, 17)` (UTC) |
| `date(2025, 6, 18)` | `date(2025, 6, 18)` |
| `None` | `None` |

Used in the event name+date+city grouping pass.

---

### `normalize_city(city)`

```python
def normalize_city(city: str | None) -> str
```

Lowercase and strip whitespace. Returns `""` for `None` or blank input.

| Input | Output |
|---|---|
| `"  Cagayan de Oro  "` | `"cagayan de oro"` |
| `"MANILA"` | `"manila"` |
| `None` | `""` |

---

## Duplicate finders

Each finder takes a `psycopg2` cursor (with `RealDictCursor` factory) and returns a list of ordered groups. Each group is a list of integer PKs where **the first element is the winner** and remaining elements are losers.

Groups with only one member are never returned.

---

### `find_event_duplicates(cursor)`

```python
def find_event_duplicates(cursor) -> list[list[int]]
```

Two-pass detection:

1. **URL pass** — groups events by `normalize_url(url)` where `url != ''`
2. **Name+date+city pass** — groups by `(normalize_name(name), normalize_date(starts_at), normalize_city(venue.city))`

Results from both passes are union-merged (overlapping groups are combined). Winner selection applied to each final group.

**Returns:** e.g. `[[42, 87], [15, 201, 340]]` — group 1: winner 42, loser 87; group 2: winner 15, losers 201 and 340.

---

### `find_venue_duplicates(cursor)`

```python
def find_venue_duplicates(cursor) -> list[list[int]]
```

Two-pass detection:

1. **Website pass** — groups by `normalize_url(website)` where `website != ''`
2. **Name+city pass** — groups by `(normalize_name(name), normalize_city(city))`

> Note: the standalone script applies an additional guard — venues with distinct non-empty `place_id` values are not merged by name+city alone. This guard is also present in the Django inline hook (`_dedup_after_save`).

---

### `find_organizer_duplicates(cursor)`

```python
def find_organizer_duplicates(cursor) -> list[list[int]]
```

Two-pass detection:

1. **Website pass** — groups by `normalize_url(website)` where `website != ''`
2. **Name pass** — groups by `normalize_name(name)`

---

## Merge functions

Each merge function:
1. Enriches the winner row by copying non-empty loser field values into empty winner fields
2. Remaps FK references from loser IDs to the winner ID (where applicable)
3. Hard-deletes the loser rows

All three functions are **no-ops if `loser_ids` is empty**.

---

### `merge_events(cursor, winner_id, loser_ids)`

```python
def merge_events(cursor, winner_id: int, loser_ids: list[int]) -> None
```

**Skip fields** (never copied from losers):

```
id, slug, created_at, updated_at, agent_categories, source, external_id
```

**FK remapping:** none — nothing in the current schema foreign-keys into `events_event`.

**Deletion:** `DELETE FROM events_event WHERE id = ANY(loser_ids)`

---

### `merge_venues(cursor, winner_id, loser_ids)`

```python
def merge_venues(cursor, winner_id: int, loser_ids: list[int]) -> None
```

**Skip fields:**

```
id, slug, created_at, updated_at, agents_primary_types, verification_status, place_id, source
```

**FK remapping:**

```sql
UPDATE events_event SET venue_id = winner_id WHERE venue_id = ANY(loser_ids)
```

**Deletion:** `DELETE FROM events_venue WHERE id = ANY(loser_ids)`

---

### `merge_organizers(cursor, winner_id, loser_ids)`

```python
def merge_organizers(cursor, winner_id: int, loser_ids: list[int]) -> None
```

**Skip fields:**

```
id, slug, created_at, updated_at, agents_primary_types, status, source, external_id
```

**FK remapping:**

```sql
UPDATE events_event SET organizer_ref_id = winner_id WHERE organizer_ref_id = ANY(loser_ids)
```

**Deletion:** `DELETE FROM events_organizer WHERE id = ANY(loser_ids)`

---

## Internal helpers (not part of the public API)

| Function | Purpose |
|---|---|
| `_richness_score(row: dict) -> int` | Count non-null, non-empty fields in a row dict |
| `_merge_overlapping_groups(groups)` | Union-merge groups that share any PK |
| `_select_winner(cursor, table, pks)` | Return `[winner, *losers]` ordered by richness then oldest `created_at` |
| `_group_by_key(rows, key_fn)` | Bucket rows by a key function; return groups with 2+ members |
| `_fill_missing(cursor, table, winner_id, loser_ids, skip_fields)` | Copy empty winner fields from losers via `UPDATE` |
| `_is_empty(value) -> bool` | True for `None`, `""`, `[]`, `{}` |

---

## Usage example

```python
import sys
from pathlib import Path
import psycopg2, psycopg2.extras

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
import dedup

conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)

with conn.cursor() as cur:
    groups = dedup.find_venue_duplicates(cur)

print(f"Found {len(groups)} duplicate venue groups")

conn.autocommit = False
for group in groups:
    winner, *losers = group
    try:
        with conn.cursor() as cur:
            dedup.merge_venues(cur, winner, losers)
        conn.commit()
        print(f"Merged {losers} → {winner}")
    except Exception as e:
        conn.rollback()
        print(f"Failed: {e}")

conn.close()
```
