"""Deduplication utilities: normalization helpers, duplicate finders, merge functions.

Used by the deduplicate.py standalone script. Pure Python plus raw-SQL helpers
that operate on a psycopg2 cursor — no Django imports, so this module can be
imported by both the standalone script and the test suite without Django setup.

Duplicate-finder functions return ``list[list[int]]`` where each sub-list is an
ordered group ``[winner_id, *loser_ids]``. Merge functions receive a cursor, a
winner id and the loser ids for the relevant table; they enrich the winner with
the losers' non-null fields, remap foreign keys, and hard-delete the losers.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# ---------------------------------------------------------------------------
# Normalization helpers (pure Python, no DB)
# ---------------------------------------------------------------------------


def normalize_name(name: str | None) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace.

    Returns "" for None/blank input. ``"Café Évènement!"`` → ``"cafe evenement"``.
    """
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", str(name))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_url(url: str | None) -> str:
    """Scheme-less, UTM-stripped, query-sorted, trailing-slash-stripped URL key.

    Drops the scheme entirely so ``http://`` and ``https://`` collapse together.
    Removes any query key starting with ``utm_``, sorts the remaining params
    alphabetically, and strips a trailing slash from the path. Returns "" for
    blank/None input.
    """
    if not url:
        return ""
    parsed = urlparse(str(url).strip().lower())
    # When there is no scheme, urlparse puts the host in ``path``; rebuild a
    # consistent netloc+path regardless of whether a scheme was present.
    netloc = parsed.netloc
    path = parsed.path
    if not netloc and path:
        # e.g. "example.com/page" → netloc="example.com", path="/page"
        netloc, _, rest = path.partition("/")
        path = "/" + rest if rest else ""
    path = path.rstrip("/")

    query_pairs = [
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.startswith("utm_")
    ]
    query_pairs.sort()
    query = urlencode(query_pairs)

    # scheme dropped intentionally (empty); keep netloc + path + query.
    return urlunparse(("", netloc, path, "", query, ""))


def normalize_date(dt) -> date | None:
    """Return a UTC ``date`` from a datetime, pass through a date, else None."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.date()
    if isinstance(dt, date):
        return dt
    return None


def normalize_city(city: str | None) -> str:
    """Lowercase and strip whitespace. Returns "" for None/blank input."""
    if not city:
        return ""
    return str(city).strip().lower()


# ---------------------------------------------------------------------------
# Grouping + winner selection helpers
# ---------------------------------------------------------------------------


def _richness_score(row: dict) -> int:
    """Count fields that are not None and not an empty string/collection."""
    score = 0
    for value in row.values():
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        if isinstance(value, (list, dict, tuple)) and len(value) == 0:
            continue
        score += 1
    return score


def _merge_overlapping_groups(groups: list[list[int]]) -> list[list[int]]:
    """Union-merge any groups that share at least one id. Order-preserving."""
    merged: list[set[int]] = []
    for group in groups:
        g = set(group)
        hit = None
        for existing in merged:
            if existing & g:
                existing |= g
                hit = existing
                break
        if hit is None:
            merged.append(g)
        else:
            # A merge may now bridge previously-separate sets; collapse again.
            collapsed: list[set[int]] = []
            for existing in merged:
                placed = False
                for c in collapsed:
                    if c & existing:
                        c |= existing
                        placed = True
                        break
                if not placed:
                    collapsed.append(set(existing))
            merged = collapsed
    return [sorted(s) for s in merged if len(s) >= 2]


def _select_winner(cursor, table: str, pks: list[int]) -> list[int]:
    """Return ``[winner, *losers]`` ordered by richness then oldest created_at."""
    cursor.execute(
        f"SELECT * FROM {table} WHERE id = ANY(%s)", (list(pks),)
    )
    rows = cursor.fetchall()
    scored = []
    for row in rows:
        d = dict(row)
        created = d.get("created_at")
        scored.append((-_richness_score(d), created, d["id"]))
    # Highest richness first; oldest created_at as tiebreak (None sorts last).
    scored.sort(key=lambda t: (t[0], t[1] is None, t[1]))
    ordered = [t[2] for t in scored]
    return ordered


def _group_by_key(rows: list[dict], key_fn) -> list[list[int]]:
    """Bucket rows by ``key_fn(row)``; return only groups with 2+ ids.

    Rows whose key is falsy (empty string / None) are skipped — they cannot be
    confidently grouped.
    """
    buckets: dict = {}
    for row in rows:
        key = key_fn(row)
        if key in ("", None):
            continue
        buckets.setdefault(key, []).append(row["id"])
    return [ids for ids in buckets.values() if len(ids) >= 2]


# ---------------------------------------------------------------------------
# Duplicate finders
# ---------------------------------------------------------------------------


def find_event_duplicates(cursor) -> list[list[int]]:
    """Find duplicate events via URL, then name+date+city. Ordered groups."""
    # Pass 1 — URL normalized match.
    cursor.execute("SELECT id, url FROM events_event WHERE url != ''")
    url_rows = [dict(r) for r in cursor.fetchall()]
    groups = _group_by_key(url_rows, lambda r: normalize_url(r["url"]))

    # Pass 2 — name + date + city exact match.
    cursor.execute(
        "SELECT e.id, e.name, e.starts_at, v.city "
        "FROM events_event e LEFT JOIN events_venue v ON e.venue_id = v.id"
    )
    nd_rows = [dict(r) for r in cursor.fetchall()]
    groups += _group_by_key(
        nd_rows,
        lambda r: (
            normalize_name(r["name"]),
            normalize_date(r["starts_at"]),
            normalize_city(r["city"]),
        ),
    )

    merged = _merge_overlapping_groups(groups)
    return [_select_winner(cursor, "events_event", pks) for pks in merged]


def find_venue_duplicates(cursor) -> list[list[int]]:
    """Find duplicate venues via website, then name+city. Ordered groups."""
    cursor.execute("SELECT id, website FROM events_venue WHERE website != ''")
    web_rows = [dict(r) for r in cursor.fetchall()]
    groups = _group_by_key(web_rows, lambda r: normalize_url(r["website"]))

    cursor.execute("SELECT id, name, city FROM events_venue")
    nc_rows = [dict(r) for r in cursor.fetchall()]
    groups += _group_by_key(
        nc_rows,
        lambda r: (normalize_name(r["name"]), normalize_city(r["city"])),
    )

    merged = _merge_overlapping_groups(groups)
    return [_select_winner(cursor, "events_venue", pks) for pks in merged]


def find_organizer_duplicates(cursor) -> list[list[int]]:
    """Find duplicate organizers via website, then name. Ordered groups."""
    cursor.execute("SELECT id, website FROM events_organizer WHERE website != ''")
    web_rows = [dict(r) for r in cursor.fetchall()]
    groups = _group_by_key(web_rows, lambda r: normalize_url(r["website"]))

    cursor.execute("SELECT id, name FROM events_organizer")
    name_rows = [dict(r) for r in cursor.fetchall()]
    groups += _group_by_key(name_rows, lambda r: normalize_name(r["name"]))

    merged = _merge_overlapping_groups(groups)
    return [_select_winner(cursor, "events_organizer", pks) for pks in merged]


# ---------------------------------------------------------------------------
# Merge functions
# ---------------------------------------------------------------------------


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, dict, tuple)) and len(value) == 0:
        return True
    return False


def _fill_missing(cursor, table: str, winner_id: int, loser_ids: list[int],
                  skip_fields: set[str]) -> None:
    """Copy each empty winner field from the first loser that has a value."""
    cursor.execute(f"SELECT * FROM {table} WHERE id = %s", (winner_id,))
    winner = dict(cursor.fetchone())
    cursor.execute(
        f"SELECT * FROM {table} WHERE id = ANY(%s)", (list(loser_ids),)
    )
    losers = [dict(r) for r in cursor.fetchall()]

    updates: dict = {}
    for field, w_value in winner.items():
        if field in skip_fields:
            continue
        if not _is_empty(w_value):
            continue
        for loser in losers:
            l_value = loser.get(field)
            if not _is_empty(l_value):
                updates[field] = l_value
                break

    if updates:
        set_clause = ", ".join(f"{col} = %s" for col in updates)
        params = list(updates.values()) + [winner_id]
        cursor.execute(
            f"UPDATE {table} SET {set_clause} WHERE id = %s", params
        )


# Fields never copied from a loser onto the winner.
_EVENT_SKIP = {
    "id", "slug", "created_at", "updated_at",
    "agent_categories", "source", "external_id",
}
_VENUE_SKIP = {
    "id", "slug", "created_at", "updated_at",
    "agents_primary_types", "verification_status", "place_id", "source",
}
_ORGANIZER_SKIP = {
    "id", "slug", "created_at", "updated_at",
    "agents_primary_types", "status", "source", "external_id",
}


def merge_events(cursor, winner_id: int, loser_ids: list[int]) -> None:
    """Enrich winner from losers, then hard-delete losers (no FK remap needed)."""
    if not loser_ids:
        return
    _fill_missing(cursor, "events_event", winner_id, loser_ids, _EVENT_SKIP)
    cursor.execute(
        "DELETE FROM events_event WHERE id = ANY(%s)", (list(loser_ids),)
    )


def merge_venues(cursor, winner_id: int, loser_ids: list[int]) -> None:
    """Enrich winner, remap Event.venue FKs, then hard-delete loser venues."""
    if not loser_ids:
        return
    _fill_missing(cursor, "events_venue", winner_id, loser_ids, _VENUE_SKIP)
    cursor.execute(
        "UPDATE events_event SET venue_id = %s WHERE venue_id = ANY(%s)",
        (winner_id, list(loser_ids)),
    )
    cursor.execute(
        "DELETE FROM events_venue WHERE id = ANY(%s)", (list(loser_ids),)
    )


def merge_organizers(cursor, winner_id: int, loser_ids: list[int]) -> None:
    """Enrich winner, remap Event.organizer_ref FKs, then hard-delete losers."""
    if not loser_ids:
        return
    _fill_missing(
        cursor, "events_organizer", winner_id, loser_ids, _ORGANIZER_SKIP
    )
    cursor.execute(
        "UPDATE events_event SET organizer_ref_id = %s "
        "WHERE organizer_ref_id = ANY(%s)",
        (winner_id, list(loser_ids)),
    )
    cursor.execute(
        "DELETE FROM events_organizer WHERE id = ANY(%s)", (list(loser_ids),)
    )
