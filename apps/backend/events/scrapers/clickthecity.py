"""Scraper for ClickTheCity Philippines events.

Single-step process: one GET to the unauthenticated JSON REST API returns all
events. No JS rendering or anti-bot bypass needed — plain requests works.

API: GET https://www.clickthecity.com/api/events?limit=1000
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone as dt_timezone

import requests

from .base import BaseScraper, ScrapedEvent, ScrapedVenue, save_events

logger = logging.getLogger(__name__)

_API = "https://www.clickthecity.com/api/events"
_SITE = "https://www.clickthecity.com"
_SOURCE_URL = f"{_SITE}/events"
_TIMEOUT = 30

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, */*",
    "Referer": _SITE,
}


def _parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)
        return dt
    except (ValueError, TypeError):
        logger.warning("clickthecity: could not parse date %r", date_str)
        return None


def _is_external_venue_url(url: str) -> bool:
    """Return True if the URL points somewhere other than clickthecity.com/local."""
    if not url:
        return False
    return _SITE not in url or "/local/" not in url


def _build_venue(event: dict) -> ScrapedVenue | None:
    venue_name = (event.get("venue") or "").strip()
    if not venue_name:
        return None

    location = event.get("location") or {}
    address_obj = location.get("address") or {}

    address = address_obj.get("streetAddress", "").strip()
    city = address_obj.get("addressLocality", "").strip()
    country_raw = address_obj.get("addressCountry", "").strip()
    country = country_raw if country_raw else "Philippines"

    venue_url = (event.get("venueUrl") or "").strip()
    website = venue_url if _is_external_venue_url(venue_url) else ""

    loc_name = (location.get("name") or "").strip()
    name = loc_name if loc_name else venue_name

    return ScrapedVenue(
        name=name,
        address=address,
        city=city,
        country=country,
        website=website,
        source_url=venue_url or f"{_SITE}/events/{event.get('slug', '')}",
    )


def _build_event(event: dict) -> ScrapedEvent:
    slug = event.get("slug") or str(event.get("id", ""))
    price_raw = (event.get("price") or "").strip()
    currency = (event.get("priceCurrency") or "").strip()
    price = f"{price_raw} {currency}".strip() if currency and price_raw and price_raw.lower() not in ("free", "tba") else price_raw

    return ScrapedEvent(
        name=(event.get("title") or "").strip(),
        description=(event.get("description") or "").strip(),
        starts_at=_parse_date(event.get("startDate")),
        ends_at=_parse_date(event.get("endDate")),
        url=f"{_SITE}/events/{slug}",
        image_url=(event.get("imageUrl") or "").strip(),
        price=price,
        category=(event.get("category") or "").strip(),
        external_id=slug,
        source_url=_SOURCE_URL,
        organizer=(event.get("organizer") or "").strip(),
        venue=_build_venue(event),
    )


class ClickTheCityScraper(BaseScraper):
    source = "clickthecity"

    def fetch(self):
        try:
            resp = requests.get(
                _API,
                params={"limit": 1000},
                headers=_HEADERS,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("clickthecity: listing request failed: %s", exc)
            return

        payload = resp.json()
        events = payload.get("data") or []
        logger.info("clickthecity: %d events fetched", len(events))

        for event in events:
            try:
                yield _build_event(event)
            except Exception as exc:
                logger.warning(
                    "clickthecity: skipping event %r — %s",
                    event.get("slug") or event.get("id"),
                    exc,
                )

    def run(self, **_kwargs) -> dict:
        events = list(self.fetch())
        result = save_events(self.source, events)
        logger.info(
            "clickthecity: created=%d updated=%d",
            result["created"],
            result["updated"],
        )
        return result
