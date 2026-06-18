#!/usr/bin/env python3
"""Standalone script: find and merge duplicate Event/Venue/Organizer rows on Neon.

Connects to Neon via DATABASE_URL, detects duplicate records using URL
normalization and exact field-match grouping, merges the best non-null fields
from the losers into a chosen winner, remaps foreign keys, and hard-deletes the
losing rows. No Django startup required.

Usage:
    ./venv/bin/python scripts/deduplicate.py
    ./venv/bin/python scripts/deduplicate.py --entity events
    ./venv/bin/python scripts/deduplicate.py --entity venues
    ./venv/bin/python scripts/deduplicate.py --entity organizers
    ./venv/bin/python scripts/deduplicate.py --entity all
    ./venv/bin/python scripts/deduplicate.py --dry-run
    ./venv/bin/python scripts/deduplicate.py --verbose

Environment (read from .env automatically):
    DATABASE_URL       Neon postgres connection string

Hard deletes are irreversible. Take a `pg_dump` backup and review `--dry-run`
output before running without --dry-run.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# Import the local dedup utilities (same scripts/ directory)
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import dedup  # noqa: E402

# ---------------------------------------------------------------------------
# Load .env from the backend directory (one level up from scripts/)
# ---------------------------------------------------------------------------


def _load_dotenv():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# (label, finder_fn, merge_fn)
_ENTITY_HANDLERS = {
    "events": ("Events", dedup.find_event_duplicates, dedup.merge_events),
    "venues": ("Venues", dedup.find_venue_duplicates, dedup.merge_venues),
    "organizers": (
        "Organizers", dedup.find_organizer_duplicates, dedup.merge_organizers
    ),
}

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def get_connection():
    if not DATABASE_URL:
        print(
            "ERROR: DATABASE_URL is not set. Add it to apps/backend/.env",
            file=sys.stderr,
        )
        sys.exit(1)
    return psycopg2.connect(
        DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor
    )


# ---------------------------------------------------------------------------
# Per-entity dedup run
# ---------------------------------------------------------------------------


def run_entity(conn, entity: str, dry_run: bool, verbose: bool) -> dict:
    """Find + merge duplicates for one entity. Returns count summary dict."""
    label, finder_fn, merge_fn = _ENTITY_HANDLERS[entity]

    with conn.cursor() as cur:
        groups = finder_fn(cur)

    summary = {
        "label": label, "groups": len(groups), "merged": 0, "deleted": 0,
        "errors": 0,
    }

    if dry_run:
        for group in groups:
            winner, losers = group[0], group[1:]
            print(
                f"  [{label}] winner {winner} <- losers {losers}"
            )
        return summary

    # Each group is committed independently so one failure cannot corrupt or
    # roll back the others.
    conn.autocommit = False
    for group in groups:
        winner, losers = group[0], group[1:]
        if not losers:
            continue
        try:
            with conn.cursor() as cur:
                merge_fn(cur, winner, losers)
            conn.commit()
            summary["merged"] += 1
            summary["deleted"] += len(losers)
            if verbose:
                print(f"  [{label}] merged losers {losers} -> winner {winner}")
        except Exception as exc:  # noqa: BLE001 — isolate per-group failures
            conn.rollback()
            summary["errors"] += 1
            print(
                f"  [{label}] ERROR merging {group}: {exc}", file=sys.stderr
            )

    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _print_summary(summaries: list[dict]) -> None:
    print()
    print(f"{'Entity':<12}{'Groups':>8}{'Merged':>8}{'Deleted':>9}")
    for s in summaries:
        print(
            f"{s['label']:<12}{s['groups']:>8}{s['merged']:>8}{s['deleted']:>9}"
        )
    total_errors = sum(s["errors"] for s in summaries)
    if total_errors:
        print(f"\n{total_errors} group(s) failed and were rolled back.")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--entity",
        choices=["events", "venues", "organizers", "all"],
        default="all",
        help="Which entity to deduplicate (default: all).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Find and report duplicate groups without writing to the DB.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each merged group.",
    )
    args = parser.parse_args()

    if args.entity == "all":
        entities = ["events", "venues", "organizers"]
    else:
        entities = [args.entity]

    conn = get_connection()
    try:
        summaries = []
        for entity in entities:
            summaries.append(
                run_entity(conn, entity, args.dry_run, args.verbose)
            )
        _print_summary(summaries)
        if args.dry_run:
            print("\n[dry-run] No writes. Remove --dry-run to apply.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
