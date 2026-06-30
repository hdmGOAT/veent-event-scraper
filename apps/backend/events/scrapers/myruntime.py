"""Scraper for myruntime.com events.

Fetches all events from the MyRuntime JSON API in a single request.
No authentication required; the API is publicly accessible.

Organizers are derived from the regUrl subdomain for subdomain-hosted events
(e.g. tribeevents.myruntime.com → "tribeevents"). For events hosted directly
on myruntime.com (no subdomain), the Facebook page handle from externalLinks
is used as the organizer key instead — 89% of direct events carry one. Events
with no usable link are left unattributed rather than collapsed into a synthetic
"direct" bucket.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urlparse

from .proxy_manager import get_session
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
    """Return the subdomain from a regUrl, or '' for myruntime.com-hosted ones."""
    hostname = urlparse(reg_url).hostname or ""
    subdomain = hostname.split(".")[0]
    return subdomain if subdomain not in ("myruntime", "") else ""


_FB_NON_PAGE_SEGMENTS = frozenset(
    ["events", "groups", "pages", "people", "profile.php", "watch", "marketplace"]
)


def _fb_handle(fb_url: str) -> str:
    """Extract the page handle/slug from a Facebook URL path.

    Returns '' for generic non-page path segments (events, groups, people, etc.).
    """
    parts = [p for p in urlparse(fb_url).path.split("/") if p]
    if not parts:
        return ""
    handle = parts[0]
    return "" if handle in _FB_NON_PAGE_SEGMENTS else handle


def _direct_org_key(ext_links: dict) -> tuple[str, str, str, str] | None:
    """For direct-hosted events, derive (key, fb_url, website, ig_url).

    Priority: Facebook handle → website domain → Instagram handle.
    Returns None when no usable link exists (event stays unattributed).
    """
    fb = (ext_links.get("facebook") or "").strip().rstrip("/")
    website = (ext_links.get("website") or "").strip().rstrip("/")
    ig = (ext_links.get("instagram") or "").strip().rstrip("/")

    if fb:
        handle = _fb_handle(fb)
        if handle:
            return handle, fb, website, ig
    if website:
        hostname = urlparse(website).hostname or website
        key = hostname.removeprefix("www.")
        return key, fb, website, ig
    if ig:
        parts = [p for p in urlparse(ig).path.split("/") if p]
        key = parts[0] if parts else ""
        if key:
            return key, fb, website, ig
    return None


def _organizer_key(reg_url: str, ext_links: dict) -> str:
    """Return the organizer identifier for an event.

    Subdomain-hosted events use the subdomain; direct-hosted events use the
    Facebook handle (or website domain, or IG handle). Returns '' when no
    identity can be derived so the event is stored unattributed.
    """
    subdomain = _organizer_subdomain(reg_url)
    if subdomain:
        return subdomain
    result = _direct_org_key(ext_links)
    return result[0] if result else ""


def _best_url(ext_links: dict) -> str:
    return (
        ext_links.get("website")
        or ext_links.get("facebook")
        or ext_links.get("instagram")
        or ext_links.get("twitter")
        or ""
    )


def _build_organizers(items: list[dict]) -> list[ScrapedOrganizer]:
    """Collect one ScrapedOrganizer per unique organizer key.

    Subdomain-hosted events group by subdomain. Direct-hosted events group by
    Facebook handle (or website domain / IG handle). Events with no usable
    identity are skipped — they are stored unattributed on their Event row.
    Multiple events from the same organizer are merged: the first non-empty
    value wins for each link field.
    """
    seen: dict[str, ScrapedOrganizer] = {}

    for item in items:
        reg_url = item.get("regUrl") or ""
        if not reg_url:
            continue

        ext_links = item.get("externalLinks") or {}
        subdomain = _organizer_subdomain(reg_url)

        if subdomain:
            key = subdomain
            if key not in seen:
                seen[key] = ScrapedOrganizer(
                    name=key,
                    external_id=key,
                    source_url=_EVENTS_PAGE,
                    website=ext_links.get("website") or "",
                    facebook_url=ext_links.get("facebook") or "",
                    instagram_url=ext_links.get("instagram") or "",
                )
            else:
                org = seen[key]
                if not org.website:
                    org.website = ext_links.get("website") or ""
                if not org.facebook_url:
                    org.facebook_url = ext_links.get("facebook") or ""
                if not org.instagram_url:
                    org.instagram_url = ext_links.get("instagram") or ""
        else:
            result = _direct_org_key(ext_links)
            if result is None:
                continue
            key, fb_url, website, ig_url = result
            if key not in seen:
                seen[key] = ScrapedOrganizer(
                    name=key,
                    external_id=key,
                    source_url=_EVENTS_PAGE,
                    facebook_url=fb_url,
                    website=website,
                    instagram_url=ig_url,
                )
            else:
                org = seen[key]
                if not org.facebook_url and fb_url:
                    org.facebook_url = fb_url
                if not org.website and website:
                    org.website = website
                if not org.instagram_url and ig_url:
                    org.instagram_url = ig_url

    return list(seen.values())


class MyRuntimeScraper(BaseScraper):
    source = "myruntime"

    def _fetch_data(self) -> list[dict]:
        try:
            resp = get_session().get(
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
            organizer_name = _organizer_key(reg_url, ext_links) if reg_url else ""

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
            organizer_name = _organizer_key(reg_url, ext_links) if reg_url else ""

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
