"""Scraper for eventbookings.com Philippine events.

Two-step process:
  1. POST to the internal explore API to paginate all PH event listings.
  2. GET each event detail page to extract full data via Schema.org JSON-LD.
  3. GET each organizer profile page to collect contact/social info.

No JavaScript rendering required — all pages are server-rendered HTML.
robots.txt explicitly allows bots; ClaudeBot/anthropic-ai are whitelisted.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime

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

_EXPLORE_API = "https://explore.eventbookings.com/api/explore-events"
_SITE = "https://www.eventbookings.com"
_SOURCE_URL = f"{_SITE}/en-ph/explore-events/"
_COUNTRY = "PH"
_CURRENCY = "PHP"
_CURRENCY_SYMBOL = "₱"
_PER_PAGE = 16
_TIMEOUT = 30
_DELAY = 0.5  # seconds between detail-page requests

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_API_HEADERS = {
    **_HEADERS,
    "Origin": _SITE,
    "Referer": f"{_SITE}/en-ph/explore-events/",
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

# Schema.org @type values that represent events.
_EVENT_SCHEMA_TYPES = {
    "Event", "MusicEvent", "BusinessEvent", "SocialEvent",
    "EducationEvent", "EntertainmentEvent", "SportsEvent",
    "FoodEvent", "LiteraryEvent", "VisualArtsEvent",
    "ComedyEvent", "DanceEvent", "TheaterEvent",
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _post_explore(offset: int) -> dict:
    # position starts at 1 (not 0) — sending position=0 triggers a 500 on their server.
    # country="" (empty); the country filter is applied via current_country_code_trp.
    position = (offset // _PER_PAGE) + 1
    try:
        resp = requests.post(
            _EXPLORE_API,
            headers=_API_HEADERS,
            data={
                "action": "load_more_events",
                "per_page": _PER_PAGE,
                "shwFltrs": "1",
                "excldPstEvnts": "1",
                "eventType": "",
                "eventLbl": "",
                "fltrDays": "All",
                "city": "",
                "state": "",
                "pc": "",
                "country": "",
                "current_language_trp": "tl_PH",
                "current_country_name_trp": "Philippines",
                "current_country_code_trp": _COUNTRY,
                "current_currency_trp": _CURRENCY,
                "tz": "Asia/Singapore",
                "ofst": offset,
                "position": position,
            },
            params={"t": int(time.time() * 1000)},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("eventbookings: explore API error at offset %d: %s", offset, exc)
        return {}


def _get_html(url: str) -> str:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        time.sleep(_DELAY)
        return resp.text
    except Exception as exc:
        logger.error("eventbookings: GET failed for %s: %s", url, exc)
        return ""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _extract_schema_org(html: str) -> dict:
    """Return the first Event-type Schema.org JSON-LD block found in the page."""
    soup = BeautifulSoup(html, "lxml")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") in _EVENT_SCHEMA_TYPES:
                    return item
        except (json.JSONDecodeError, AttributeError):
            pass
    return {}


def _parse_iso_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _price_str(pricing: dict) -> str:
    if pricing.get("is_free"):
        return "Free"
    amount = pricing.get("actual_price") or ""
    symbol = pricing.get("currency_symbol") or _CURRENCY_SYMBOL
    return f"{symbol}{amount}" if amount else ""


def _build_venue(location: dict, event_url: str) -> ScrapedVenue | None:
    # Skip virtual / online events
    if location.get("@type") == "VirtualLocation":
        return None
    name = (location.get("name") or "").strip()
    if not name:
        return None
    addr = location.get("address") or {}
    street = (addr.get("streetAddress") or "").strip()
    locality = (addr.get("addressLocality") or "").strip()
    region = (addr.get("addressRegion") or "").strip()
    postal = (addr.get("postalCode") or "").strip()
    country = (addr.get("addressCountry") or "").strip()
    full_address = ", ".join(filter(None, [street, postal]))
    return ScrapedVenue(
        name=name,
        address=full_address,
        city=locality or region,
        country=country,
        source_url=event_url,
    )


def _organizer_from_schema(org_field) -> tuple[str, str]:
    """Return (name, url) from Schema.org organizer field (dict or list)."""
    if isinstance(org_field, list):
        org_field = org_field[0] if org_field else {}
    if not isinstance(org_field, dict):
        return "", ""
    return (org_field.get("name") or "").strip(), (org_field.get("url") or "").strip()


def _scrape_organizer_profile(org_url: str, org_uuid: str, org_name: str) -> ScrapedOrganizer:
    """Fetch the organizer profile page and extract bio.

    Social links (website, Facebook, Instagram) are injected by JavaScript and
    are not present in the static HTML — we only extract the text bio here.
    """
    html = _get_html(org_url)
    description = ""

    if html:
        soup = BeautifulSoup(html, "lxml")
        # bio-section is always present; it carries 'd-none' when the organizer
        # hasn't written a bio (content is just the "Bio" / "MoreLess" UI text).
        bio_el = soup.select_one("div.bio-section:not(.d-none)")
        if bio_el:
            raw = bio_el.get_text(separator=" ", strip=True)
            # Strip leading "Bio" label and trailing "MoreLess" toggle text.
            raw = raw.removeprefix("Bio").removesuffix("MoreLess").strip()
            if len(raw) > 5:
                description = raw

    return ScrapedOrganizer(
        name=org_name,
        external_id=org_uuid,
        description=description,
        source_url=org_url,
    )


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class EventBookingsScraper(BaseScraper):
    """Scraper for eventbookings.com Philippine events.

    Uses the explore API to list events and per-page Schema.org JSON-LD for
    full event + venue + organizer data. Organizer profile pages are fetched
    once per unique organizer UUID discovered across all events.
    """

    source = "eventbookings"

    def _fetch_all_listings(self) -> list[dict]:
        all_events: list[dict] = []
        offset = 0
        while True:
            data = _post_explore(offset)
            batch = data.get("events") or []
            if not batch:
                break
            all_events.extend(batch)
            logger.info("eventbookings: %d events at offset %d", len(batch), offset)
            if len(batch) < _PER_PAGE:
                break
            offset += _PER_PAGE
            time.sleep(_DELAY)
        return all_events

    def _process_listing(
        self,
        listing: dict,
        organizers: dict[str, ScrapedOrganizer],
    ) -> ScrapedEvent | None:
        event_url = (listing.get("url") or "").strip()
        if not event_url:
            return None

        html = _get_html(event_url)
        if not html:
            return None

        schema = _extract_schema_org(html)
        if not schema:
            logger.warning("eventbookings: no Schema.org block at %s", event_url)
            return None

        # Datetimes come with timezone offset from Schema.org (reliable)
        starts_at = _parse_iso_dt(schema.get("startDate") or "")
        ends_at = _parse_iso_dt(schema.get("endDate") or "")

        # Image — Schema.org image is either a string or list
        images = schema.get("image") or []
        if isinstance(images, str):
            images = [images]
        image_url = images[0] if images else ""

        # Category from listing API (more structured than Schema.org)
        cats = listing.get("categories") or []
        category = ", ".join(c["cat_title"] for c in cats if c.get("cat_title"))

        # Price from listing API pricing block
        price = _price_str(listing.get("pricing") or {})

        # Organizer from Schema.org
        org_name, org_url = _organizer_from_schema(schema.get("organizer"))
        org_uuid = (listing.get("organisation_uuid") or "").strip()

        # Fetch organizer profile once per UUID
        if org_uuid and org_uuid not in organizers:
            if org_url and org_name:
                organizers[org_uuid] = _scrape_organizer_profile(org_url, org_uuid, org_name)
            elif org_name:
                organizers[org_uuid] = ScrapedOrganizer(
                    name=org_name,
                    external_id=org_uuid,
                    source_url=org_url,
                )

        venue = _build_venue(schema.get("location") or {}, event_url)
        external_id = (listing.get("uuid") or listing.get("slug") or "").strip()

        return ScrapedEvent(
            name=(schema.get("name") or listing.get("name") or "").strip(),
            description=(schema.get("description") or "").strip(),
            starts_at=starts_at,
            ends_at=ends_at,
            url=schema.get("url") or event_url,
            image_url=image_url,
            price=price,
            category=category,
            external_id=external_id,
            source_url=_SOURCE_URL,
            organizer=org_name,
            organizer_url=org_url,
            venue=venue,
        )

    def _collect(self) -> tuple[list[ScrapedEvent], list[ScrapedOrganizer]]:
        listings = self._fetch_all_listings()
        logger.info("eventbookings: %d total listings to process", len(listings))

        events: list[ScrapedEvent] = []
        organizers: dict[str, ScrapedOrganizer] = {}

        for i, listing in enumerate(listings, 1):
            logger.debug("eventbookings: event %d/%d", i, len(listings))
            event = self._process_listing(listing, organizers)
            if event and event.name:
                events.append(event)

        logger.info(
            "eventbookings: %d events, %d organizers collected",
            len(events),
            len(organizers),
        )
        return events, list(organizers.values())

    def fetch(self):
        events, _ = self._collect()
        yield from events

    def run(self, **_kwargs) -> dict:
        events, organizers = self._collect()
        events_result = save_events(self.source, events)
        organizers_result = save_organizers(self.source, organizers)
        return {
            **events_result,
            "organizers_created": organizers_result["created"],
            "organizers_updated": organizers_result["updated"],
        }
