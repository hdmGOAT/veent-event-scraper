"""Scraper for planout.io events.

planout.io exposes a public JSON API (api-v2.planout.io). The events list
endpoint is paginated and carries all required fields inline (venue address,
organizer team, tags), so no per-event detail fetch is needed. No auth required.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from .proxy_manager import get_session
from .base import BaseScraper, ScrapedEvent, ScrapedOrganizer, ScrapedVenue, save_events, save_organizers

logger = logging.getLogger(__name__)

_API = "https://api-v2.planout.io"
_SITE = "https://planout.io"
_SOURCE_URL = f"{_SITE}/events"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EventScraper/1.0)", "Accept": "application/json"}
_TIMEOUT = 20


def _fetch_all_events() -> list[dict]:
    items: list[dict] = []
    page = 1
    while True:
        try:
            resp = get_session().get(
                f"{_API}/api/events",
                params={"limit": 50, "page": page},
                headers=_HEADERS,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            logger.error("planout: page %d fetch failed: %s", page, exc)
            break

        data = payload.get("data") or []
        items.extend(data)

        if not (payload.get("links") or {}).get("next"):
            break
        page += 1

    return items


def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _to_float(val) -> float | None:
    if val in (None, ""):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_venue(item: dict) -> ScrapedVenue | None:
    address = (item.get("address") or "").strip()
    if not address:
        return None
    segments = [s.strip() for s in address.split(",") if s.strip()]
    name = segments[0] if segments else address
    city = segments[-1] if len(segments) > 1 else ""
    return ScrapedVenue(
        name=name,
        address=address,
        city=city,
        latitude=_to_float(item.get("lat")),
        longitude=_to_float(item.get("long")),
        source_url=_SOURCE_URL,
    )


def _facebook_url(links) -> str:
    for link in links or []:
        if (link or {}).get("type") == "facebook":
            return link.get("url") or ""
    return ""


def _build_organizers(items: list[dict]) -> list[ScrapedOrganizer]:
    organizers: dict[str, ScrapedOrganizer] = {}
    for item in items:
        team = item.get("team") or {}
        team_id = team.get("id")
        if team_id is None:
            continue
        key = str(team_id)
        if key in organizers:
            continue
        organizers[key] = ScrapedOrganizer(
            name=team.get("name") or "",
            description=team.get("description") or "",
            email=team.get("email") or "",
            phone=team.get("mobile") or "",
            facebook_url=_facebook_url(team.get("links")),
            external_id=key,
            source_url=_SOURCE_URL,
        )
    return list(organizers.values())


def _category(item: dict) -> str:
    names = [
        (tag.get("name") or "")
        for tag in (item.get("tags") or [])
        if (tag or {}).get("type_label") == "category"
    ]
    names = [n for n in names if n]
    return ", ".join(names)[:120] if names else ""


def _build_event(item: dict) -> ScrapedEvent:
    team = item.get("team") or {}
    description = re.sub(r"<[^>]+>", "", item.get("description") or "").strip()
    return ScrapedEvent(
        name=item.get("name") or "",
        description=description,
        starts_at=_parse_dt(item.get("start")),
        ends_at=_parse_dt(item.get("end")),
        url=f"{_SITE}/event/{item.get('slug')}",
        image_url=(item.get("cover_photo") or {}).get("url") or "",
        price="",
        category=_category(item),
        external_id=str(item.get("id")),
        source_url=_SOURCE_URL,
        organizer=team.get("name") or "",
        organizer_url="",
        venue=_parse_venue(item),
    )


class PlanoutScraper(BaseScraper):
    source = "planout"

    def fetch(self):
        for item in _fetch_all_events():
            if item.get("name"):
                yield _build_event(item)

    def run(self, **_kwargs) -> dict:
        items = _fetch_all_events()
        events = [_build_event(i) for i in items if i.get("name")]
        organizers = _build_organizers(items)
        logger.info("planout: %d events, %d organizers", len(events), len(organizers))

        events_result = save_events(self.source, events)
        organizers_result = save_organizers(self.source, organizers)

        return {
            **events_result,
            "organizers_created": organizers_result["created"],
            "organizers_updated": organizers_result["updated"],
        }
