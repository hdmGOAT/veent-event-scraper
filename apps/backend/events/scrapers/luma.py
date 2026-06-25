"""Scraper for lu.ma (Luma) events.

Uses the unauthenticated geo-discovery endpoint:
  GET https://api.lu.ma/discover/get-paginated-events
  params: latitude, longitude, radius_km[, pagination_cursor]

Covers three Philippine metro areas; deduplicates by api_id across regions.
The calendar object on each entry is used as the organizer.
"""
from __future__ import annotations

import logging
from datetime import datetime

from .proxy_manager import get_session
from .base import (
    BaseScraper,
    ScrapedEvent,
    ScrapedOrganizer,
    ScrapedVenue,
    save_events,
    save_organizers,
)

logger = logging.getLogger(__name__)

_API_URL = "https://api.lu.ma/discover/get-paginated-events"
_LUMA_BASE = "https://lu.ma"
_SOURCE_URL = "https://lu.ma/discover"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EventScraper/1.0)"}
_TIMEOUT = 15

# (lat, lon, radius_km) — three major PH metro areas
_PH_LOCATIONS = [
    (14.5958, 120.9772, 100),  # Metro Manila
    (10.3157, 123.8854, 100),  # Metro Cebu
    (7.1907, 125.4553, 100),   # Davao
]


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _price_str(ticket_info: dict) -> str:
    if not ticket_info:
        return ""
    if ticket_info.get("is_free"):
        return "Free"
    price = ticket_info.get("price") or {}
    cents = price.get("cents")
    if cents is None:
        return ""
    amount = cents / 100
    max_p = ticket_info.get("max_price") or {}
    max_cents = max_p.get("cents")
    if max_cents and max_cents != cents:
        return f"₱{amount:,.0f}-₱{max_cents / 100:,.0f}"
    return f"₱{amount:,.0f}"


def _build_venue(ev: dict) -> ScrapedVenue | None:
    geo = ev.get("geo_address_info") or {}
    coord = ev.get("coordinate") or {}
    name = geo.get("address") or geo.get("full_address", "")
    if not name:
        return None
    return ScrapedVenue(
        name=name,
        address=geo.get("full_address", ""),
        city=geo.get("city", ""),
        country=geo.get("country", "Philippines"),
        latitude=coord.get("latitude"),
        longitude=coord.get("longitude"),
        source_url=_SOURCE_URL,
    )


def _build_organizers(items: list[dict]) -> list[ScrapedOrganizer]:
    seen: dict[str, ScrapedOrganizer] = {}
    for entry in items:
        cal = entry.get("calendar") or {}
        cal_id = cal.get("api_id", "")
        if not cal_id or cal_id in seen:
            continue
        name = (cal.get("name") or "").strip()
        if not name:
            continue
        ig = cal.get("instagram_handle") or ""
        seen[cal_id] = ScrapedOrganizer(
            name=name,
            external_id=cal_id,
            source_url=_SOURCE_URL,
            website=cal.get("website") or "",
            instagram_url=f"https://www.instagram.com/{ig}" if ig else "",
            description=(cal.get("description_short") or "")[:500],
        )
    return list(seen.values())


class LumaScraper(BaseScraper):
    source = "luma"

    def _fetch_location(self, lat: float, lon: float, radius: float) -> list[dict]:
        entries: list[dict] = []
        cursor: str | None = None
        while True:
            params: dict = {"latitude": lat, "longitude": lon, "radius_km": radius}
            if cursor:
                params["pagination_cursor"] = cursor
            try:
                resp = get_session().get(_API_URL, headers=_HEADERS, params=params, timeout=_TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.error("Luma: request failed lat=%s lon=%s: %s", lat, lon, exc)
                break
            entries.extend(data.get("entries", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor") or None
            if not cursor:
                break
        return entries

    def _collect_all(self) -> list[dict]:
        seen: set[str] = set()
        all_items: list[dict] = []
        for lat, lon, radius in _PH_LOCATIONS:
            for entry in self._fetch_location(lat, lon, radius):
                api_id = entry.get("api_id", "")
                if api_id and api_id not in seen:
                    seen.add(api_id)
                    all_items.append(entry)
        logger.info("Luma: collected %d unique events", len(all_items))
        return all_items

    def _entry_to_event(self, entry: dict) -> ScrapedEvent | None:
        ev = entry.get("event") or {}
        name = (ev.get("name") or "").strip()
        if not name:
            return None
        url_slug = (ev.get("url") or "").strip()
        cal = entry.get("calendar") or {}
        hosts = entry.get("hosts") or []
        organizer_name = (cal.get("name") or (hosts[0]["name"] if hosts else "")).strip()
        return ScrapedEvent(
            name=name,
            starts_at=_parse_dt(ev.get("start_at")),
            ends_at=_parse_dt(ev.get("end_at")),
            url=f"{_LUMA_BASE}/{url_slug}" if url_slug else "",
            image_url=ev.get("cover_url") or "",
            price=_price_str(entry.get("ticket_info") or {}),
            category="",
            external_id=entry.get("api_id", ""),
            source_url=_SOURCE_URL,
            organizer=organizer_name[:255],
            organizer_url=cal.get("website") or "",
            venue=_build_venue(ev),
        )

    def run(self, **_kwargs) -> dict:
        items = self._collect_all()
        events = [e for entry in items if (e := self._entry_to_event(entry))]
        organizers = _build_organizers(items)
        logger.info("Luma: %d events, %d organizers", len(events), len(organizers))
        events_result = save_events(self.source, events)
        organizers_result = save_organizers(self.source, organizers)
        return {
            **events_result,
            "organizers_created": organizers_result["created"],
            "organizers_updated": organizers_result["updated"],
        }

    def fetch(self):
        for entry in self._collect_all():
            event = self._entry_to_event(entry)
            if event:
                yield event
