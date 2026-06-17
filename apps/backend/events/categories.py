"""Display-only category normalization for the events dashboard.

Maps raw, scraper-stored ``Event.category`` strings (which are often comma-joined
race distances or ticket-tier names) to a small canonical set of human-readable
buckets. This module is intentionally decoupled from the Django ORM so it can be
reused verbatim in a future Option B taxonomy migration or in ``save_events``.

The single public entry point is :func:`normalize_category`.
"""

from __future__ import annotations

import re

# A distance token like "10K", "21KM", "5 km", "42K".
_DISTANCE_RE = re.compile(r"^\d+\s?km?$", re.IGNORECASE)

# Run-event tier/wave names that masquerade as categories.
_WAVE_TIER_TERMS = ("wave", "elite", "competitor", "finisher", "pacer")

# Canonical bucket used for both distance lists and wave/tier names.
_RUN_BUCKET = "Fun Run / Road Race"

# Ordered keyword map: first matching key (whole-word, case-insensitive) wins.
# Each entry is (tuple_of_keywords, canonical_bucket).
_KEYWORD_MAP: tuple[tuple[tuple[str, ...], str], ...] = (
    (("trail",), "Trail Run"),
    (("triathlon", "duathlon"), "Triathlon / Duathlon"),
    (("cycling", "bike", "biking"), "Cycling"),
    (("swim", "swimming"), "Swimming"),
    (("music", "concert", "band", "gig"), "Music"),
    (("festival",), "Festival"),
    (("conference", "summit", "seminar"), "Conference / Seminar"),
    (("workshop", "training", "class"), "Workshop / Training"),
    (("food", "culinary", "dining"), "Food & Dining"),
    (("art", "exhibit", "gallery"), "Arts & Culture"),
    (("charity", "fundrais"), "Charity / Fundraiser"),
    (("sport", "game", "tournament"), "Sports"),
)


def _is_distance_list(raw: str) -> bool:
    """True if any comma-separated part looks like a race distance token."""
    return any(_DISTANCE_RE.match(part.strip()) for part in raw.split(","))


def _matches_keyword(text: str, keyword: str) -> bool:
    """Whole-word (leading word-boundary) keyword match on lowercased ``text``.

    A leading ``\\b`` prevents mid-word false positives ("art" must not match
    "party" or "smart") while still allowing stems/plurals to match
    ("fundrais" -> "fundraiser", "wave" -> "waves").
    """
    return re.search(r"\b" + re.escape(keyword), text) is not None


def normalize_category(raw: str) -> str:
    """Map a raw category string to a canonical display bucket.

    Ordered rules, first match wins:

    1. Empty / whitespace-only input returns ``""`` (never crashes).
    2. Distance-list detection (e.g. ``"10K, 5K, 3K"``) -> ``"Fun Run / Road Race"``.
    3. Wave/tier name detection (e.g. ``"SUB1 Elite, Open Wave"``) -> ``"Fun Run / Road Race"``.
    4. Keyword map (whole-word, case-insensitive) -> canonical bucket.
    5. Fallback: ``raw.strip().title()`` so unknown-but-clean values survive.

    Returns plain strings with no ORM coupling.
    """
    if raw is None:
        return ""

    stripped = raw.strip()
    if not stripped:
        return ""

    lowered = stripped.lower()

    # Rule 2: distance list.
    if _is_distance_list(stripped):
        return _RUN_BUCKET

    # Rule 3: wave/tier names (only reached when not a distance list).
    if any(_matches_keyword(lowered, term) for term in _WAVE_TIER_TERMS):
        return _RUN_BUCKET

    # Rule 4: keyword map.
    for keywords, bucket in _KEYWORD_MAP:
        if any(_matches_keyword(lowered, keyword) for keyword in keywords):
            return bucket

    # Rule 5: fallback.
    return stripped.title()
