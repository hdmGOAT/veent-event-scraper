"""Scraper for SISTIC Singapore events.

Two-step process:
  1. GET paginated listing from the Drupal CMS REST API (no auth, no JS needed).
  2. GET event detail for each alias to collect full fields.

The CMS API (cms.sistic.com.sg) is the same backend the Next.js frontend
calls — plain requests work without any Cloudflare or JS challenge.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from .base import (
    BaseScraper,
    ScrapedEvent,
    ScrapedOrganizer,
    ScrapedVenue,
    save_events,
    save_organizers,
)

logger = logging.getLogger(__name__)

_CMS = "https://cms.sistic.com.sg/sistic/docroot"
_API = f"{_CMS}/api"
_SITE = "https://www.sistic.com.sg"
_SOURCE_URL = f"{_SITE}/events"
_TZ = ZoneInfo("Asia/Singapore")
_PER_PAGE = 30  # API silently returns empty data for limit > 30
_TIMEOUT = 30
_DELAY = 0.3

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, */*",
    "Referer": _SITE,
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(url: str, **params) -> dict | list | None:
    try:
        resp = requests.get(url, headers=_HEADERS, params=params or None, timeout=_TIMEOUT)
        resp.raise_for_status()
        time.sleep(_DELAY)
        return resp.json()
    except Exception as exc:
        logger.error("sistic: GET failed for %s: %s", url, exc)
        return None


def _fetch_all_listings() -> list[dict]:
    all_items: list[dict] = []
    first = 0
    total: int | None = None
    while True:
        data = _get(
            f"{_API}/events",
            client=1,
            first=first,
            limit=_PER_PAGE,
            sort_type="date",
            sort_order="ASC",
            index="global",
        )
        if not data or not isinstance(data, dict):
            break
        if total is None:
            total = int(data.get("total_records") or 0)
        batch = data.get("data") or []
        if not batch:
            break
        all_items.extend(batch)
        logger.info("sistic: %d / %d listings fetched", len(all_items), total or "?")
        if total and len(all_items) >= total:
            break
        first += _PER_PAGE
    return all_items


def _fetch_detail(alias: str) -> dict | None:
    data = _get(f"{_API}/event-detail", client=1, code=alias)
    if isinstance(data, dict):
        return data
    return None


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _parse_date(date_str: str) -> datetime | None:
    """Parse 'Wed, 30 Nov 2022' → SGT-aware datetime at midnight."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.strip(), "%a, %d %b %Y").replace(tzinfo=_TZ)
    except ValueError:
        logger.warning("sistic: unparseable date %r", date_str)
        return None


def _image_url(path: str) -> str:
    if not path:
        return ""
    return path if path.startswith("http") else f"{_CMS}{path}"


def _build_venue(venue_data: dict) -> ScrapedVenue | None:
    name = (venue_data.get("name") or "").strip()
    if not name:
        return None
    def _float(val) -> float | None:
        try:
            return float(val) if val else None
        except (ValueError, TypeError):
            return None
    return ScrapedVenue(
        name=name,
        city="Singapore",
        country="SG",
        latitude=_float(venue_data.get("latitude")),
        longitude=_float(venue_data.get("longitude")),
        source_url=_SOURCE_URL,
    )


def _build_event(listing: dict, detail: dict) -> ScrapedEvent:
    alias = (listing.get("alias") or "").strip()
    images = detail.get("images") or []
    raw_image = images[0].get("full_image", "") if images else ""
    promoters = detail.get("promoters") or []
    org_name = (promoters[0].get("name") or "").strip() if promoters else ""
    venue_data = detail.get("venue_name")
    venue = _build_venue(venue_data) if isinstance(venue_data, dict) else None
    return ScrapedEvent(
        name=_strip_html(detail.get("title") or listing.get("title") or ""),
        description=_strip_html(detail.get("description") or ""),
        starts_at=_parse_date(detail.get("start_date") or listing.get("start_date")),
        ends_at=_parse_date(detail.get("end_date") or listing.get("end_date")),
        url=f"{_SITE}/events/{alias}" if alias else "",
        image_url=_image_url(raw_image),
        price=detail.get("price") or "",
        category=detail.get("primary_genre") or "",
        external_id=str(detail.get("id") or listing.get("id") or ""),
        source_url=_SOURCE_URL,
        organizer=org_name,
        organizer_url="",
        venue=venue,
    )


def _build_organizer(detail: dict) -> ScrapedOrganizer | None:
    promoters = detail.get("promoters") or []
    if not promoters:
        return None
    p = promoters[0]
    name = (p.get("name") or "").strip()
    if not name:
        return None
    return ScrapedOrganizer(
        name=name,
        website=p.get("url") or "",
        email=p.get("email") or "",
        external_id=str(p.get("id") or ""),
        source_url=_SOURCE_URL,
    )


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class SisticScraper(BaseScraper):
    """Scraper for SISTIC Singapore events via the Drupal CMS REST API."""

    source = "sistic"

    def _collect(self) -> tuple[list[ScrapedEvent], list[ScrapedOrganizer]]:
        listings = _fetch_all_listings()
        logger.info("sistic: %d listings to process", len(listings))

        events: list[ScrapedEvent] = []
        organizers: dict[str, ScrapedOrganizer] = {}

        for i, listing in enumerate(listings, 1):
            alias = (listing.get("alias") or "").strip()
            if not alias:
                continue
            detail = _fetch_detail(alias)
            if not detail:
                continue
            logger.debug("sistic: %d/%d — %s", i, len(listings), alias)

            event = _build_event(listing, detail)
            if event.name:
                events.append(event)

            org = _build_organizer(detail)
            if org and org.name and org.name not in organizers:
                organizers[org.name] = org

        logger.info("sistic: %d events, %d organizers collected", len(events), len(organizers))
        return events, list(organizers.values())

    def fetch(self):
        events, _ = self._collect()
        yield from events

    def run(self) -> dict:
        events, organizers = self._collect()
        events_result = save_events(self.source, events)
        organizers_result = save_organizers(self.source, organizers)
        return {
            **events_result,
            "organizers_created": organizers_result["created"],
            "organizers_updated": organizers_result["updated"],
        }
