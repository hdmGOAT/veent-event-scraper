#!/usr/bin/env python3
"""Standalone script: categorize uncategorized events directly on Neon.

Connects to Neon via DATABASE_URL, fetches only events with empty
agent_categories, calls the local Claude CLI (Haiku) in batches of 20,
and writes results back. No Django startup required.

Usage:
    ./venv/bin/python scripts/categorize-neon-events.py
    ./venv/bin/python scripts/categorize-neon-events.py --limit 50
    ./venv/bin/python scripts/categorize-neon-events.py --dry-run
    ./venv/bin/python scripts/categorize-neon-events.py --all       # re-classify everything

Environment (read from .env automatically):
    DATABASE_URL       Neon postgres connection string
    CLAUDE_CLI_CMD     Claude binary name (default: claude)
    CLAUDE_CONFIG_DIR  Config dir for non-default accounts (e.g. ~/.claude-account-ojt)
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

CANONICAL_CATEGORIES = [
    "Church",
    "Sports",
    "Workshop",
    "Bar/DJ",
    "Concert",
    "Music Fest",
    "Expo",
    "Live Band",
    "Theater",
    "Modelling",
    "Film",
    "Screening",
    "Car Pool",
    "Camp",
    "Competition",
    "Fan Fair",
    "School",
    "Conference",
    "Convention",
    "Resort",
    "Art",
    "Health",
    "Pet",
    "Clinic",
    "Rentals",
    "Hotel/Inn/Airbnb",
    "Travel and Tours",
    "Community",
    "Webinar",
    "Fun Run",
    "Club",
    "Salon",
    "Adventure Parks",
    "Water Park",
    "Study Hub",
    "Cabin",
    "Farm",
    "Studio",
    "Restaurant",
    "Playground",
    "Other",
]

_CANONICAL_SET = set(CANONICAL_CATEGORIES)

_CATEGORY_HINTS = """
Category guidance (use these mappings to pick the best label):
- Concert: orchestras, symphonies, classical music, pop/rock/jazz concerts, comedy tours, live performances by artists
- Theater: musicals, plays, stage shows, theatrical productions
- Music Fest: music festivals spanning multiple acts or days
- Live Band: bar gigs, live band nights, small venue performances
- Bar/DJ: DJ sets, nightclub events, bar parties
- Art: art exhibitions, galleries, immersive art, light installations, digital art
- Sports: athletic competitions, team sports, martial arts, motorsports
- Fun Run: road races, fun runs, marathons, charity walks
- Conference: summits, symposiums, business conferences, tech expos
- Workshop: training sessions, skill workshops, seminars, masterclasses
- Expo: trade expos, consumer expos, conventions with exhibitors
- Church: religious services, masses, prayer events, spiritual retreats
- Health: medical camps, wellness events, yoga, mental health
- Community: neighborhood events, cultural fairs, charity fundraisers, social gatherings
- School: academic events, school programs, graduation ceremonies
- Webinar: online talks, virtual conferences, livestreams
- Travel and Tours: travel fairs, tour packages, travel expos
- Film: movie screenings, film festivals
- Screening: one-off screenings, preview screenings
- Playground: family-friendly events, kids activities, theme park events
- Adventure Parks: outdoor adventures, obstacle courses, zip lines
- Water Park: water-based recreational events
- Camp: overnight camps, summer camps, outdoor retreats
- Club: club nights, members events, social clubs
- Salon: beauty, hair, wellness salons
- Clinic: medical clinics, health screenings, dental events
- Pet: pet shows, animal adoption, pet-friendly events
- Modelling: fashion shows, modelling competitions
- Competition: contests, battles, game competitions (non-sports)
- Fan Fair: fan meets, fan conventions, idol events
- Convention: pop culture conventions, cosplay events, comic cons
- Resort: resort packages, staycation events
- Hotel/Inn/Airbnb: accommodation-related events
- Rentals: equipment or venue rentals
- Cabin: cabin retreats, mountain getaways
- Farm: farm visits, agritourism, harvest festivals
- Studio: recording studio events, art studio events
- Restaurant: food events, dining experiences, restaurant launches
- Study Hub: study groups, review centers, learning hubs
- Car Pool: ridesharing, carpooling events
- Other: only use if no other category fits at all
"""

_SYSTEM_PROMPT = (
    "You are a strict event classifier. Return ONLY valid JSON — no markdown fences, "
    "no explanation, no extra text. Each event must map to 1-2 labels chosen "
    "exclusively from this exact list: " + json.dumps(CANONICAL_CATEGORIES) + "\n" + _CATEGORY_HINTS
)

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_connection():
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL is not set. Add it to apps/backend/.env", file=sys.stderr)
        sys.exit(1)
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def fetch_uncategorized(conn, limit=None, reclassify_all=False):
    """Return list of {id, name, category, description} dicts."""
    with conn.cursor() as cur:
        if reclassify_all:
            sql = "SELECT id, name, category, description FROM events_event ORDER BY id"
        else:
            sql = (
                "SELECT id, name, category, description FROM events_event "
                "WHERE agent_categories = '[]'::jsonb ORDER BY id"
            )
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur.execute(sql)
        return cur.fetchall()


def write_categories(conn, updates: dict[int, list[str]]):
    """Bulk-update agent_categories for the given {id: labels} mapping."""
    if not updates:
        return
    with conn.cursor() as cur:
        args = [(json.dumps(labels), event_id) for event_id, labels in updates.items()]
        psycopg2.extras.execute_batch(
            cur,
            "UPDATE events_event SET agent_categories = %s::jsonb WHERE id = %s",
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
        "Classify each of the following events. Use the event name, raw category, "
        "and description to decide. If the raw category is empty, classify from the "
        "name and description alone.",
        "",
        "Return ONLY a JSON object mapping each event id (as a string key) to an "
        'array of 1-2 canonical labels. Example: '
        '{"1": ["Fun Run"], "2": ["Concert", "Music Fest"], "3": ["Theater"]}',
        "",
        "Events:",
    ]
    for row in batch:
        lines.append(json.dumps({
            "id": row["id"],
            "name": row["name"] or "",
            "category": row["category"] or "",
            "description": (row["description"] or "")[:200],
        }))
    return "\n".join(lines)


def _validate_labels(raw) -> list[str]:
    if not isinstance(raw, list):
        return ["Other"]
    valid = [l for l in raw if l in _CANONICAL_SET]
    return valid or ["Other"]


def _extract_json(text: str) -> str:
    """Strip markdown fences and extract the first JSON object from text."""
    import re
    # Remove ```json ... ``` or ``` ... ``` fences
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    # Grab from first { to last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text


def call_claude(batch: list[dict], debug: bool = False) -> dict[int, list[str]]:
    """Call Claude CLI for a batch, return {event_id: [labels]}."""
    prompt = _build_prompt(batch)
    event_ids = [row["id"] for row in batch]

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

    if debug:
        print(f"\n--- RAW CLAUDE OUTPUT ---\n{result.stdout}\n--- END ---\n")

    try:
        cleaned = _extract_json(result.stdout.strip())
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        if debug:
            print(f"[debug] JSON parse failed on: {result.stdout[:300]!r}", file=sys.stderr)
        parsed = {}

    mapping = parsed if isinstance(parsed, dict) else {}
    return {eid: _validate_labels(mapping.get(str(eid))) for eid in event_ids}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", dest="reclassify_all", help="Re-classify already-categorized events too.")
    parser.add_argument("--limit", type=int, help="Max number of events to process.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run without writing to DB.")
    parser.add_argument("--debug", action="store_true", help="Print raw Claude output for each batch.")
    args = parser.parse_args()

    conn = get_connection()
    try:
        rows = fetch_uncategorized(conn, limit=args.limit, reclassify_all=args.reclassify_all)
    except Exception as e:
        print(f"ERROR fetching from Neon: {e}", file=sys.stderr)
        conn.close()
        sys.exit(1)

    total = len(rows)
    if total == 0:
        print("All events are already categorized. Nothing to do.")
        conn.close()
        return

    num_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"Found {total} uncategorized event(s) → {num_batches} batch(es) of {BATCH_SIZE}")

    if args.dry_run:
        print("[dry-run] No writes. Remove --dry-run to apply.")
        conn.close()
        return

    classified = 0
    for i, start in enumerate(range(0, total, BATCH_SIZE), 1):
        batch = rows[start : start + BATCH_SIZE]
        print(f"  batch {i}/{num_batches} ({len(batch)} events) …", end=" ", flush=True)
        try:
            updates = call_claude(batch, debug=args.debug)
            write_categories(conn, updates)
            classified += len(updates)
            print("done")
            id_to_name = {row["id"]: row["name"] or "(no name)" for row in batch}
            for eid, labels in updates.items():
                print(f"    [{eid}] {id_to_name.get(eid, '?')}  →  {', '.join(labels)}")
        except Exception as e:
            print(f"FAILED: {e}")

    conn.close()
    print(f"\nDone. Classified {classified}/{total} event(s).")


if __name__ == "__main__":
    main()
