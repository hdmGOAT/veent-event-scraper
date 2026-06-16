"""Base scraper interface and persistence helpers.

A scraper's job is to yield plain ``ScrapedEvent`` / ``ScrapedVenue`` dataclasses.
Turning those into database rows (slugging, dedup, upsert) is handled centrally
in ``save_events`` so individual scrapers stay small.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from django.utils import timezone
from django.utils.text import slugify

from events.models import Event, Venue


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
    source_url: str = ""
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
        return save_events(self.source, events)


def _unique_slug(model, base: str) -> str:
    base = slugify(base) or "item"
    slug = base
    i = 2
    while model.objects.filter(slug=slug).exists():
        slug = f"{base}-{i}"
        i += 1
    return slug


def _upsert_venue(source: str, sv: ScrapedVenue, now) -> Venue:
    venue = (
        Venue.objects.filter(source=source, name=sv.name).first()
        or Venue.objects.filter(name=sv.name).first()
    )
    fields = dict(
        address=sv.address, city=sv.city, country=sv.country,
        website=sv.website, latitude=sv.latitude, longitude=sv.longitude,
        source=source, source_url=sv.source_url, scraped_at=now,
    )
    if venue:
        for k, v in fields.items():
            setattr(venue, k, v)
        venue.save()
        return venue
    return Venue.objects.create(
        name=sv.name, slug=_unique_slug(Venue, sv.name), **fields
    )


def save_events(source: str, events: Iterable[ScrapedEvent]) -> dict:
    """Persist scraped events, upserting on (source, external_id) when present."""
    now = timezone.now()
    created = updated = 0

    for se in events:
        venue = _upsert_venue(source, se.venue, now) if se.venue else None

        existing = None
        if se.external_id:
            existing = Event.objects.filter(
                source=source, external_id=se.external_id
            ).first()

        fields = dict(
            name=se.name, description=se.description, venue=venue,
            starts_at=se.starts_at, ends_at=se.ends_at, url=se.url,
            image_url=se.image_url, price=se.price, category=se.category,
            source=source, source_url=se.source_url,
            external_id=se.external_id, scraped_at=now,
        )

        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            existing.save()
            updated += 1
        else:
            Event.objects.create(slug=_unique_slug(Event, se.name), **fields)
            created += 1

    return {"source": source, "created": created, "updated": updated}
