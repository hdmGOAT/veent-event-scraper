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
    price: str = ""
    category: str = ""
    external_id: str = ""
    # URL of the listing page this event was scraped from.
    source_url: str = ""
    organizer: str = ""
    organizer_url: str = ""
    venue: ScrapedVenue | None = None


class BaseScraper:
    """Subclass this and implement ``fetch``.

    Set ``source`` to a stable, unique key — it is stored on every row and
    used together with ``external_id`` to deduplicate across runs.
    """

    source: str = ""

    def fetch(self) -> Iterable[ScrapedEvent]:
        """Yield ScrapedEvent instances. Implemented by subclasses."""
        raise NotImplementedError

    def run(self) -> dict:
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
            image_url=se.image_url, price=se.price, category=se.category,
            organizer=se.organizer, organizer_url=se.organizer_url,
            organizer_ref=organizer_ref,
            source=source, source_url=se.source_url,
            external_id=se.external_id, scraped_at=now,
        )

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
            for k, v in contact_fields.items():
                setattr(existing, k, v)
            existing.save()
            updated += 1
        else:
            Organizer.objects.create(
                slug=_unique_slug(Organizer, so.name),
                status=Organizer.STATUS_PENDING,
                **contact_fields,
            )
            created += 1

    return {"source": source, "created": created, "updated": updated}


def save_venues(source: str, venues: Iterable[ScrapedVenue]) -> dict:
    """Persist scraped venues directly (no event required).

    Upserts on ``(source, place_id)`` when a ``place_id`` is present, falling
    back to a name match. Mirrors ``save_events`` for venue-only sources such as
    the Google Places scraper.
    """
    now = timezone.now()
    created = updated = 0
    for sv in venues:
        _, was_created = _upsert_venue(source, sv, now)
        if was_created:
            created += 1
        else:
            updated += 1
    return {"source": source, "created": created, "updated": updated}
