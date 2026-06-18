# Running the Deduplication Script

## Prerequisites

- Python virtualenv activated (`source venv/bin/activate` or `./venv/bin/python`)
- `DATABASE_URL` set in `apps/backend/.env`
- `psycopg2` installed (already in project requirements)

---

## Commands

All commands are run from `apps/backend/`.

### Dry-run (safe — zero DB writes)

Always run this first and review the output before executing a real merge.

```bash
./venv/bin/python scripts/deduplicate.py --dry-run
```

With verbose group output:

```bash
./venv/bin/python scripts/deduplicate.py --dry-run --verbose
```

**Sample output:**

```
  [Venues] winner 42 <- losers [87]
  [Venues] winner 15 <- losers [201, 340]
  [Events] winner 1003 <- losers [1204]

Entity       Groups  Merged  Deleted
Events           11       0        0
Venues           21       0        0
Organizers        5       0        0

[dry-run] No writes. Remove --dry-run to apply.
```

---

### Run for a single entity

```bash
./venv/bin/python scripts/deduplicate.py --entity venues
./venv/bin/python scripts/deduplicate.py --entity events
./venv/bin/python scripts/deduplicate.py --entity organizers
```

Recommended order: **venues → organizers → events**. Venue and organizer FK references are remapped before event dedup runs, so event winner rows will already have the correct `venue_id` and `organizer_ref_id`.

### Run all entities

```bash
./venv/bin/python scripts/deduplicate.py --entity all
# or simply (default):
./venv/bin/python scripts/deduplicate.py
```

---

## Safe production workflow

```bash
# Step 1 — dry-run on production to see what would be merged
./venv/bin/python scripts/deduplicate.py --dry-run --verbose 2>&1 | tee dedup_dry_run.txt

# Step 2 — review dedup_dry_run.txt; spot-check a few winner/loser pairs in Django admin

# Step 3 — take a full backup
pg_dump $DATABASE_URL > backup_before_dedup_$(date +%Y%m%d_%H%M).sql

# Step 4 — run per entity (recommended for first time)
./venv/bin/python scripts/deduplicate.py --entity venues --verbose
./venv/bin/python scripts/deduplicate.py --entity organizers --verbose
./venv/bin/python scripts/deduplicate.py --entity events --verbose

# Step 5 — verify row counts dropped as expected
./venv/bin/python manage.py shell -c "
from events.models import Event, Venue, Organizer
print('Events:', Event.objects.count())
print('Venues:', Venue.objects.count())
print('Organizers:', Organizer.objects.count())
"
```

---

## Summary table

At the end of every run (dry or live), the script prints:

```
Entity       Groups  Merged  Deleted
Events            N       N        N
Venues            N       N        N
Organizers        N       N        N
```

| Column | Meaning |
|---|---|
| `Groups` | Number of duplicate groups found |
| `Merged` | Groups where the winner was enriched and losers deleted |
| `Deleted` | Total loser rows hard-deleted |

If any groups fail (DB error, constraint violation), a line like `2 group(s) failed and were rolled back.` is appended. Failed groups leave the DB unchanged for that group — other groups are unaffected.

---

## Scheduling (optional)

To run dedup automatically after every full scrape cycle, add it as an n8n HTTP Request node that hits a Django management command endpoint, or wire it into the existing scraper automation workflow as a final step.

Alternatively, run it as a cron job on the server:

```bash
# Daily at 3 AM UTC — after scraper runs complete
0 3 * * * cd /app && ./venv/bin/python scripts/deduplicate.py >> /var/log/dedup.log 2>&1
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ERROR: DATABASE_URL is not set` | Missing env var | Add `DATABASE_URL=...` to `apps/backend/.env` |
| `ModuleNotFoundError: No module named 'psycopg2'` | venv not active or deps not installed | `pip install -r requirements.txt` |
| `IntegrityError: duplicate key value violates unique constraint` | Two rows in the same group have conflicting identity fields (`slug`, `source`+`external_id`) — should be rare | Check the group IDs in the error; manually inspect these rows in Django admin before retrying |
| Groups found in dry-run but `Merged: 0` after real run | All groups hit errors and were rolled back | Check stderr output for per-group error details |
| Re-running finds 0 groups | Dedup already applied — working as expected | Nothing to do |
