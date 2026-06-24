"""AllEvents.in scraper using the official Azure APIM REST API.

Requires an API subscription key from https://allevents.developer.azure-api.net
(Starter plan is free: 1,000 calls/week, 10 calls/min).

Add ALLEVENTS_API_KEY=<your-key> to your .env file, then run:
    python manage.py scrape allevents_in
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Iterable

import requests
from django.conf import settings

from .base import (
    BaseScraper,
    ScrapedEvent,
    ScrapedOrganizer,
    ScrapedVenue,
    save_events,
    save_organizers,
)

logger = logging.getLogger(__name__)

_API_URL = "http://api.allevents.in/events/list/"
_TIMEOUT = 20
_PAGE_SIZE = 50
_MAX_PAGES = 20
_PHT = dt_timezone(timedelta(hours=8))

_PH_CITIES = [
    {"city": "Manila", "state": "National Capital Region", "country": "PH"},
    {"city": "Cebu", "state": "Central Visayas", "country": "PH"},
    {"city": "Davao City", "state": "Davao Region", "country": "PH"},
    {"city": "Cagayan de Oro", "state": "Northern Mindanao", "country": "PH"},
]

_CITY_MAP = {
    "Manila": "Manila",
    "Cebu": "Cebu",
    "Davao City": "Davao City",
    "Cagayan de Oro": "Cagayan de Oro",
}


def _headers(api_key: str) -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (compatible; EventScraper/1.0)",
        "Accept": "application/json",
        "Ocp-Apim-Subscription-Key": api_key,
    }


def _parse_dt(raw) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=dt_timezone.utc)
    s = str(raw).strip()
    if not s:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_PHT).astimezone(dt_timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _get_str(item: dict, *keys: str, max_len: int = 0) -> str:
    for k in keys:
        v = item.get(k)
        if v and isinstance(v, str):
            return v[:max_len] if max_len else v
    return ""


def _build_venue(item: dict, city_name: str) -> ScrapedVenue | None:
    venue_data = item.get("venue") or {}
    if isinstance(venue_data, str):
        name, address = venue_data, ""
    else:
        name = _get_str(venue_data, "name") or _get_str(item, "venue_name", "location_name", "location")
        address = _get_str(venue_data, "address") or _get_str(item, "venue_address", "address")
    if not name:
        return None
    try:
        lat = float(item.get("lat") or item.get("latitude") or 0) or None
        lon = float(item.get("long") or item.get("lng") or item.get("longitude") or 0) or None
    except (TypeError, ValueError):
        lat = lon = None
    return ScrapedVenue(
        name=name,
        address=address,
        city=city_name,
        country="Philippines",
        latitude=lat,
        longitude=lon,
    )


def _build_organizer(item: dict) -> ScrapedOrganizer | None:
    name = _get_str(item, "organizer_name", "organizer", "host_name")
    org_id = str(item.get("organizer_id") or item.get("host_id") or "").strip()
    if not name:
        return None
    return ScrapedOrganizer(
        name=name,
        external_id=org_id,
        source_url=_get_str(item, "organizer_url", "host_url"),
        website=_get_str(item, "organizer_website"),
        description=_get_str(item, "organizer_desc", max_len=500),
    )


def _item_to_scraped_event(item: dict, city_name: str) -> ScrapedEvent | None:
    name = _get_str(item, "name", "title", "event_name", "eventname")
    if not name:
        return None
    event_url = _get_str(item, "url", "event_url", "link")
    external_id = str(
        item.get("id") or item.get("event_id") or item.get("eid") or item.get("eventid") or ""
    ).strip()
    return ScrapedEvent(
        name=name,
        description=_get_str(item, "description", "desc"),
        starts_at=_parse_dt(
            item.get("start_time") or item.get("start_date") or item.get("startDate") or item.get("start")
        ),
        ends_at=_parse_dt(
            item.get("end_time") or item.get("end_date") or item.get("endDate") or item.get("end")
        ),
        url=event_url,
        image_url=_get_str(item, "banner", "image", "thumbnail", "pic", "image_url"),
        price=str(item.get("ticket_price") or item.get("price") or item.get("cost") or ""),
        category=_get_str(item, "category", "type", "cat"),
        external_id=external_id,
        source_url=_API_URL,
        organizer=_get_str(item, "organizer_name", "organizer", "host_name", max_len=255),
        organizer_url=_get_str(item, "organizer_url", "host_url"),
        venue=_build_venue(item, city_name),
    )


def _fetch_page(api_key: str, city_cfg: dict, page: int) -> list[dict]:
    params = {**city_cfg, "page": page}
    try:
        resp = requests.post(
            _API_URL,
            headers=_headers(api_key),
            params=params,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.error("AllEvents API error city=%s page=%d: %s", city_cfg["city"], page, exc)
        return []
    items = (
        data.get("data")
        or data.get("events")
        or data.get("items")
        or data.get("results")
        or (data if isinstance(data, list) else [])
    )
    return items if isinstance(items, list) else []


class AllEventsAPIScraper(BaseScraper):
    source = "allevents_in"

    def _get_api_key(self) -> str:
        key = getattr(settings, "ALLEVENTS_API_KEY", "")
        if not key:
            raise ValueError(
                "ALLEVENTS_API_KEY is not set. "
                "Sign up at https://allevents.developer.azure-api.net (Starter plan is free), "
                "then add ALLEVENTS_API_KEY=<your-key> to your .env file."
            )
        return key

    def _collect_all(self, api_key: str) -> list[dict]:
        seen: set[str] = set()
        all_items: list[dict] = []
        for city_cfg in _PH_CITIES:
            city_name = city_cfg["city"]
            for page in range(1, _MAX_PAGES + 1):
                items = _fetch_page(api_key, city_cfg, page)
                if not items:
                    break
                new_items = []
                for item in items:
                    eid = str(item.get("id") or item.get("event_id") or item.get("eid") or "")
                    key_str = f"{city_name}:{eid}" if eid else f"{city_name}:{item.get('name','')}"
                    if key_str not in seen:
                        seen.add(key_str)
                        item["_city_name"] = city_name
                        new_items.append(item)
                all_items.extend(new_items)
                if len(items) < _PAGE_SIZE:
                    break
        logger.info("AllEvents API: collected %d events across %d cities", len(all_items), len(_PH_CITIES))
        return all_items

    def fetch(self) -> Iterable[ScrapedEvent]:
        api_key = self._get_api_key()
        for item in self._collect_all(api_key):
            ev = _item_to_scraped_event(item, item.get("_city_name", "Philippines"))
            if ev:
                yield ev

    def run(self, **_kwargs) -> dict:
        api_key = self._get_api_key()
        raw = self._collect_all(api_key)

        events = [
            e for item in raw
            if (e := _item_to_scraped_event(item, item.get("_city_name", "Philippines")))
        ]

        seen_orgs: set[str] = set()
        organizers: list[ScrapedOrganizer] = []
        for item in raw:
            org = _build_organizer(item)
            if not org:
                continue
            key = org.external_id or org.name
            if key and key not in seen_orgs:
                seen_orgs.add(key)
                organizers.append(org)

        logger.info("AllEvents API: %d events, %d organizers", len(events), len(organizers))
        organizers_result = save_organizers(self.source, organizers)
        events_result = save_events(self.source, events)
        return {
            **events_result,
            "organizers_created": organizers_result["created"],
            "organizers_updated": organizers_result["updated"],
        }
