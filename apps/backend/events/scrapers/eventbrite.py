"""Scraper for Eventbrite events (Philippines).

Two-step approach — no Playwright needed:
  1. GET listing pages via requests to collect event IDs (server-rendered
     data-event-id attributes in the HTML).
  2. Batch-call the internal /api/v3/destination/events/ endpoint for full
     event, venue, organizer, and pricing data.

Covers three PH metro areas; deduplicates by numeric event ID.
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

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

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EventScraper/1.0)"}
_TIMEOUT = 25
_LISTING_URL = "https://www.eventbrite.com/d/{location}/all-events/"
_API_URL = "https://www.eventbrite.com/api/v3/destination/events/"
_API_EXPAND = (
    "event_sales_status,image,primary_venue,ticket_availability,primary_organizer"
)
_SOURCE_URL = "https://www.eventbrite.com/d/philippines/all-events/"
_MAX_PAGES = 10  # safety cap per location

_PH_LOCATIONS = [
    "philippines--manila",
    "philippines--cebu",
    "philippines--davao-city",
]


def _parse_dt(date_str: str, time_str: str, tz_str: str) -> datetime | None:
    if not date_str:
        return None
    try:
        tz = ZoneInfo(tz_str or "Asia/Manila")
        return datetime.strptime(
            f"{date_str} {time_str or '00:00'}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=tz)
    except Exception:
        return None


def _price_str(ta: dict) -> str:
    if not ta:
        return ""
    if ta.get("is_free"):
        return "Free"
    min_p = ta.get("minimum_ticket_price") or {}
    max_p = ta.get("maximum_ticket_price") or {}
    min_val = min_p.get("major_value")
    if min_val is None:
        return ""
    min_amt = float(min_val)
    max_val = max_p.get("major_value")
    if max_val and float(max_val) != min_amt:
        return f"₱{min_amt:,.0f}-₱{float(max_val):,.0f}"
    return f"₱{min_amt:,.0f}"


def _category(tags: list) -> str:
    for tag in tags or []:
        if tag.get("prefix") == "EventbriteCategory":
            return tag.get("display_name", "")
    return ""


def _facebook_url(fb: str | None) -> str:
    if not fb:
        return ""
    if fb.startswith("http"):
        return fb
    if fb.isdigit():
        return f"https://www.facebook.com/profile.php?id={fb}"
    return f"https://www.facebook.com/{fb}"


def _build_venue(ev: dict) -> ScrapedVenue | None:
    if ev.get("is_online_event"):
        return None
    venue = ev.get("primary_venue") or {}
    name = (venue.get("name") or "").strip()
    if not name:
        return None
    addr = venue.get("address") or {}
    city = addr.get("city") or addr.get("region") or ""
    country_code = addr.get("country") or "PH"
    country = "Philippines" if country_code == "PH" else country_code
    try:
        lat = float(addr.get("latitude") or 0) or None
        lon = float(addr.get("longitude") or 0) or None
    except (TypeError, ValueError):
        lat = lon = None
    return ScrapedVenue(
        name=name,
        address=addr.get("address_1") or "",
        city=city,
        country=country,
        latitude=lat,
        longitude=lon,
        source_url=ev.get("url") or "",
    )


def _build_organizer(org: dict) -> ScrapedOrganizer | None:
    name = (org.get("name") or "").strip()
    org_id = str(org.get("id") or "").strip()
    if not name or not org_id:
        return None
    return ScrapedOrganizer(
        name=name,
        external_id=org_id,
        source_url=org.get("url") or "",
        website=org.get("website_url") or "",
        facebook_url=_facebook_url(org.get("facebook")),
        description=(org.get("summary") or "")[:500],
    )


class EventbriteScraper(BaseScraper):
    source = "eventbrite"

    def _get_page_ids(self, location: str, page: int) -> list[str]:
        url = _LISTING_URL.format(location=location)
        if page > 1:
            url += f"?page={page}"
        try:
            resp = get_session().get(url, headers=_HEADERS, timeout=_TIMEOUT)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Eventbrite: listing failed %s p%d: %s", location, page, exc)
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        seen: set[str] = set()
        ids: list[str] = []
        for a in soup.find_all("a", attrs={"data-event-id": True}):
            eid = (a.get("data-event-id") or "").strip()
            if eid and eid not in seen:
                seen.add(eid)
                ids.append(eid)
        return ids

    def _fetch_details(self, event_ids: list[str]) -> list[dict]:
        if not event_ids:
            return []
        try:
            resp = get_session().get(
                _API_URL,
                headers=_HEADERS,
                params={
                    "event_ids": ",".join(event_ids),
                    "page_size": len(event_ids),
                    "expand": _API_EXPAND,
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json().get("events", [])
        except Exception as exc:
            logger.error("Eventbrite: API failed for %d events: %s", len(event_ids), exc)
            return []

    def _collect_all(self) -> list[dict]:
        seen: set[str] = set()
        all_events: list[dict] = []
        for location in _PH_LOCATIONS:
            for page in range(1, _MAX_PAGES + 1):
                ids = self._get_page_ids(location, page)
                if not ids:
                    break
                new_ids = [i for i in ids if i not in seen]
                seen.update(ids)
                if new_ids:
                    batch = self._fetch_details(new_ids)
                    all_events.extend(batch)
        logger.info("Eventbrite: collected %d unique events", len(all_events))
        return all_events

    def _to_scraped_event(self, ev: dict) -> ScrapedEvent | None:
        name = (ev.get("name") or "").strip()
        if not name:
            return None
        tz = ev.get("timezone") or "Asia/Manila"
        org = ev.get("primary_organizer") or {}
        img = ev.get("image") or {}
        return ScrapedEvent(
            name=name,
            starts_at=_parse_dt(ev.get("start_date"), ev.get("start_time"), tz),
            ends_at=_parse_dt(ev.get("end_date"), ev.get("end_time"), tz),
            url=ev.get("url") or "",
            image_url=img.get("url") or "",
            price=_price_str(ev.get("ticket_availability") or {}),
            category=_category(ev.get("tags") or []),
            external_id=str(ev.get("id") or ""),
            source_url=_SOURCE_URL,
            organizer=(org.get("name") or "")[:255],
            organizer_url=org.get("url") or "",
            venue=_build_venue(ev),
        )

    def run(self, **_kwargs) -> dict:
        raw = self._collect_all()
        events = [e for ev in raw if (e := self._to_scraped_event(ev))]
        seen_orgs: set[str] = set()
        organizers: list[ScrapedOrganizer] = []
        for ev in raw:
            org_data = ev.get("primary_organizer") or {}
            org_id = str(org_data.get("id") or "")
            if org_id and org_id not in seen_orgs:
                seen_orgs.add(org_id)
                org = _build_organizer(org_data)
                if org:
                    organizers.append(org)
        logger.info("Eventbrite: %d events, %d organizers", len(events), len(organizers))
        organizers_result = save_organizers(self.source, organizers)
        events_result = save_events(self.source, events)
        return {
            **events_result,
            "organizers_created": organizers_result["created"],
            "organizers_updated": organizers_result["updated"],
        }

    def fetch(self):
        for ev in self._collect_all():
            scraped = self._to_scraped_event(ev)
            if scraped:
                yield scraped
