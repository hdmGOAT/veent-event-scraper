"""Backfill MyRuntime "direct" organizer attribution.

The MyRuntime scraper previously collapsed all events hosted directly on
myruntime.com (no custom subdomain) into a single synthetic organizer named
"direct". This script fixes that by:

  1. Re-fetching the MyRuntime API.
  2. For each direct-hosted event, deriving the real organizer key from
     externalLinks (Facebook handle → website domain → IG handle).
  3. Creating missing Organizer rows for those keys.
  4. Updating each Event row's organizer name and organizer_ref FK.
  5. Deleting the old "direct" Organizer row (after detaching any remaining
     events that had no usable link).

Usage:
    python scripts/backfill-myruntime-direct-organizers.py
    python scripts/backfill-myruntime-direct-organizers.py --dry-run

Environment:
    DATABASE_URL   Neon / Postgres connection string (read from .env)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras
import requests

# ---------------------------------------------------------------------------
# Load .env
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
            os.environ.setdefault(key.strip(), value.strip())

_load_dotenv()

# ---------------------------------------------------------------------------
# MyRuntime API helpers (duplicated from the scraper so this script is
# self-contained and doesn't need Django to be set up)
# ---------------------------------------------------------------------------

_API_URL = "https://myruntime.com/appEventsService/api/v1/getAppEvents"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EventScraper/1.0)"}
_TIMEOUT = 20
_EVENTS_PAGE = "https://myruntime.com/events"


def _fetch_api() -> list[dict]:
    resp = requests.get(_API_URL, params={"limit": 2000}, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("data", [])


def _organizer_subdomain(reg_url: str) -> str:
    hostname = urlparse(reg_url).hostname or ""
    subdomain = hostname.split(".")[0]
    return subdomain if subdomain not in ("myruntime", "") else ""


_FB_NON_PAGE_SEGMENTS = frozenset(
    ["events", "groups", "pages", "people", "profile.php", "watch", "marketplace"]
)


def _fb_handle(fb_url: str) -> str:
    parts = [p for p in urlparse(fb_url).path.split("/") if p]
    if not parts:
        return ""
    handle = parts[0]
    return "" if handle in _FB_NON_PAGE_SEGMENTS else handle


def _direct_org_key(ext_links: dict) -> tuple[str, str, str, str] | None:
    fb = (ext_links.get("facebook") or "").strip().rstrip("/")
    website = (ext_links.get("website") or "").strip().rstrip("/")
    ig = (ext_links.get("instagram") or "").strip().rstrip("/")

    if fb:
        handle = _fb_handle(fb)
        if handle:
            return handle, fb, website, ig
    if website:
        hostname = urlparse(website).hostname or website
        key = hostname.removeprefix("www.")
        return key, fb, website, ig
    if ig:
        parts = [p for p in urlparse(ig).path.split("/") if p]
        key = parts[0] if parts else ""
        if key:
            return key, fb, website, ig
    return None


def _event_external_id(reg_url: str, name: str) -> str:
    parsed = urlparse(reg_url)
    m = re.search(r"/register/(.+)$", parsed.path.rstrip("/"))
    if m:
        return m.group(1)
    subdomain = (parsed.hostname or "").split(".")[0]
    if subdomain in ("myruntime", ""):
        subdomain = "fallback"
    name_slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{subdomain}/{name_slug}"


def _slugify(name: str) -> str:
    slug = re.sub(r"[^\w-]", "-", name.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "organizer"


def _unique_slug(cur, base: str) -> str:
    slug = _slugify(base)
    i = 2
    while True:
        cur.execute("SELECT 1 FROM events_organizer WHERE slug = %s", (slug,))
        if not cur.fetchone():
            return slug
        slug = f"{_slugify(base)}-{i}"
        i += 1


# ---------------------------------------------------------------------------
# Main backfill logic
# ---------------------------------------------------------------------------

def main(dry_run: bool) -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        sys.exit("DATABASE_URL not set")

    print("Fetching MyRuntime API...")
    items = _fetch_api()
    print(f"  {len(items)} events received")

    # Build a map: external_id → (organizer_key, fb_url, website, ig_url)
    # Only for direct-hosted events.
    direct_map: dict[str, tuple[str, str, str, str] | None] = {}
    org_details: dict[str, tuple[str, str, str]] = {}  # key → (fb, website, ig)

    for item in items:
        reg_url = item.get("regUrl") or ""
        name = (item.get("name") or "").strip()
        if not reg_url or not name:
            continue
        if _organizer_subdomain(reg_url):
            continue  # subdomain event — already correct
        ext_links = item.get("externalLinks") or {}
        ext_id = _event_external_id(reg_url, name)
        result = _direct_org_key(ext_links)
        direct_map[ext_id] = result
        if result:
            key, fb, website, ig = result
            if key not in org_details:
                org_details[key] = (fb, website, ig)

    print(f"  {len(direct_map)} direct-hosted events found")
    print(f"  {len(org_details)} unique organizer keys derived")
    unattributed = sum(1 for v in direct_map.values() if v is None)
    print(f"  {unattributed} events have no usable link (will be unattributed)")

    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # 1. Find the old "direct" organizer row (if it exists)
        cur.execute(
            "SELECT id FROM events_organizer WHERE source = 'myruntime' AND external_id = 'direct'"
        )
        direct_row = cur.fetchone()
        direct_org_id = direct_row["id"] if direct_row else None
        if direct_org_id:
            print(f"\nFound existing 'direct' organizer row (id={direct_org_id})")
        else:
            print("\nNo 'direct' organizer row found in DB")

        # 2. Ensure Organizer rows exist for each derived key
        key_to_org_id: dict[str, int] = {}
        for key, (fb, website, ig) in org_details.items():
            cur.execute(
                "SELECT id FROM events_organizer WHERE source = 'myruntime' AND external_id = %s",
                (key,),
            )
            row = cur.fetchone()
            if row:
                key_to_org_id[key] = row["id"]
                if not dry_run:
                    # Fill blank link fields
                    cur.execute(
                        """
                        UPDATE events_organizer SET
                            facebook_url = CASE WHEN facebook_url = '' AND %s != '' THEN %s ELSE facebook_url END,
                            website      = CASE WHEN website = ''      AND %s != '' THEN %s ELSE website END,
                            instagram_url= CASE WHEN instagram_url = '' AND %s != '' THEN %s ELSE instagram_url END,
                            updated_at   = NOW()
                        WHERE id = %s
                        """,
                        (fb, fb, website, website, ig, ig, row["id"]),
                    )
                print(f"  [exists] organizer '{key}' id={row['id']}")
            else:
                slug = _unique_slug(cur, key)
                if not dry_run:
                    cur.execute(
                        """
                        INSERT INTO events_organizer
                            (name, slug, status, source, source_url, external_id,
                             facebook_url, website, instagram_url, description,
                             email, phone, address, city, country,
                             enrichment_source,
                             created_at, updated_at)
                        VALUES (%s,%s,'pending','myruntime',%s,%s,%s,%s,%s,'','','','','','','',NOW(),NOW())
                        RETURNING id
                        """,
                        (key, slug, _EVENTS_PAGE, key, fb, website, ig),
                    )
                    new_id = cur.fetchone()["id"]
                    key_to_org_id[key] = new_id
                    print(f"  [created] organizer '{key}' id={new_id} slug={slug}")
                else:
                    key_to_org_id[key] = -1
                    print(f"  [dry-run] would create organizer '{key}' slug={slug}")

        # 3. For each direct-hosted event in the DB, update organizer + organizer_ref
        updated = 0
        detached = 0
        not_found = 0
        for ext_id, result in direct_map.items():
            cur.execute(
                "SELECT id, organizer, organizer_ref_id FROM events_event WHERE source = 'myruntime' AND external_id = %s",
                (ext_id,),
            )
            event_row = cur.fetchone()
            if not event_row:
                not_found += 1
                continue

            if result:
                key, fb, website, ig = result
                new_org_name = key
                new_org_ref = key_to_org_id.get(key)
                new_org_url = fb or website or ig
            else:
                new_org_name = ""
                new_org_ref = None
                new_org_url = ""

            if not dry_run:
                cur.execute(
                    """
                    UPDATE events_event SET
                        organizer = %s,
                        organizer_url = %s,
                        organizer_ref_id = %s
                    WHERE id = %s
                    """,
                    (new_org_name, new_org_url, new_org_ref, event_row["id"]),
                )
            if result:
                updated += 1
            else:
                detached += 1

        print(f"\nEvents updated: {updated} re-attributed, {detached} unattributed, {not_found} not in DB")

        # 4. Delete the old "direct" organizer row
        if direct_org_id:
            # First detach any remaining events still pointing to it
            cur.execute(
                "SELECT COUNT(*) AS n FROM events_event WHERE organizer_ref_id = %s",
                (direct_org_id,),
            )
            remaining = cur.fetchone()["n"]
            if remaining:
                print(f"  {remaining} events still reference 'direct' — detaching organizer_ref")
                if not dry_run:
                    cur.execute(
                        "UPDATE events_event SET organizer_ref_id = NULL WHERE organizer_ref_id = %s",
                        (direct_org_id,),
                    )
            if not dry_run:
                cur.execute("DELETE FROM events_organizer WHERE id = %s", (direct_org_id,))
                print(f"  Deleted 'direct' organizer row (id={direct_org_id})")
            else:
                print(f"  [dry-run] would delete 'direct' organizer row (id={direct_org_id})")

        if dry_run:
            print("\nDry run complete — no changes written")
            conn.rollback()
        else:
            conn.commit()
            print("\nBackfill committed.")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print what would change without writing")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
