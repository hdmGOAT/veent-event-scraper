"""Scraper for racemeister.com upcoming and recurring events.

Event data is served by a Google Apps Script JSON API whose URLs are
CryptoJS-AES-encrypted in racemeister.com's links.js. The decrypted endpoints
are pinned below as constants. Each endpoint returns a flat JSON list of event
objects (``Race``, ``Date``, ``Address``, ``Page``, ...); the listing carries no
price, so ``price`` is left empty.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from django.utils import timezone

from .proxy_manager import get_session
from .base import BaseScraper, ScrapedEvent, ScrapedOrganizer, ScrapedVenue, save_events, save_organizers

logger = logging.getLogger(__name__)

# Decrypted from https://www.racemeister.com/js/api/links.js (CryptoJS AES key "1")
_EVENTS_API = (
    "https://script.google.com/macros/s/"
    "AKfycbz0IYaNlcASnvaGNOu7gNmlieWx3DYWp8B0Bhc5UFNAWRweVftYOzmzQYa8CMjWam7nLg/exec?q=events"
)
_RECURRING_API = (
    "https://script.google.com/macros/s/"
    "AKfycbw8CyZSz1BHWzrCfD7bMNz-Hrpk7wAjw4QWv7wgWXSAgXzOfHX5Zb6QTiH-siCJoRJXfw/exec?q=events"
)
_SITE = "https://www.racemeister.com/"
_SOURCE_URL = "https://www.racemeister.com/events"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; EventScraper/1.0)"
}
_TIMEOUT = 30


def _parse_date(date_str: str) -> tuple[datetime | None, datetime | None]:
    """Parse free-text dates like 'June 20, 2026' or 'August 20-23, 2026'.

    A single-day string yields ``(starts_at, None)``; a day-range string yields
    ``(starts_at, ends_at)`` sharing the same month and year. Returned datetimes
    are timezone-aware (USE_TZ is active).
    """
    date_str = (date_str or "").strip()
    if not date_str:
        return None, None

    def _aware(month: str, day: str, year: str) -> datetime:
        naive = datetime.strptime(f"{month} {day}, {year}", "%B %d, %Y")
        return timezone.make_aware(naive)

    range_match = re.match(r"^([A-Za-z]+)\s+(\d{1,2})-(\d{1,2}),\s*(\d{4})$", date_str)
    if range_match:
        month, start_day, end_day, year = range_match.groups()
        try:
            return _aware(month, start_day, year), _aware(month, end_day, year)
        except ValueError:
            return None, None

    single_match = re.match(r"^([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})$", date_str)
    if single_match:
        try:
            return _aware(*single_match.groups()), None
        except ValueError:
            pass

    logger.warning("Racemeister: unparseable date %r", date_str)
    return None, None


def _external_id(item: dict) -> str:
    """Stable id from the ``Page`` slug, falling back to the slugified race name."""
    page = (item.get("Page") or "").strip()
    if page and page != "#":
        segment = page.rstrip("/").split("/")[-1]
        slug = re.sub(r"[^a-z0-9]+", "-", segment.lower()).strip("-")
        if slug:
            return slug

    name = (item.get("Race") or "").strip()
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _parse_address(address: str) -> tuple[str, str]:
    """Return ``(venue_name, city)`` where city is the last comma-separated part."""
    address = (address or "").strip()
    if not address:
        return "", ""
    parts = [p.strip() for p in address.split(",") if p.strip()]
    city = parts[-1] if len(parts) > 1 else ""
    return address, city


def _resolve_page_url(item: dict) -> str:
    """Resolve the event ``Page`` to an absolute URL, else fall back to ``Website``."""
    page = (item.get("Page") or "").strip()
    if page and page != "#":
        if page.startswith("http"):
            return page
        return _SITE + page.lstrip("/")
    return (item.get("Website") or "").strip()


def _build_organizers(items: list[dict]) -> list[ScrapedOrganizer]:
    seen: dict[str, ScrapedOrganizer] = {}
    for item in items:
        names_raw = (item.get("Organizer") or "").strip()
        website = (item.get("Website") or "").strip()
        for name in [n.strip() for n in names_raw.split(",") if n.strip()]:
            external_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            if external_id not in seen:
                seen[external_id] = ScrapedOrganizer(
                    name=name,
                    external_id=external_id,
                    source_url=_SOURCE_URL,
                    website=website if not website.startswith("https://www.facebook.com") else "",
                    facebook_url=website if website.startswith("https://www.facebook.com") else "",
                )
    return list(seen.values())


class RacemeisterEventsScraper(BaseScraper):
    source = "racemeister_events"

    def _fetch_events(self, url: str) -> list[dict]:
        try:
            resp = get_session().get(url, headers=_HEADERS, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("Racemeister events request failed for %s: %s", url, exc)
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for value in data.values():
                if isinstance(value, list):
                    return value
        return []

    def run(self, **_kwargs) -> dict:
        items = self._fetch_events(_EVENTS_API) + self._fetch_events(_RECURRING_API)
        logger.info("Racemeister: received %d raw events", len(items))

        seen_ids: set[str] = set()
        events = []
        for item in items:
            name = (item.get("Race") or "").strip()
            if not name:
                continue
            external_id = _external_id(item)
            if external_id in seen_ids:
                continue
            seen_ids.add(external_id)
            starts_at, ends_at = _parse_date(item.get("Date") or "")
            description = re.sub(r"<br\s*/?>", "\n", item.get("Description") or "", flags=re.I).strip()
            venue = None
            address = (item.get("Address") or "").strip()
            if address:
                venue_name, city = _parse_address(address)
                venue = ScrapedVenue(name=venue_name, city=city, country="Philippines", source_url=_SOURCE_URL)
            events.append(ScrapedEvent(
                name=name, description=description, starts_at=starts_at, ends_at=ends_at,
                url=_resolve_page_url(item), image_url=(item.get("Image") or "").strip(),
                price="", category=(item.get("Classification") or "").strip(),
                external_id=external_id, source_url=_SOURCE_URL,
                organizer=(item.get("Organizer") or "").strip(),
                organizer_url=(item.get("Website") or "").strip(), venue=venue,
            ))

        organizers = _build_organizers(items)
        logger.info("Racemeister: found %d unique organizers", len(organizers))

        events_result = save_events(self.source, events)
        organizers_result = save_organizers(self.source, organizers)
        return {
            **events_result,
            "organizers_created": organizers_result["created"],
            "organizers_updated": organizers_result["updated"],
        }

    def fetch(self):
        items = self._fetch_events(_EVENTS_API) + self._fetch_events(_RECURRING_API)
        logger.info("Racemeister: received %d raw events", len(items))

        seen: set[str] = set()
        for item in items:
            name = (item.get("Race") or "").strip()
            if not name:
                continue

            external_id = _external_id(item)
            if external_id in seen:
                continue
            seen.add(external_id)

            starts_at, ends_at = _parse_date(item.get("Date") or "")
            description = re.sub(
                r"<br\s*/?>", "\n", item.get("Description") or "", flags=re.I
            ).strip()

            venue = None
            address = (item.get("Address") or "").strip()
            if address:
                venue_name, city = _parse_address(address)
                venue = ScrapedVenue(
                    name=venue_name,
                    city=city,
                    country="Philippines",
                    source_url=_SOURCE_URL,
                )

            yield ScrapedEvent(
                name=name,
                description=description,
                starts_at=starts_at,
                ends_at=ends_at,
                url=_resolve_page_url(item),
                image_url=(item.get("Image") or "").strip(),
                price="",
                category=(item.get("Classification") or "").strip(),
                external_id=external_id,
                source_url=_SOURCE_URL,
                organizer=(item.get("Organizer") or "").strip(),
                organizer_url=(item.get("Website") or "").strip(),
                venue=venue,
            )
