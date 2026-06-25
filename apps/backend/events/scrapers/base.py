"""Base scraper interface and persistence helpers.

A scraper's job is to yield plain ``ScrapedEvent`` / ``ScrapedVenue`` dataclasses.
Turning those into database rows (slugging, dedup, upsert) is handled centrally
in ``save_events`` so individual scrapers stay small.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from django.utils import timezone
from django.utils.text import slugify

logger = logging.getLogger(__name__)

from events.models import Event, Organizer, Venue


@dataclass
class ScrapedVenue:
    name: str
    address: str = ""
    city: str = ""
    country: str = ""
    website: str = ""
    latitude: float | None = None
    longitude: float | None = None
    source_url: str = ""
    # Stable id from the source (e.g. Google Places place_id) for dedup.
    place_id: str = ""
    # Classification / descriptive metadata (Places "About" data).
    primary_type: str = ""
    primary_type_display: str = ""
    types: list = field(default_factory=list)
    about: str = ""
    amenities: dict = field(default_factory=dict)
    rating: float | None = None
    price_level: str = ""


@dataclass
class ScrapedOrganizer:
    name: str
    website: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    city: str = ""
    country: str = ""
    facebook_url: str = ""
    instagram_url: str = ""
    description: str = ""
    external_id: str = ""
    source_url: str = ""


@dataclass
class ScrapedEvent:
    name: str
    description: str = ""
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    url: str = ""
    image_url: str = ""
    registration_url: str = ""
    price: str = ""
    category: str = ""
    external_id: str = ""
    # URL of the listing page this event was scraped from.
    source_url: str = ""
    organizer: str = ""
    organizer_url: str = ""
    venue: ScrapedVenue | None = None
    address: str = ""
    city: str = ""
    country: str = ""
    raw_text: str = ""
    post_date: datetime | None = None


class BaseScraper:
    """Subclass this and implement ``fetch``.

    Set ``source`` to a stable, unique key — it is stored on every row and
    used together with ``external_id`` to deduplicate across runs.
    """

    source: str = ""
    # Opt-in flag: when True, the Scraper Center shows a keyword picker for
    # this scraper and its ``run()`` accepts ``query_ids``. Default off.
    supports_keywords: bool = False

    def fetch(self) -> Iterable[ScrapedEvent]:
        """Yield ScrapedEvent instances. Implemented by subclasses."""
        raise NotImplementedError

    def run(self, on_progress=None, **_kwargs) -> dict:
        if not self.source:
            raise ValueError(f"{type(self).__name__}.source must be set")
        events = list(self.fetch())
        result = save_events(self.source, events)
        _categorize_after_save(result)
        return result


def _categorize_after_save(result: dict) -> None:
    """Auto-classify newly saved events. Never crashes the scraper run.

    Reads ``event_ids`` from a ``save_events`` result and asks the AI
    categorizer to classify them. Any failure (CLI missing, timeout, bad
    output) is logged as a warning and swallowed — categorization is a
    best-effort enrichment, not a hard dependency of scraping.
    """
    event_ids = result.get("event_ids") if isinstance(result, dict) else None
    if not event_ids:
        return
    try:
        from events.ai_categories import categorize_events_by_ids

        categorize_events_by_ids(event_ids)
    except Exception:  # noqa: BLE001 — never let categorization crash a scrape
        logger.warning(
            "Auto-categorization failed for %d events; they were saved with "
            "agent_categories=[]. Run `manage.py categorize_events --uncategorized` "
            "to backfill.",
            len(event_ids),
            exc_info=True,
        )


def _dedup_after_save(entity: str, ids: list[int]) -> None:
    """Post-save dedup guard. Best-effort; never raises to the caller.

    A lightweight inline guard run at scrape time, kept deliberately cheaper
    than the standalone ``scripts/deduplicate.py`` tool:

    * events     — URL-exact match only (fast path; name+date matching is left
                   to the standalone script).
    * venues     — website URL match, then name+city match.
    * organizers — website URL match, then name match.

    Any failure is logged as a warning and swallowed so a dedup bug can never
    abort a scrape run, mirroring ``_categorize_after_save``.
    """
    if not ids:
        return
    try:
        if entity == "events":
            _dedup_events_by_url(ids)
        elif entity == "venues":
            _dedup_venues_by_name_city(ids)
        elif entity == "organizers":
            _dedup_organizers_by_website(ids)
    except Exception:  # noqa: BLE001 — never let dedup crash a scrape
        logger.warning("_dedup_after_save(%s) failed", entity, exc_info=True)


def _normalize_name(name: str | None) -> str:
    """Lowercase, strip accents + punctuation, collapse whitespace. "" for blank."""
    import re
    import unicodedata

    if not name:
        return ""
    text = unicodedata.normalize("NFKD", str(name))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _dedup_normalize_url(url: str | None) -> str:
    """Scheme-less, UTM-stripped, query-sorted, slash-trimmed URL key.

    Unlike ``_normalize_url`` (which preserves the scheme for organizer
    resolution), the dedup path drops the scheme so ``http://`` and ``https://``
    collapse together — matching scripts/dedup.normalize_url.
    """
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    if not url:
        return ""
    parsed = urlparse(str(url).strip().lower())
    netloc, path = parsed.netloc, parsed.path
    if not netloc and path:
        netloc, _, rest = path.partition("/")
        path = "/" + rest if rest else ""
    path = path.rstrip("/")
    pairs = [
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.startswith("utm_")
    ]
    pairs.sort()
    return urlunparse(("", netloc, path, "", urlencode(pairs), ""))


def _group_by(rows, key_fn) -> list[list[int]]:
    """Bucket ``(pk, *)`` rows by ``key_fn``; return groups with 2+ pks.

    The first pk in each group (lowest pk = oldest row) is treated as the
    winner for this lightweight inline path.
    """
    buckets: dict = {}
    for row in rows:
        key = key_fn(row)
        if key in ("", None):
            continue
        buckets.setdefault(key, []).append(row[0])
    return [sorted(pks) for pks in buckets.values() if len(pks) >= 2]


def _fill_missing(winner, losers, protected: set[str]) -> None:
    """Copy each empty winner field from the first loser that has a value."""
    skip = {"id", "slug", "created_at", "updated_at"} | protected
    for field in winner._meta.concrete_fields:
        name = field.name
        if name in skip or field.is_relation:
            continue
        w_value = getattr(winner, name)
        if not _is_blank(w_value):
            continue
        for loser in losers:
            l_value = getattr(loser, name)
            if not _is_blank(l_value):
                setattr(winner, name, l_value)
                break


def _is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, dict, tuple)) and len(value) == 0:
        return True
    return False


def _dedup_events_by_url(ids: list[int]) -> None:
    """Merge events in ``ids`` that share a normalized URL (URL-exact only)."""
    rows = list(
        Event.objects.filter(pk__in=ids).exclude(url="").values_list("pk", "url")
    )
    for group in _group_by(rows, lambda r: _dedup_normalize_url(r[1])):
        winner_id, loser_ids = group[0], group[1:]
        winner = Event.objects.get(pk=winner_id)
        losers = list(Event.objects.filter(pk__in=loser_ids))
        _fill_missing(winner, losers, {"agent_categories", "source", "external_id"})
        winner.save()
        Event.objects.filter(pk__in=loser_ids).delete()


def _dedup_venues_by_name_city(ids: list[int]) -> None:
    """Merge venues in ``ids`` by website URL, then by name+city.

    Name+city groups are skipped when their members carry differing non-empty
    ``place_id`` values: a distinct stable source id means a genuinely distinct
    place, so the upsert path's place_id-keyed identity is preserved.
    """
    qs = Venue.objects.filter(pk__in=ids)
    web_rows = list(qs.exclude(website="").values_list("pk", "website"))
    nc_rows = list(qs.values_list("pk", "name", "city"))
    place_ids = dict(qs.values_list("pk", "place_id"))

    groups = _group_by(web_rows, lambda r: _dedup_normalize_url(r[1]))
    groups += [
        g
        for g in _group_by(
            nc_rows,
            lambda r: (_normalize_name(r[1]), (r[2] or "").strip().lower()),
        )
        if not _has_conflicting_place_ids(g, place_ids)
    ]
    _apply_groups(
        Venue, _dedup_merge_overlaps(groups),
        protected={"agents_primary_types", "verification_status", "place_id", "source"},
        venue_fk=True,
    )


def _has_conflicting_place_ids(pks: list[int], place_ids: dict) -> bool:
    """True if the group contains two or more distinct non-empty place_ids."""
    distinct = {p for p in (place_ids.get(pk, "") for pk in pks) if p}
    return len(distinct) >= 2


def _dedup_organizers_by_website(ids: list[int]) -> None:
    """Merge organizers in ``ids`` by website URL, then by name."""
    qs = Organizer.objects.filter(pk__in=ids)
    web_rows = list(qs.exclude(website="").values_list("pk", "website"))
    name_rows = list(qs.values_list("pk", "name"))
    groups = _group_by(web_rows, lambda r: _dedup_normalize_url(r[1]))
    groups += _group_by(name_rows, lambda r: _normalize_name(r[1]))
    _apply_groups(
        Organizer, _dedup_merge_overlaps(groups),
        protected={"agents_primary_types", "status", "source", "external_id"},
        organizer_fk=True,
    )


def _dedup_merge_overlaps(groups: list[list[int]]) -> list[list[int]]:
    """Union-merge groups that share any pk; keep lowest pk first as winner."""
    merged: list[set[int]] = []
    for group in groups:
        g = set(group)
        placed = False
        for existing in merged:
            if existing & g:
                existing |= g
                placed = True
                break
        if not placed:
            merged.append(g)
    # Second pass to collapse any now-bridged sets.
    result: list[set[int]] = []
    for s in merged:
        placed = False
        for r in result:
            if r & s:
                r |= s
                placed = True
                break
        if not placed:
            result.append(set(s))
    return [sorted(s) for s in result if len(s) >= 2]


def _apply_groups(model, groups, protected, venue_fk=False, organizer_fk=False):
    """Merge each group's losers into the winner and hard-delete the losers."""
    for group in groups:
        winner_id, loser_ids = group[0], group[1:]
        if not loser_ids:
            continue
        winner = model.objects.get(pk=winner_id)
        losers = list(model.objects.filter(pk__in=loser_ids))
        _fill_missing(winner, losers, protected)
        winner.save()
        if venue_fk:
            Event.objects.filter(venue_id__in=loser_ids).update(venue_id=winner_id)
        if organizer_fk:
            Event.objects.filter(organizer_ref_id__in=loser_ids).update(
                organizer_ref_id=winner_id
            )
        model.objects.filter(pk__in=loser_ids).delete()


def _unique_slug(model, base: str) -> str:
    base = slugify(base) or "item"
    slug = base
    i = 2
    while model.objects.filter(slug=slug).exists():
        slug = f"{base}-{i}"
        i += 1
    return slug


def _upsert_venue(source: str, sv: ScrapedVenue, now) -> tuple[Venue, bool]:
    """Upsert a venue. Returns (venue, created).

    Dedup prefers the stable ``place_id`` (scoped to the source) when present,
    falling back to a name match for sources without a stable id.
    """
    venue = None
    if sv.place_id:
        # With a stable id, match only on it — a different id is a different
        # place even if the name collides.
        venue = Venue.objects.filter(source=source, place_id=sv.place_id).first()
    else:
        venue = (
            Venue.objects.filter(source=source, name=sv.name).first()
            or Venue.objects.filter(name=sv.name).first()
        )
    fields = dict(
        address=sv.address, city=sv.city, country=sv.country,
        website=sv.website, latitude=sv.latitude, longitude=sv.longitude,
        source=source, source_url=sv.source_url, place_id=sv.place_id,
        primary_type=sv.primary_type,
        primary_type_display=sv.primary_type_display,
        types=sv.types, about=sv.about, amenities=sv.amenities,
        rating=sv.rating, price_level=sv.price_level,
        scraped_at=now,
    )
    if venue:
        for k, v in fields.items():
            setattr(venue, k, v)
        venue.save()
        return venue, False
    venue = Venue.objects.create(
        name=sv.name, slug=_unique_slug(Venue, sv.name), **fields
    )
    return venue, True


def _normalize_url(url: str) -> str:
    """Lowercase scheme+host and strip a trailing slash. Returns "" for blank."""
    from urllib.parse import urlparse, urlunparse

    if not url:
        return ""
    parsed = urlparse(url.strip())
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
    )
    return urlunparse(normalized).rstrip("/")


def _resolve_organizer(organizer_url: str, organizer_name: str) -> Organizer | None:
    """Resolve an existing Organizer by URL then unambiguous name. Never creates rows.

    Pass 1: normalize ``organizer_url`` and match against ``Organizer.website``.
    Pass 2: case-insensitive match on ``organizer_name``; skip if ambiguous (>1).
    Returns the matched ``Organizer`` or ``None``.
    """
    key = _normalize_url(organizer_url)
    if key:
        for org in Organizer.objects.filter(website__gt=""):
            if _normalize_url(org.website) == key:
                return org

    name = (organizer_name or "").strip()
    if name:
        matches = list(Organizer.objects.filter(name__iexact=name)[:2])
        if len(matches) == 1:
            return matches[0]

    return None


def save_events(source: str, events: Iterable[ScrapedEvent]) -> dict:
    """Persist scraped events, upserting on (source, external_id) when present.

    Returns a dict including ``event_ids``: the PKs of every event created or
    updated this run, so callers (e.g. ``BaseScraper.run``) can categorize them.
    """
    now = timezone.now()
    created = updated = 0
    event_ids: list[int] = []

    for se in events:
        venue = _upsert_venue(source, se.venue, now)[0] if se.venue else None

        existing = None
        if se.external_id:
            existing = Event.objects.filter(
                source=source, external_id=se.external_id
            ).first()

        organizer_ref = _resolve_organizer(se.organizer_url, se.organizer)

        fields = dict(
            name=se.name, description=se.description, venue=venue,
            starts_at=se.starts_at, ends_at=se.ends_at, url=se.url,
            image_url=se.image_url, registration_url=se.registration_url,
            price=se.price, category=se.category,
            organizer=se.organizer, organizer_url=se.organizer_url,
            organizer_ref=organizer_ref,
            source=source, source_url=se.source_url,
            external_id=se.external_id, scraped_at=now,
        )

        # Only write when provided so scrapers that don't populate these
        # fields never clear existing values on re-scrape.
        if se.raw_text:
            fields["raw_text"] = se.raw_text
        if se.post_date is not None:
            fields["post_date"] = se.post_date

        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            existing.save()
            updated += 1
            event_ids.append(existing.pk)
        else:
            obj = Event.objects.create(slug=_unique_slug(Event, se.name), **fields)
            created += 1
            event_ids.append(obj.pk)

    _dedup_after_save("events", event_ids)

    return {
        "source": source,
        "created": created,
        "updated": updated,
        "event_ids": event_ids,
    }


def save_organizers(source: str, organizers: Iterable[ScrapedOrganizer]) -> dict:
    """Persist scraped organizers, upserting on (source, external_id) when present.

    ``status`` is intentionally never overwritten on re-scrape so that admin
    confirm/reject decisions survive subsequent runs.
    """
    now = timezone.now()
    created = updated = 0
    organizer_ids: list[int] = []

    for so in organizers:
        existing = None
        if so.external_id:
            existing = Organizer.objects.filter(
                source=source, external_id=so.external_id
            ).first()
        if existing is None:
            existing = Organizer.objects.filter(source=source, name=so.name).first()

        contact_fields = dict(
            name=so.name, website=so.website, email=so.email, phone=so.phone,
            address=so.address, city=so.city, country=so.country,
            facebook_url=so.facebook_url, instagram_url=so.instagram_url,
            description=so.description, source=source, source_url=so.source_url,
            external_id=so.external_id, scraped_at=now,
        )

        if existing:
            # Always update provenance and display name.
            always_update = {"name", "source", "scraped_at"}
            changed = False
            for k, v in contact_fields.items():
                if k in always_update:
                    setattr(existing, k, v)
                    changed = True
                elif v and not getattr(existing, k):
                    # Only fill blank fields — never clobber existing contact data.
                    setattr(existing, k, v)
                    changed = True
            if changed:
                existing.save()
            updated += 1
            organizer_ids.append(existing.pk)
        else:
            org = Organizer.objects.create(
                slug=_unique_slug(Organizer, so.name),
                status=Organizer.STATUS_PENDING,
                **contact_fields,
            )
            created += 1
            organizer_ids.append(org.pk)

    _dedup_after_save("organizers", organizer_ids)

    return {"source": source, "created": created, "updated": updated}


def save_venues(source: str, venues: Iterable[ScrapedVenue]) -> dict:
    """Persist scraped venues directly (no event required).

    Upserts on ``(source, place_id)`` when a ``place_id`` is present, falling
    back to a name match. Mirrors ``save_events`` for venue-only sources such as
    the Google Places scraper.
    """
    now = timezone.now()
    created = updated = 0
    venue_ids: list[int] = []
    for sv in venues:
        venue, was_created = _upsert_venue(source, sv, now)
        venue_ids.append(venue.pk)
        if was_created:
            created += 1
        else:
            updated += 1

    _dedup_after_save("venues", venue_ids)

    return {"source": source, "created": created, "updated": updated}
