"""Scraper for ticket2me.net events.

ticket2me.net is a Nuxt.js SPA backed by an AWS API Gateway. The front-page
endpoint lists ~50 unique events across several sections; per-event detail and
show endpoints supply venue, organizer, and schedule data. No auth required.

All datetimes from the API are naive Philippine time (UTC+8).
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone

from .proxy_manager import get_session
from .base import BaseScraper, ScrapedEvent, ScrapedOrganizer, ScrapedVenue, save_events, save_organizers

logger = logging.getLogger(__name__)

_BASE_API = "https://2b67fmfmld.execute-api.ap-southeast-1.amazonaws.com/prod"
_ASSETS = "https://assets.ticket2me.net/public/"
_SITE = "https://www.ticket2me.net"
_SOURCE_URL = f"{_SITE}/events"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EventScraper/1.0)", "Accept": "application/json"}
_TIMEOUT = 20
_TZ = "Asia/Manila"


def _get(path: str, **params):
    try:
        resp = get_session().get(_BASE_API + path, params=params or None, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        time.sleep(0.3)
        return resp.json()
    except Exception as exc:
        logger.error("ticket2me request failed for %s: %s", path, exc)
        return None


def _image_url(path: str) -> str:
    return _ASSETS + path if path else ""


def _parse_naive_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        naive = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return timezone.make_aware(naive, ZoneInfo(_TZ))
    except (ValueError, TypeError):
        return None


def _price_str(val) -> str:
    if val is None or val == -1:
        return ""
    try:
        return f"₱{float(val):,.2f}"
    except (ValueError, TypeError):
        return ""


def _section_items(front_page: dict, key: str) -> list:
    """Return the ``attributes`` list for a front-page section.

    Each section is wrapped as ``{"attributes": [...], "meta": {...}}``.
    """
    section = front_page.get(key) or {}
    return section.get("attributes") or []


def _collect_event_ids(front_page: dict) -> dict[int, dict]:
    """Walk every front-page section and collect unique event ids.

    First occurrence wins for price/date fields.
    """
    collected: dict[int, dict] = {}

    def _add(eid, price=None, start_date=None, end_date=None):
        if eid is None:
            return
        eid = int(eid)
        if eid not in collected:
            collected[eid] = {"price": price, "start_date": start_date, "end_date": end_date}

    for item in _section_items(front_page, "coming_soon"):
        _add(item.get("event_id"), item.get("price"), item.get("start_date"), item.get("end_date"))

    for section in ("featured", "top"):
        for item in _section_items(front_page, section):
            _add(item.get("id"), item.get("price"))

    for row in _section_items(front_page, "custom_rows"):
        for item in row.get("items") or []:
            event = item.get("event") or {}
            _add(item.get("event_id") or event.get("id"), event.get("price"))

    return collected


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _build_event(event_id: int, attrs: dict, listing: dict) -> tuple[ScrapedEvent, dict | None]:
    ed = attrs.get("event_details") or {}
    org = attrs.get("organiser_details") or {}
    vd = ed.get("venue_details") or {}

    tags = ed.get("tags") or []
    category = ", ".join(tags)[:120] if tags else (ed.get("type") or "")

    organiser_url = org.get("organiser_url") or ""
    org_url = f"{_SITE}/{organiser_url}" if organiser_url else ""

    venue = None
    if vd.get("venue_name"):
        venue = ScrapedVenue(
            name=vd.get("venue_name") or "",
            address=vd.get("location_address") or "",
            city=vd.get("location_state") or "",
            country=vd.get("location_country") or "Philippines",
            latitude=vd.get("location_lat") or None,
            longitude=vd.get("location_long") or None,
            source_url=_SOURCE_URL,
        )

    starts_at = _parse_naive_dt(listing.get("start_date"))
    ends_at = _parse_naive_dt(listing.get("end_date"))

    event = ScrapedEvent(
        name=ed.get("title") or "",
        description=_strip_html(ed.get("description")),
        starts_at=starts_at,
        ends_at=ends_at,
        url=f"{_SITE}/event/{event_id}",
        image_url=_image_url(ed.get("bg_image_path") or ed.get("event_tile_image_path") or ""),
        price=_price_str(listing.get("price")),
        category=category,
        external_id=str(ed.get("id") or event_id),
        source_url=_SOURCE_URL,
        organizer=org.get("name") or "",
        organizer_url=org_url,
        venue=venue,
    )

    organizer = None
    if org.get("id") and org.get("name"):
        organizer = {
            "name": org.get("name") or "",
            "external_id": str(org.get("id")),
            "website": org_url,
            "email": org.get("email") or "",
            "phone": org.get("phone") or "",
            "description": org.get("about") or "",
            "facebook_url": org.get("facebook") or "",
            "source_url": _SOURCE_URL,
        }

    return event, organizer


def _first_show_dt(event_id: int) -> datetime | None:
    shows = _get(f"/event/{event_id}/get_shows")
    if not shows:
        return None
    attrs = (shows.get("data") or {}).get("attributes") or []
    for entry in attrs:
        for dt_str in entry.keys():
            parsed = _parse_naive_dt(dt_str)
            if parsed:
                return parsed
    return None


class Ticket2MeScraper(BaseScraper):
    source = "ticket2me"

    def _collect(self) -> tuple[list[ScrapedEvent], list[ScrapedOrganizer]]:
        front_page = _get("/events/front-page")
        if not front_page:
            logger.error("ticket2me: front-page fetch returned nothing")
            return [], []

        listings = _collect_event_ids(front_page.get("data") or {})
        logger.info("ticket2me: %d unique events on front page", len(listings))

        events: list[ScrapedEvent] = []
        organizers: dict[str, ScrapedOrganizer] = {}

        for event_id, listing in listings.items():
            detail = _get(f"/event/{event_id}")
            if not detail:
                continue
            attrs = (detail.get("data") or {}).get("attributes") or {}
            if not attrs:
                continue

            event, organizer = _build_event(event_id, attrs, listing)
            if not event.name:
                continue

            if event.starts_at is None:
                event.starts_at = _first_show_dt(event_id)

            events.append(event)

            if organizer and organizer["external_id"] not in organizers:
                organizers[organizer["external_id"]] = ScrapedOrganizer(**organizer)

        return events, list(organizers.values())

    def fetch(self):
        events, _ = self._collect()
        yield from events

    def run(self, **_kwargs) -> dict:
        events, organizers = self._collect()
        logger.info("ticket2me: %d events, %d organizers", len(events), len(organizers))

        organizers_result = save_organizers(self.source, organizers)
        events_result = save_events(self.source, events)

        return {
            **events_result,
            "organizers_created": organizers_result["created"],
            "organizers_updated": organizers_result["updated"],
        }
