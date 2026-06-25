"""Meetup.com Philippines scraper.

Headless Playwright + network interception strategy:
  1. Navigate to Meetup's discover page for Philippines and key cities.
  2. Intercept all POST /gql2 (internal GraphQL) JSON responses.
  3. Also extract ``__NEXT_DATA__`` embedded JSON from page HTML.
  4. Scroll to trigger lazy-loading / infinite scroll pagination.
  5. Parse events and Meetup groups; save both events and organizers.

No browser window appears — all execution is headless.

Run:
    python manage.py scrape meetup
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone as dt_timezone
from typing import Iterable

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from .proxy_manager import get_proxy_enabled, get_proxy_session
from .base import (
    BaseScraper,
    ScrapedEvent,
    ScrapedOrganizer,
    ScrapedVenue,
    save_events,
    save_organizers,
)

logger = logging.getLogger(__name__)

_MEETUP_BASE = "https://www.meetup.com"
_SOURCE_URL = "https://www.meetup.com/find/philippines/"

# Discover pages to scrape — broad Philippines + key metro areas
_SEARCH_URLS = [
    "https://www.meetup.com/find/philippines/",
    "https://www.meetup.com/find/?location=Manila%2C+Philippines&source=EVENTS&sortField=DATETIME",
    "https://www.meetup.com/find/?location=Cebu+City%2C+Philippines&source=EVENTS&sortField=DATETIME",
    "https://www.meetup.com/find/?location=Davao+City%2C+Philippines&source=EVENTS&sortField=DATETIME",
]

_SCROLL_ROUNDS = 10           # number of scroll-and-wait cycles per page
_SCROLL_PAUSE_MS = 2_500      # ms to wait after each scroll
_INITIAL_WAIT_MS = 6_000      # ms to wait after page load before scrolling
_PAGE_TIMEOUT_MS = 90_000     # navigation timeout


# ---------------------------------------------------------------------------
# Datetime parsing
# ---------------------------------------------------------------------------

def _parse_dt(raw: str | int | None) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw / 1000 if raw > 1e10 else raw, tz=dt_timezone.utc)
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
                from zoneinfo import ZoneInfo
                dt = dt.replace(tzinfo=ZoneInfo("Asia/Manila"))
            return dt
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# GraphQL / JSON payload extraction
# ---------------------------------------------------------------------------

def _extract_event_nodes(payload: dict | list) -> list[dict]:
    """Walk a GraphQL response and collect all objects that look like events."""
    nodes: list[dict] = []
    if isinstance(payload, list):
        for item in payload:
            nodes.extend(_extract_event_nodes(item))
        return nodes
    if not isinstance(payload, dict):
        return nodes

    # Direct event node: has 'eventUrl' or ('title' + 'dateTime')
    if ("eventUrl" in payload or "event_url" in payload) and (
        "title" in payload or "name" in payload
    ):
        nodes.append(payload)
        return nodes

    # Walk deeper
    for value in payload.values():
        if isinstance(value, (dict, list)):
            nodes.extend(_extract_event_nodes(value))
    return nodes


def _extract_group_nodes(payload: dict | list, seen: set) -> list[dict]:
    """Collect unique group/organizer dicts from a payload."""
    groups: list[dict] = []
    if isinstance(payload, list):
        for item in payload:
            groups.extend(_extract_group_nodes(item, seen))
        return groups
    if not isinstance(payload, dict):
        return groups

    # A group node has 'urlname' and 'name'
    if "urlname" in payload and "name" in payload:
        uid = payload.get("id") or payload.get("urlname")
        if uid and uid not in seen:
            seen.add(uid)
            groups.append(payload)
        return groups

    for value in payload.values():
        if isinstance(value, (dict, list)):
            groups.extend(_extract_group_nodes(value, seen))
    return groups


# ---------------------------------------------------------------------------
# Domain model builders
# ---------------------------------------------------------------------------

def _build_venue(event_node: dict) -> ScrapedVenue | None:
    venue = event_node.get("venue") or {}
    if not venue:
        return None

    name = (venue.get("name") or "").strip()
    if not name:
        return None

    address_parts = [
        venue.get("address", ""),
        venue.get("address1", ""),
        venue.get("address2", ""),
    ]
    address = ", ".join(p for p in address_parts if p).strip(", ")

    # Use Meetup's venue ID as a stable dedup key scoped to this source
    venue_id = str(venue.get("id") or "").strip()

    # Link back to the event page as the closest source URL for the venue
    event_url = (event_node.get("eventUrl") or event_node.get("event_url") or "").strip()

    return ScrapedVenue(
        name=name,
        address=address,
        city=(venue.get("city") or "").strip(),
        country=(venue.get("country") or "Philippines").strip(),
        latitude=venue.get("lat") or venue.get("latitude"),
        longitude=venue.get("lon") or venue.get("lng") or venue.get("longitude"),
        place_id=venue_id,
        source_url=event_url,
    )


def _extract_category(node: dict) -> str:
    """Return a comma-joined string of Meetup topic names for this event."""
    topics = node.get("topics") or node.get("tags") or []
    if isinstance(topics, list):
        names = [
            (t.get("name") or t.get("urlkey") or t if isinstance(t, str) else "").strip()
            for t in topics
        ]
        return ", ".join(n for n in names if n)[:120]
    return ""


def _build_event(node: dict) -> ScrapedEvent | None:
    title = (node.get("title") or node.get("name") or "").strip()
    if not title:
        return None

    event_url = (node.get("eventUrl") or node.get("event_url") or "").strip()
    external_id = str(node.get("id") or "")
    if not external_id and event_url:
        m = re.search(r"/events/(\d+)", event_url)
        if m:
            external_id = m.group(1)

    group = node.get("group") or {}
    group_urlname = (group.get("urlname") or "").strip()
    organizer_name = (group.get("name") or "").strip()
    organizer_url = (
        f"{_MEETUP_BASE}/{group_urlname}" if group_urlname else (group.get("link") or "")
    ).strip()

    image_url = (
        node.get("imageUrl")
        or node.get("image_url")
        or node.get("featuredEventPhoto", {}).get("photoUrl", "")
        or (node.get("imageUrls") or [None])[0]
        or ""
    )

    is_free = node.get("isFree") or node.get("is_free")
    fee = node.get("fee") or node.get("rsvpSettings") or {}
    if isinstance(fee, dict):
        amount = fee.get("amount") or fee.get("price") or fee.get("cost") or ""
        currency = fee.get("currency") or ""
        price = f"{currency}{amount}".strip() if amount else ("Free" if is_free else "")
    else:
        price = "Free" if is_free else ""

    return ScrapedEvent(
        name=title,
        description=(
            node.get("description")
            or node.get("shortDescription")
            or node.get("short_description")
            or ""
        )[:5000],
        starts_at=_parse_dt(node.get("dateTime") or node.get("date_time") or node.get("time")),
        ends_at=_parse_dt(node.get("endTime") or node.get("end_time")),
        url=event_url,
        image_url=image_url,
        price=price,
        category=_extract_category(node),
        external_id=external_id,
        source_url=_SOURCE_URL,
        organizer=organizer_name[:255],
        organizer_url=organizer_url,
        venue=_build_venue(node),
    )


def _build_organizer(group: dict) -> ScrapedOrganizer | None:
    name = (group.get("name") or "").strip()
    if not name:
        return None

    urlname = (group.get("urlname") or "").strip()
    external_id = str(group.get("id") or urlname)
    group_url = f"{_MEETUP_BASE}/{urlname}" if urlname else (group.get("link") or "")

    # Social links — Meetup groups may expose these on their profile
    social = group.get("socialLinks") or group.get("social_links") or []
    facebook_url = instagram_url = ""
    if isinstance(social, list):
        for link in social:
            href = (link.get("url") or link.get("href") or "").lower()
            if "facebook.com" in href:
                facebook_url = href
            elif "instagram.com" in href:
                instagram_url = href
    elif isinstance(social, dict):
        facebook_url = social.get("facebook", "")
        instagram_url = social.get("instagram", "")

    # Some group nodes embed a direct website separate from the Meetup group URL
    website = (group.get("website") or group.get("link") or group_url).strip()

    return ScrapedOrganizer(
        name=name,
        external_id=external_id,
        source_url=group_url,
        website=website,
        city=(group.get("city") or "").strip(),
        country=(group.get("country") or "Philippines").strip(),
        description=(group.get("description") or group.get("about") or "")[:1000],
        facebook_url=facebook_url,
        instagram_url=instagram_url,
    )


# ---------------------------------------------------------------------------
# __NEXT_DATA__ extraction
# ---------------------------------------------------------------------------

def _extract_next_data(html: str) -> dict:
    m = re.search(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class MeetupScraper(BaseScraper):
    source = "meetup"

    def _collect_raw(self) -> tuple[list[dict], list[dict]]:
        """Return (event_nodes, group_nodes) collected across all search URLs."""
        all_payloads: list[dict | list] = []
        seen_urls: set[str] = set()

        _proxy_arg = None
        if get_proxy_enabled():
            try:
                _sess = get_proxy_session()
                _purl = _sess.proxies.get("https") or _sess.proxies.get("http")
                if _purl:
                    _proxy_arg = {"server": _purl}
            except Exception:
                pass  # no proxy available — continue without

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                **({"proxy": _proxy_arg} if _proxy_arg else {}),
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                timezone_id="Asia/Manila",
            )

            def _on_response(response):
                url = response.url
                if "meetup.com" not in url:
                    return
                if response.status != 200:
                    return
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                try:
                    body = response.json()
                    all_payloads.append(body)
                except Exception:
                    pass

            page = context.new_page()
            Stealth().use_sync(page)
            page.on("response", _on_response)

            for url in _SEARCH_URLS:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                logger.info("Meetup: loading %s", url)
                try:
                    page.goto(url, wait_until="load", timeout=_PAGE_TIMEOUT_MS)
                    page.wait_for_timeout(_INITIAL_WAIT_MS)

                    # Scroll to trigger lazy-loading / infinite scroll
                    for i in range(_SCROLL_ROUNDS):
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(_SCROLL_PAUSE_MS)
                        # Try clicking "See more" / "Load more" buttons
                        for selector in [
                            "button:has-text('See more')",
                            "button:has-text('Load more')",
                            "button:has-text('Show more')",
                            "[data-testid='load-more']",
                        ]:
                            try:
                                btn = page.query_selector(selector)
                                if btn and btn.is_visible():
                                    btn.click()
                                    page.wait_for_timeout(2_000)
                            except Exception:
                                pass

                    # Also grab __NEXT_DATA__ from the page HTML
                    html = page.content()
                    next_data = _extract_next_data(html)
                    if next_data:
                        all_payloads.append(next_data)

                except Exception as exc:
                    logger.error("Meetup: failed to load %s: %s", url, exc)

            browser.close()

        # Deduplicate event nodes by id/url
        event_nodes: list[dict] = []
        seen_event_ids: set[str] = set()
        group_nodes: list[dict] = []
        seen_group_ids: set[str] = set()

        for payload in all_payloads:
            for node in _extract_event_nodes(payload):
                uid = (
                    str(node.get("id") or "")
                    or node.get("eventUrl", "")
                    or node.get("event_url", "")
                )
                if uid and uid in seen_event_ids:
                    continue
                if uid:
                    seen_event_ids.add(uid)
                event_nodes.append(node)

            for grp in _extract_group_nodes(payload, seen_group_ids):
                group_nodes.append(grp)

        logger.info(
            "Meetup: collected %d event nodes, %d group nodes",
            len(event_nodes),
            len(group_nodes),
        )
        return event_nodes, group_nodes

    def fetch(self) -> Iterable[ScrapedEvent]:
        event_nodes, _ = self._collect_raw()
        for node in event_nodes:
            ev = _build_event(node)
            if ev:
                yield ev

    def run(self, **_kwargs) -> dict:
        event_nodes, group_nodes = self._collect_raw()

        events = [ev for node in event_nodes if (ev := _build_event(node))]
        organizers = [org for grp in group_nodes if (org := _build_organizer(grp))]

        logger.info(
            "Meetup: %d events, %d organizers to save", len(events), len(organizers)
        )

        events_result = save_events(self.source, events)
        organizers_result = save_organizers(self.source, organizers)

        return {
            **events_result,
            "organizers_created": organizers_result["created"],
            "organizers_updated": organizers_result["updated"],
        }
