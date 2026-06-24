"""Scraper for myruntime.com events.

Fetches all events from the MyRuntime JSON API in a single request.
No authentication required; the API is publicly accessible.

Organizers are derived from the regUrl subdomain (68 unique organizers across
843 events). Each organizer accumulates social/website links from all its events.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urlparse

import requests

from .base import BaseScraper, ScrapedEvent, ScrapedOrganizer, ScrapedVenue, save_events, save_organizers

logger = logging.getLogger(__name__)

_BASE_URL = "https://myruntime.com"
_API_URL = f"{_BASE_URL}/appEventsService/api/v1/getAppEvents"
_EVENTS_PAGE = f"{_BASE_URL}/events"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; EventScraper/1.0)"
}
_TIMEOUT = 20


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _extract_city(location: str) -> str:
    parts = [p.strip() for p in location.split(",")]
    return parts[-1] if len(parts) > 1 else ""


def _event_external_id(reg_url: str, name: str) -> str:
    """Derive a stable id from the registration URL.

    Most regUrls end with /register/{slug}. For those without a slug,
    fall back to subdomain + slugified name so the id stays unique.
    """
    parsed = urlparse(reg_url)
    m = re.search(r"/register/(.+)$", parsed.path.rstrip("/"))
    if m:
        return m.group(1)

    subdomain = (parsed.hostname or "").split(".")[0]
    if subdomain in ("myruntime", ""):
        subdomain = "direct"
    name_slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{subdomain}/{name_slug}"


def _organizer_subdomain(reg_url: str) -> str:
    """Return the subdomain from a regUrl, or 'direct' for myruntime.com-hosted ones."""
    hostname = urlparse(reg_url).hostname or ""
    subdomain = hostname.split(".")[0]
    return subdomain if subdomain not in ("myruntime", "") else "direct"


def _best_url(ext_links: dict) -> str:
    return (
        ext_links.get("website")
        or ext_links.get("facebook")
        or ext_links.get("instagram")
        or ext_links.get("twitter")
        or ""
    )


def _build_organizers(items: list[dict]) -> list[ScrapedOrganizer]:
    """Collect one ScrapedOrganizer per unique subdomain.

    Multiple events from the same organizer are merged: the first non-empty
    value wins for each link field.
    """
    seen: dict[str, ScrapedOrganizer] = {}

    for item in items:
        reg_url = item.get("regUrl") or ""
        if not reg_url:
            continue

        subdomain = _organizer_subdomain(reg_url)
        ext_links = item.get("externalLinks") or {}

        if subdomain not in seen:
            seen[subdomain] = ScrapedOrganizer(
                name=subdomain,
                external_id=subdomain,
                source_url=_EVENTS_PAGE,
                website=ext_links.get("website") or "",
                facebook_url=ext_links.get("facebook") or "",
                instagram_url=ext_links.get("instagram") or "",
            )
        else:
            org = seen[subdomain]
            if not org.website:
                org.website = ext_links.get("website") or ""
            if not org.facebook_url:
                org.facebook_url = ext_links.get("facebook") or ""
            if not org.instagram_url:
                org.instagram_url = ext_links.get("instagram") or ""

    return list(seen.values())


class MyRuntimeScraper(BaseScraper):
    source = "myruntime"

    def _fetch_data(self) -> list[dict]:
        try:
            resp = requests.get(
                _API_URL,
                params={"limit": 2000},
                headers=_HEADERS,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception as exc:
            logger.error("MyRuntime API request failed: %s", exc)
            return []

    def fetch(self):
        data = self._fetch_data()
        logger.info("MyRuntime: received %d events", len(data))

        for item in data:
            name = (item.get("name") or "").strip()
            if not name:
                continue

            reg_url = item.get("regUrl") or ""
            locations = item.get("location") or []
            location_str = locations[0] if locations else ""
            tickets = item.get("tickets") or []
            ext_links = item.get("externalLinks") or {}

            venue = None
            if location_str:
                venue = ScrapedVenue(
                    name=location_str,
                    city=_extract_city(location_str),
                    country="Philippines",
                    source_url=_EVENTS_PAGE,
                )

            ticket_names = [t["name"] for t in tickets if t.get("name")]
            organizer_name = _organizer_subdomain(reg_url) if reg_url else ""

            yield ScrapedEvent(
                name=name,
                starts_at=_parse_dt(item.get("eventDate")),
                ends_at=_parse_dt(item.get("eventDateEnd")),
                url=reg_url,
                image_url=item.get("bannerImage") or item.get("thumbnail") or "",
                category=", ".join(ticket_names)[:120],
                external_id=_event_external_id(reg_url, name) if reg_url else "",
                source_url=_EVENTS_PAGE,
                organizer=organizer_name,
                organizer_url=_best_url(ext_links),
                venue=venue,
            )

    def run(self, **_kwargs) -> dict:
        data = self._fetch_data()
        logger.info("MyRuntime: received %d events", len(data))

        events = []
        for item in data:
            name = (item.get("name") or "").strip()
            if not name:
                continue

            reg_url = item.get("regUrl") or ""
            locations = item.get("location") or []
            location_str = locations[0] if locations else ""
            tickets = item.get("tickets") or []
            ext_links = item.get("externalLinks") or {}

            venue = None
            if location_str:
                venue = ScrapedVenue(
                    name=location_str,
                    city=_extract_city(location_str),
                    country="Philippines",
                    source_url=_EVENTS_PAGE,
                )

            ticket_names = [t["name"] for t in tickets if t.get("name")]
            organizer_name = _organizer_subdomain(reg_url) if reg_url else ""

            events.append(ScrapedEvent(
                name=name,
                starts_at=_parse_dt(item.get("eventDate")),
                ends_at=_parse_dt(item.get("eventDateEnd")),
                url=reg_url,
                image_url=item.get("bannerImage") or item.get("thumbnail") or "",
                category=", ".join(ticket_names)[:120],
                external_id=_event_external_id(reg_url, name) if reg_url else "",
                source_url=_EVENTS_PAGE,
                organizer=organizer_name,
                organizer_url=_best_url(ext_links),
                venue=venue,
            ))

        organizers = _build_organizers(data)
        logger.info("MyRuntime: found %d unique organizers", len(organizers))

        events_result = save_events(self.source, events)
        organizers_result = save_organizers(self.source, organizers)

        return {
            **events_result,
            "organizers_created": organizers_result["created"],
            "organizers_updated": organizers_result["updated"],
        }
