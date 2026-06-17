#!/usr/bin/env python3
"""Standalone script: classify venue primary types directly on Neon.

Connects to Neon via DATABASE_URL, fetches only venues with empty
agents_primary_types, calls the local Claude CLI (Haiku) in batches of 20,
and writes results back. No Django startup required.

Usage:
    ./venv/bin/python scripts/classify-neon-venues.py
    ./venv/bin/python scripts/classify-neon-venues.py --limit 50
    ./venv/bin/python scripts/classify-neon-venues.py --dry-run
    ./venv/bin/python scripts/classify-neon-venues.py --all       # re-classify everything

Environment (read from .env automatically):
    DATABASE_URL       Neon postgres connection string
    CLAUDE_CLI_CMD     Claude binary name (default: claude)
    CLAUDE_CONFIG_DIR  Config dir for non-default accounts (e.g. ~/.claude-account-ojt)

NOTE: requires the agents_primary_types JSONField to exist on events_venue.
      Run `manage.py makemigrations && manage.py migrate` first.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

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
CLAUDE_CLI_CMD = os.environ.get("CLAUDE_CLI_CMD", "claude")
CLAUDE_CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR", "")
BATCH_SIZE = 20
MODEL = "claude-haiku-4-5-20251001"

CANONICAL_VENUE_TYPES = [
    "Sports & Recreation",
    "Hotel / Accommodation",
    "Restaurant / Food & Beverage",
    "Conference / Meeting Space",
    "Park / Outdoor Space",
    "Arts & Culture",
    "Theater & Performing Arts",
    "Religious Venue",
    "Educational Institution",
    "Community / Government",
    "Commercial / Retail",
    "Other",
]

_CANONICAL_SET = set(CANONICAL_VENUE_TYPES)

_SYSTEM_PROMPT = (
    "You are a strict venue classifier. Return ONLY valid JSON, no markdown, no "
    "explanation. Each venue must map to 1-2 labels chosen exclusively from this "
    "list: " + json.dumps(CANONICAL_VENUE_TYPES)
)

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_connection():
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL is not set. Add it to apps/backend/.env", file=sys.stderr)
        sys.exit(1)
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def fetch_unclassified(conn, limit=None, reclassify_all=False):
    """Return list of {id, name, primary_type, primary_type_display, types, about} dicts."""
    with conn.cursor() as cur:
        if reclassify_all:
            sql = (
                "SELECT id, name, primary_type, primary_type_display, types, about "
                "FROM events_venue ORDER BY id"
            )
        else:
            sql = (
                "SELECT id, name, primary_type, primary_type_display, types, about "
                "FROM events_venue "
                "WHERE agents_primary_types = '[]'::jsonb ORDER BY id"
            )
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        cur.execute(sql)
        return cur.fetchall()


def write_types(conn, updates: dict[int, list[str]]):
    """Bulk-update agents_primary_types for the given {id: labels} mapping."""
    if not updates:
        return
    with conn.cursor() as cur:
        args = [(json.dumps(labels), venue_id) for venue_id, labels in updates.items()]
        psycopg2.extras.execute_batch(
            cur,
            "UPDATE events_venue SET agents_primary_types = %s::jsonb WHERE id = %s",
            args,
        )
    conn.commit()

# ---------------------------------------------------------------------------
# Claude CLI helpers
# ---------------------------------------------------------------------------

def _build_prompt(batch: list[dict]) -> str:
    lines = [
        _SYSTEM_PROMPT,
        "",
        "Classify each of the following venues. Use the venue name, raw primary type, "
        "Places type list, and about text to decide. If most fields are empty, classify "
        "from the name alone.",
        "",
        "Return ONLY a JSON object mapping each venue id (as a string key) to an "
        'array of 1-2 canonical labels. Example: '
        '{"1": ["Sports & Recreation"], "2": ["Conference / Meeting Space", "Hotel / Accommodation"]}',
        "",
        "Venues:",
    ]
    for row in batch:
        # types is already a list from psycopg2 JSON parsing; guard against None
        raw_types = row["types"] or []
        if isinstance(raw_types, str):
            try:
                raw_types = json.loads(raw_types)
            except json.JSONDecodeError:
                raw_types = []
        lines.append(json.dumps({
            "id": row["id"],
            "name": row["name"] or "",
            "primary_type": row["primary_type"] or "",
            "primary_type_display": row["primary_type_display"] or "",
            "types": raw_types[:10],  # cap list length to keep prompt tight
            "about": (row["about"] or "")[:200],
        }))
    return "\n".join(lines)


def _validate_labels(raw) -> list[str]:
    if not isinstance(raw, list):
        return ["Other"]
    valid = [l for l in raw if l in _CANONICAL_SET]
    return valid or ["Other"]


def call_claude(batch: list[dict]) -> dict[int, list[str]] | None:
    """Call Claude CLI for a batch, return {venue_id: [labels]}."""
    prompt = _build_prompt(batch)
    venue_ids = [row["id"] for row in batch]

    sub_env = os.environ.copy()
    if CLAUDE_CONFIG_DIR:
        sub_env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(CLAUDE_CONFIG_DIR)

    try:
        result = subprocess.run(
            [CLAUDE_CLI_CMD, "--model", MODEL, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=60,
            env=sub_env,
        )
    except FileNotFoundError:
        print(
            f"ERROR: Claude CLI '{CLAUDE_CLI_CMD}' not found. "
            f"Set CLAUDE_CLI_CMD in .env (e.g. CLAUDE_CLI_CMD=claude).",
            file=sys.stderr,
        )
        sys.exit(1)

    text = result.stdout.strip()
    # Strip markdown code fences that Claude occasionally wraps around JSON.
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    text = text.rstrip("`").strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        print(f"WARNING: Claude returned non-JSON for batch; venues will be retried next run.", file=sys.stderr)
        return None

    mapping = parsed if isinstance(parsed, dict) else {}
    return {vid: _validate_labels(mapping.get(str(vid))) for vid in venue_ids}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", dest="reclassify_all", help="Re-classify already-classified venues too.")
    parser.add_argument("--limit", type=int, help="Max number of venues to process.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run without writing to DB.")
    args = parser.parse_args()

    conn = get_connection()
    try:
        rows = fetch_unclassified(conn, limit=args.limit, reclassify_all=args.reclassify_all)
    except Exception as e:
        print(f"ERROR fetching from Neon: {e}", file=sys.stderr)
        conn.close()
        sys.exit(1)

    total = len(rows)
    if total == 0:
        print("All venues are already classified. Nothing to do.")
        conn.close()
        return

    num_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"Found {total} unclassified venue(s) -> {num_batches} batch(es) of {BATCH_SIZE}")

    if args.dry_run:
        print("[dry-run] No writes. Remove --dry-run to apply.")
        conn.close()
        return

    classified = 0
    for i, start in enumerate(range(0, total, BATCH_SIZE), 1):
        batch = rows[start : start + BATCH_SIZE]
        print(f"  batch {i}/{num_batches} ({len(batch)} venues) …", end=" ", flush=True)
        try:
            updates = call_claude(batch)
            if updates is None:
                print("skipped (bad JSON from Claude)")
                continue
            write_types(conn, updates)
            classified += len(updates)
            print("done")
        except Exception as e:
            print(f"FAILED: {e}")
            conn.rollback()

    conn.close()
    print(f"\nDone. Classified {classified}/{total} venue(s).")


if __name__ == "__main__":
    main()
