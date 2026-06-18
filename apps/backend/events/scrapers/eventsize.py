"""Scraper for eventsize.com event pages.

Eventsize is a ticketing/registration platform that publishes server-side
rendered event pages at https://eventsize.com/event/{shortcode}. Each page
embeds Schema.org JSON-LD describing the event, which is the primary parse
source (Open Graph meta tags are used as a fallback for malformed pages).

Discovery (two-pronged, combined):
  1. Google SERP via StealthyFetcher (camoufox browser) — searches multiple
     queries and paginates, collecting URLs that match ``eventsize.com/event/``.
     One fresh browser session is used per search page for reliability.
  2. Public listing API — iterates known PH cities against the public offers
     endpoint and extracts event shortcodes not indexed by Google.

Fetching: plain ``requests`` + lxml (event pages are server-side rendered).
Parsing:  Schema.org JSON-LD ("@type": "Event") → Open Graph meta fallbacks.

Organizer profiles (https://eventsize.com/@Handle) are scraped once each for
email and social links.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Iterable
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

from .base import (
    BaseScraper,
    ScrapedEvent,
    ScrapedOrganizer,
    ScrapedVenue,
    save_events,
    save_organizers,
)

logger = logging.getLogger(__name__)

_SOURCE_URL = "https://eventsize.com"
_EVENT_PREFIX = "https://eventsize.com/event/"
_TIMEOUT = 30
_DELAY = 1.2  # seconds between individual event page requests
_API_DELAY = 1.0  # seconds between API discovery calls
_PHT = dt_timezone(timedelta(hours=8))  # default tz when an offset is absent

# Standard request headers for both event pages and the discovery API.
_SESSION_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

_API_HEADERS = {
    "User-Agent": _SESSION_HEADERS["User-Agent"],
    "Accept": "application/json",
    "Referer": "https://eventsize.com/",
}

_API_BASE = (
    "https://eventsize.com/API/v1.0/index.php"
    "?system=offers&type=public-unique&location={location}"
)

# Domains to ignore when collecting links from organizer pages.
_SKIP_DOMAINS = frozenset([
    "eventsize.com",
    "google.com", "google.co", "bing.com", "msn.com",
    "apple.com", "microsoft.com",
])

# Google queries — variety broadens coverage across event types and years.
_SEARCH_QUERIES = [
    "site:eventsize.com/event/ 2026",
    "site:eventsize.com/event/ Philippines 2026",
    "site:eventsize.com/event/ festival fair 2026",
    "site:eventsize.com/event/ concert show 2026",
    "site:eventsize.com/event/ 2025",
    "site:eventsize.com/event/ registration admission",
]
_GOOGLE_PAGES_PER_QUERY = 3
_GOOGLE_PAGE_SIZE = 10

# PH locations for API discovery (city slugs as used by the offers endpoint).
_PH_LOCATIONS = [
    "Philippines",
    "Philippines--Manila",
    "Philippines--Quezon-City",
    "Philippines--Makati",
    "Philippines--Taguig",
    "Philippines--Pasig",
    "Philippines--Cebu",
    "Philippines--Davao",
    "Philippines--Pasay",
    "Philippines--Paranaque",
    "Philippines--Marikina",
    "Philippines--Caloocan",
    "Philippines--Las-Pinas",
    "Philippines--Muntinlupa",
    "Philippines--Mandaluyong",
    "Philippines--San-Juan",
    "Philippines--Valenzuela",
    "Philippines--Malabon",
]


# ---------------------------------------------------------------------------
# HTTP session (for event page + organizer fetching)
# ---------------------------------------------------------------------------

def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_SESSION_HEADERS)
    return s


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def _shortcode_from_url(url: str) -> str:
    """Return the shortcode (everything after ``/event/``) or "" if not an event URL."""
    try:
        parsed = urlparse(url)
        if parsed.netloc.lower().replace("www.", "") != "eventsize.com":
            return ""
        m = re.match(r"^/event/([^/?#]+)", parsed.path)
        return m.group(1).strip() if m else ""
    except Exception:
        return ""


def _event_url(shortcode: str) -> str:
    return f"{_EVENT_PREFIX}{shortcode}"


# ---------------------------------------------------------------------------
# Discovery — Phase 1: Google SERP via StealthyFetcher
# ---------------------------------------------------------------------------

def _google_search_urls(queries: list[str], pages_per_query: int) -> set[str]:
    """Run Google queries via StealthyFetcher, one fresh browser session per page.

    A separate ``StealthyFetcher.fetch()`` call is made for every search page so
    that browser sessions are never reused across pages (reusing sessions caused
    silent failures in the sibling TicketSpice scraper).
    """
    from scrapling.fetchers import StealthyFetcher

    found: set[str] = set()

    for query in queries:
        for page_num in range(pages_per_query):
            start = page_num * _GOOGLE_PAGE_SIZE
            search_url = (
                f"https://www.google.com/search"
                f"?q={quote_plus(query)}&num=30"
                + (f"&start={start}" if start else "")
            )
            new_on_page = 0

            def _collect(page) -> None:
                nonlocal new_on_page
                page.wait_for_timeout(2_000)
                links = page.evaluate(
                    "() => [...document.querySelectorAll('a[href]')].map(a => a.href)"
                )
                for link in links:
                    link = str(link)
                    if "eventsize.com/event/" not in link:
                        continue
                    shortcode = _shortcode_from_url(link)
                    if not shortcode:
                        continue
                    url = _event_url(shortcode)
                    if url not in found:
                        found.add(url)
                        new_on_page += 1

            try:
                StealthyFetcher.fetch(
                    search_url,
                    headless=True,
                    network_idle=False,
                    page_action=_collect,
                )
            except Exception as exc:
                logger.warning(
                    "Eventsize: Google search error (query=%r page=%d): %s",
                    query, page_num, exc,
                )
                break  # Browser crashed — skip remaining pages for this query

            logger.debug(
                "Eventsize Google: query=%r page=%d -> %d new",
                query, page_num, new_on_page,
            )
            if new_on_page == 0:
                break  # No new results -> stop paginating this query

    logger.info("Eventsize: Google discovery -> %d URLs", len(found))
    return found


# ---------------------------------------------------------------------------
# Discovery — Phase 2: public listing API per PH city
# ---------------------------------------------------------------------------

def _api_discover_urls(locations: list[str]) -> set[str]:
    """Hit the public offers API per location and extract event shortcodes."""
    found: set[str] = set()
    session = requests.Session()
    session.headers.update(_API_HEADERS)

    for location in locations:
        url = _API_BASE.format(location=quote_plus(location))
        try:
            resp = session.get(url, timeout=_TIMEOUT)
            if resp.status_code == 429:
                logger.warning("Eventsize API: 429 rate limited at %s (skip)", location)
                time.sleep(_API_DELAY)
                continue
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("Eventsize API: error for location=%r: %s", location, exc)
            time.sleep(_API_DELAY)
            continue

        offers = []
        try:
            offers = data["offers"]["list"]
        except (KeyError, TypeError):
            logger.debug("Eventsize API: no offers.list for location=%r", location)

        new_here = 0
        if isinstance(offers, list):
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                shortcode = (offer.get("shortcode") or "").strip()
                if not shortcode:
                    continue
                u = _event_url(shortcode)
                if u not in found:
                    found.add(u)
                    new_here += 1

        logger.debug("Eventsize API: location=%r -> %d new", location, new_here)
        time.sleep(_API_DELAY)

    logger.info("Eventsize: API discovery -> %d URLs", len(found))
    return found


# ---------------------------------------------------------------------------
# JSON-LD + date parsing helpers
# ---------------------------------------------------------------------------

def _parse_jsonld(soup: BeautifulSoup) -> dict | None:
    """Return the first Schema.org JSON-LD object with ``@type`` Event, or None.

    Handles graphs (``@graph``) and JSON-LD blocks that are arrays of objects.
    """
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue

        candidates: list = []
        if isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                candidates.extend(data["@graph"])
            else:
                candidates.append(data)
        elif isinstance(data, list):
            candidates.extend(data)

        for obj in candidates:
            if not isinstance(obj, dict):
                continue
            obj_type = obj.get("@type", "")
            types = obj_type if isinstance(obj_type, list) else [obj_type]
            if any("Event" in str(t) for t in types):
                return obj

    return None


def _parse_date(raw: str) -> datetime | None:
    """Parse an eventsize date into a timezone-aware datetime.

    The site emits a non-standard ISO-ish format such as
    ``"2026-7-12T12:00:00+8.00"`` (single-digit month, ``+8.00`` offset rather
    than ``+08:00``). The trailing offset is normalized to ``+HH:MM`` before
    handing off to ``dateutil.parser.parse`` (which rejects the raw form).
    Naive results are assumed to be Philippine time (UTC+8).
    """
    from dateutil import parser as date_parser

    if not raw or not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw:
        return None

    # Normalize a trailing offset like "+8.00" / "-8.0" / "+08:00" -> "+HH:MM".
    m = re.search(r"([+-])(\d{1,2})[.:](\d{1,2})\s*$", raw)
    if m:
        sign, hours, minutes = m.group(1), int(m.group(2)), int(m.group(3))
        offset = f"{sign}{hours:02d}:{minutes:02d}"
        raw = raw[: m.start()] + offset

    try:
        dt = date_parser.parse(raw)
    except (ValueError, OverflowError, TypeError) as exc:
        logger.debug("Eventsize: unparseable date %r: %s", raw, exc)
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_PHT)
    return dt


def _extract_price(offers) -> str:
    """Return the minimum non-zero price as "$X.XX", or "Free" / "" otherwise.

    Accepts the JSON-LD ``offers`` value (a dict, a list of dicts, or None).
    """
    if not offers:
        return ""
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return ""

    prices: list[float] = []
    saw_offer = False
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        saw_offer = True
        raw_price = offer.get("price")
        if raw_price is None:
            continue
        try:
            value = float(str(raw_price).replace(",", "").strip())
        except (ValueError, TypeError):
            continue
        if value > 0:
            prices.append(value)

    if prices:
        return f"${min(prices):.2f}"
    if saw_offer:
        return "Free"
    return ""


def _og(soup: BeautifulSoup, prop: str) -> str:
    tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
    return (tag.get("content") or "").strip() if tag else ""


def _first_str(value) -> str:
    """Coerce a JSON-LD value (str, list, or dict with url) to a single string."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            s = _first_str(item)
            if s:
                return s
        return ""
    if isinstance(value, dict):
        return _first_str(value.get("url") or value.get("@id") or "")
    return ""


# ---------------------------------------------------------------------------
# Per-page parse
# ---------------------------------------------------------------------------

def _build_venue(jsonld: dict) -> ScrapedVenue | None:
    """Build a ScrapedVenue from JSON-LD ``location``; None for online events."""
    mode = str(jsonld.get("eventAttendanceMode") or "")
    if "Online" in mode:
        return None

    location = jsonld.get("location")
    if isinstance(location, list):
        location = next((l for l in location if isinstance(l, dict)), None)
    if not isinstance(location, dict):
        return None

    loc_type = location.get("@type", "")
    loc_types = loc_type if isinstance(loc_type, list) else [loc_type]
    if any("VirtualLocation" in str(t) for t in loc_types):
        return None

    name = _first_str(location.get("name"))
    address = location.get("address")
    addr_str = city = country = ""
    if isinstance(address, str):
        addr_str = address.strip()
    elif isinstance(address, dict):
        parts = [
            _first_str(address.get("streetAddress")),
            _first_str(address.get("addressLocality")),
            _first_str(address.get("addressRegion")),
            _first_str(address.get("postalCode")),
        ]
        addr_str = ", ".join(p for p in parts if p)
        city = _first_str(address.get("addressLocality"))
        country = _first_str(address.get("addressCountry"))

    if not (name or addr_str):
        return None

    return ScrapedVenue(
        name=name or addr_str,
        address=addr_str,
        city=city,
        country=country,
    )


def _parse_page(url: str, soup: BeautifulSoup) -> ScrapedEvent | None:
    """Parse an event page into a ScrapedEvent (JSON-LD primary, og fallback)."""
    shortcode = _shortcode_from_url(url)
    jsonld = _parse_jsonld(soup)

    if jsonld:
        name = _first_str(jsonld.get("name")) or _og(soup, "og:title")
        description = _first_str(jsonld.get("description")) or _og(soup, "og:description")
        image_url = _first_str(jsonld.get("image")) or _og(soup, "og:image")
        starts_at = _parse_date(_first_str(jsonld.get("startDate")))
        ends_at = _parse_date(_first_str(jsonld.get("endDate")))
        price = _extract_price(jsonld.get("offers"))

        organizer_name = ""
        organizer_url = ""
        organizer = jsonld.get("organizer")
        if isinstance(organizer, list):
            organizer = next((o for o in organizer if isinstance(o, dict)), None)
        if isinstance(organizer, dict):
            organizer_name = _first_str(organizer.get("name"))
            organizer_url = _first_str(organizer.get("url"))
        elif isinstance(organizer, str):
            organizer_name = organizer.strip()

        canonical = _first_str(jsonld.get("url")) or url
        venue = _build_venue(jsonld)
    else:
        # Malformed/missing JSON-LD — fall back to Open Graph meta tags.
        name = _og(soup, "og:title")
        description = _og(soup, "og:description")
        image_url = _og(soup, "og:image")
        starts_at = ends_at = None
        price = ""
        organizer_name = organizer_url = ""
        canonical = url
        venue = None

    if not name:
        logger.debug("Eventsize: no name for %s (skip)", url)
        return None

    return ScrapedEvent(
        name=name,
        description=description,
        starts_at=starts_at,
        ends_at=ends_at,
        url=canonical or url,
        image_url=image_url,
        price=price,
        external_id=shortcode,
        source_url=_SOURCE_URL,
        organizer=organizer_name,
        organizer_url=organizer_url,
        venue=venue,
    )


# ---------------------------------------------------------------------------
# Organizer profile scraping
# ---------------------------------------------------------------------------

def _handle_from_org_url(org_url: str) -> str:
    """Extract the ``@Handle`` (without the @) from an organizer profile URL."""
    try:
        path = urlparse(org_url).path.strip("/")
    except Exception:
        return ""
    if path.startswith("@"):
        path = path[1:]
    return path.split("/")[0].strip()


def _fetch_organizer(org_url: str, org_name: str) -> ScrapedOrganizer | None:
    """Scrape an organizer profile page for email + social links.

    Uses plain ``requests`` (no browser). Returns None on fetch failure.
    """
    handle = _handle_from_org_url(org_url)
    if not handle:
        return None

    session = _make_session()
    try:
        resp = session.get(org_url, timeout=_TIMEOUT, allow_redirects=True)
        if resp.status_code in (404, 410):
            logger.debug("Eventsize organizer: %s -> %d (skip)", org_url, resp.status_code)
            return None
        if resp.status_code == 429:
            logger.warning("Eventsize organizer: 429 at %s (skip)", org_url)
            return None
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Eventsize organizer: fetch failed %s: %s", org_url, exc)
        return None

    soup = BeautifulSoup(resp.text, "lxml")
    email = facebook_url = instagram_url = ""
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("mailto:") and not email:
            email = href[7:].split("?")[0].strip()
            continue
        low = href.lower()
        if "facebook.com" in low and not facebook_url:
            facebook_url = href
        elif "instagram.com" in low and not instagram_url:
            instagram_url = href

    return ScrapedOrganizer(
        name=org_name or handle,
        external_id=handle,
        source_url=org_url,
        email=email,
        facebook_url=facebook_url,
        instagram_url=instagram_url,
        website="",
    )


# ---------------------------------------------------------------------------
# Event page fetching
# ---------------------------------------------------------------------------

def _fetch_page(url: str, session: requests.Session) -> BeautifulSoup | None:
    try:
        resp = session.get(url, timeout=_TIMEOUT, allow_redirects=True)
        if resp.status_code in (404, 410):
            logger.debug("Eventsize: %s -> %d (skip)", url, resp.status_code)
            return None
        if resp.status_code == 429:
            logger.warning("Eventsize: 429 rate limited at %s (skip)", url)
            return None
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except Exception as exc:
        logger.debug("Eventsize: fetch failed %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# Main scraper class
# ---------------------------------------------------------------------------

class EventsizeScraper(BaseScraper):
    source = "eventsize"

    def _collect(self) -> tuple[list[ScrapedEvent], list[ScrapedOrganizer]]:
        # --- Discovery: Google SERP + API city iteration, combined ---
        urls = _google_search_urls(_SEARCH_QUERIES, pages_per_query=_GOOGLE_PAGES_PER_QUERY)
        urls |= _api_discover_urls(_PH_LOCATIONS)
        if not urls:
            logger.warning("Eventsize: no event URLs discovered — check network connectivity")
            return [], []
        logger.info("Eventsize: %d total unique event URLs", len(urls))

        session = _make_session()
        events: list[ScrapedEvent] = []
        organizer_urls: dict[str, str] = {}  # org_url -> org_name (first seen)

        for url in sorted(urls):
            soup = _fetch_page(url, session)
            if not soup:
                continue
            try:
                event = _parse_page(url, soup)
            except Exception as exc:
                logger.error("Eventsize: parse error for %s: %s", url, exc)
                event = None

            if event:
                events.append(event)
                if event.organizer_url and event.organizer_url not in organizer_urls:
                    organizer_urls[event.organizer_url] = event.organizer

            time.sleep(_DELAY)

        # --- Organizer profiles: scrape each unique profile once ---
        organizers: list[ScrapedOrganizer] = []
        for org_url, org_name in organizer_urls.items():
            try:
                org = _fetch_organizer(org_url, org_name)
            except Exception as exc:
                logger.error("Eventsize: organizer error for %s: %s", org_url, exc)
                org = None
            if org:
                organizers.append(org)
            time.sleep(_DELAY)

        logger.info("Eventsize: %d events, %d organizers", len(events), len(organizers))
        return events, organizers

    def fetch(self) -> Iterable[ScrapedEvent]:
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
