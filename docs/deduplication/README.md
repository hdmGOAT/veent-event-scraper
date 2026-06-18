# Deduplication System

Cross-source deduplication for `Event`, `Venue`, and `Organizer` records.

| Doc | What it covers |
|---|---|
| [overview.md](overview.md) | Architecture, matching strategy, merge rules, and automatic protocol |
| [running-the-script.md](running-the-script.md) | How to run the standalone script — dry-run, live merge, per-entity usage |
| [protocols.md](protocols.md) | Conventions scrapers must follow to minimize new duplicates |
| [api-reference.md](api-reference.md) | Full function reference for `scripts/dedup.py` |

---

## Quick start

```bash
# Always dry-run first
./venv/bin/python scripts/deduplicate.py --dry-run --verbose

# Review output, then take a backup and run for real
pg_dump $DATABASE_URL > backup_$(date +%Y%m%d).sql
./venv/bin/python scripts/deduplicate.py --entity venues
./venv/bin/python scripts/deduplicate.py --entity organizers
./venv/bin/python scripts/deduplicate.py --entity events
```

## Files

| File | Role |
|---|---|
| `apps/backend/scripts/dedup.py` | Normalization helpers, duplicate finders, merge functions (psycopg2, no Django) |
| `apps/backend/scripts/deduplicate.py` | Standalone CLI — runs against `DATABASE_URL` |
| `apps/backend/events/scrapers/base.py` | `_dedup_after_save` — lightweight inline dedup called automatically after each scrape |

## Live dry-run results (baseline — 2026-06-18)

| Entity | Duplicate groups found | Rows to delete |
|---|---|---|
| Events | 0 | 0 |
| Venues | 16 | 17 |
| Organizers | 2 | 2 |

> Initial run detected 11 event, 21 venue, and 5 organizer groups. After fixing 4 false-positive bugs in `dedup.py` (fragment stripping, date proximity window, venue city guard, organizer name-word guard), the clean count settled at 0 / 16 / 2. See [overview.md — matching strategy](overview.md#matching-strategy) for the guard details.
