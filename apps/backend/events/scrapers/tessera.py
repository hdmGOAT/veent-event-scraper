"""Tessera event scraper — discovers events in Singapore.

Tessera (yourtessera.com) is a Singapore-based ticketing platform.
All event data lives in schema.org/Event JSON-LD injected by Next.js,
so every page requires a headless browser (StealthyFetcher / camoufox).

Strategy:
  1. Fetch /discover/events-in-singapore — parse ItemList for event URLs.
  2. Fetch each /e/[slug] event page — extract full description, organizer.
  3. Fetch each /o/[slug] organizer page — extract social links and bio.

No images are stored (image_url left blank per project preference).
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone as dt_timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup

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

_BASE_URL = "https://www.yourtessera.com"
_DISCOVER_URL = f"{_BASE_URL}/discover/events-in-singapore"
_DELAY = 2.0
_UTC = dt_timezone.utc


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _get_proxy() -> str | None:
    if not get_proxy_enabled():
        return None
    try:
        sess = get_proxy_session()
        return sess.proxies.get("https") or sess.proxies.get("http")
    except Exception:
        return None


def _fetch_html(url: str, proxy: str | None) -> str:
    from scrapling.fetchers import StealthyFetcher
    try:
        result = StealthyFetcher.fetch(url, headless=True, network_idle=True, proxy=proxy)
        return result.html_content or ""
    except Exception as exc:
        logger.warning("Tessera: fetch failed %s: %s", url, exc)
        return ""


# ---------------------------------------------------------------------------
# JSON-LD helpers
# ---------------------------------------------------------------------------

def _extract_ld_scripts(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            results.append(json.loads(tag.get_text()))
        except json.JSONDecodeError:
            pass
    return results


def _find_by_type(ld_list: list[dict], typename: str) -> dict | None:
    """Search LD documents and @graph arrays for a node of the given @type."""
    for doc in ld_list:
        if doc.get("@type") == typename:
            return doc
        for node in doc.get("@graph", []):
            if node.get("@type") == typename:
                return node
    return None


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_iso(raw: str) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=_UTC)
        except ValueError:
            pass
    return None


def _format_price(offers) -> str:
    if not offers:
        return ""
    if isinstance(offers, dict):
        offers = [offers]
    prices: list[float] = []
    currency = "SGD"
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        if offer.get("priceCurrency"):
            currency = offer["priceCurrency"]
        # AggregateOffer uses lowPrice; regular Offer uses price
        raw = offer.get("price") if offer.get("price") is not None else offer.get("lowPrice")
        try:
            val = float(raw)
            if val > 0:
                prices.append(val)
        except (TypeError, ValueError):
            pass
    if not prices:
        return "Free"
    low = min(prices)
    formatted = f"{int(low)}" if low == int(low) else f"{low:.2f}"
    return f"{currency} {formatted}"


def _extract_venue(location: dict) -> ScrapedVenue | None:
    if not location or location.get("@type") != "Place":
        return None
    name = location.get("name", "").strip()
    addr = location.get("address", {})
    street = addr.get("streetAddress", "").strip()
    city = addr.get("addressLocality", "").strip()
    country = addr.get("addressCountry", "").strip()
    postal = addr.get("postalCode", "").strip()
    full_address = ", ".join(filter(None, [street, postal]))
    if not name and not full_address:
        return None
    return ScrapedVenue(
        name=name,
        address=full_address,
        city=city,
        country=country,
        source_url=_BASE_URL,
    )


def _slug_from_url(url: str) -> str:
    return urlparse(url).path.strip("/").split("/")[-1]


# ---------------------------------------------------------------------------
# Discover page — collect event URLs
# ---------------------------------------------------------------------------

def _collect_event_urls(html: str) -> list[str]:
    ld_list = _extract_ld_scripts(html)
    item_list = _find_by_type(ld_list, "ItemList")
    if not item_list:
        logger.warning("Tessera: no ItemList in discover page JSON-LD")
        return []
    urls = []
    for list_item in item_list.get("itemListElement", []):
        item = list_item.get("item", {})
        # URL is either explicit or derived from @id by dropping the #fragment
        url = item.get("url") or item.get("@id", "").split("#")[0]
        if url and url.startswith("http"):
            urls.append(url)
    return urls


# ---------------------------------------------------------------------------
# Event detail page
# ---------------------------------------------------------------------------

def _parse_event_page(html: str, url: str) -> tuple[ScrapedEvent | None, str]:
    """Return (ScrapedEvent, organizer_page_url). organizer_page_url may be ''."""
    ld_list = _extract_ld_scripts(html)
    ev = _find_by_type(ld_list, "Event")
    if not ev:
        logger.warning("Tessera: no Event JSON-LD at %s", url)
        return None, ""

    name = ev.get("name", "").strip()
    if not name:
        return None, ""

    description = ev.get("description", "").strip()
    starts_at = _parse_iso(ev.get("startDate", ""))
    ends_at = _parse_iso(ev.get("endDate", ""))
    price = _format_price(ev.get("offers", {}))
    venue = _extract_venue(ev.get("location", {}))

    org_data = ev.get("organizer", {})
    if isinstance(org_data, list):
        org_data = org_data[0] if org_data else {}
    organizer_name = org_data.get("name", "").strip()
    organizer_url = org_data.get("url", "").strip()

    event = ScrapedEvent(
        name=name,
        description=description,
        starts_at=starts_at,
        ends_at=ends_at,
        url=url,
        image_url="",
        registration_url=url,
        price=price,
        external_id=_slug_from_url(url),
        source_url=_DISCOVER_URL,
        organizer=organizer_name,
        organizer_url=organizer_url,
        venue=venue,
    )
    return event, organizer_url


# ---------------------------------------------------------------------------
# Organizer page
# ---------------------------------------------------------------------------

def _parse_organizer_page(html: str, source_url: str) -> ScrapedOrganizer | None:
    ld_list = _extract_ld_scripts(html)
    profile = _find_by_type(ld_list, "ProfilePage")
    if not profile:
        return None

    org_data = profile.get("mainEntity", {})
    name = org_data.get("name", "").strip()
    if not name:
        return None

    description = org_data.get("description", "").strip()
    website = facebook_url = instagram_url = ""

    for same_as in org_data.get("sameAs", []):
        if not same_as.startswith("http"):
            continue
        netloc = urlparse(same_as).netloc.lower().lstrip("www.")
        if "facebook.com" in netloc or "fb.com" in netloc:
            if not facebook_url:
                facebook_url = same_as
        elif "instagram.com" in netloc:
            if not instagram_url:
                instagram_url = same_as
        elif "yourtessera.com" not in netloc and not website:
            website = same_as

    return ScrapedOrganizer(
        name=name,
        description=description,
        website=website,
        facebook_url=facebook_url,
        instagram_url=instagram_url,
        external_id=_slug_from_url(source_url),
        source_url=source_url,
    )


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

class TesseraScraper(BaseScraper):
    source = "tessera"

    def _collect(self) -> tuple[list[ScrapedEvent], list[ScrapedOrganizer]]:
        proxy = _get_proxy()

        logger.info("Tessera: fetching discover page")
        discover_html = _fetch_html(_DISCOVER_URL, proxy)
        if not discover_html:
            logger.error("Tessera: could not fetch discover page")
            return [], []

        event_urls = _collect_event_urls(discover_html)
        logger.info("Tessera: %d event URLs found", len(event_urls))
        if not event_urls:
            return [], []

        events: list[ScrapedEvent] = []
        # Keyed by organizer name — always create a row, even without a profile URL.
        org_by_name: dict[str, ScrapedOrganizer] = {}
        # Organizer profile pages to fetch for enrichment: slug → full URL.
        org_profile_by_slug: dict[str, str] = {}

        for event_url in event_urls:
            logger.info("Tessera: event %s", event_url)
            html = _fetch_html(event_url, proxy)
            if not html:
                continue

            event, org_url = _parse_event_page(html, event_url)
            if event:
                events.append(event)

                org_name = event.organizer
                if org_name and org_name not in org_by_name:
                    # Build a minimal organizer row from whatever the event gives us.
                    # Profile pages may upgrade this below.
                    ext_id = (
                        _slug_from_url(org_url)
                        if org_url
                        else re.sub(r"[^a-z0-9]+", "-", org_name.lower()).strip("-")
                    )
                    org_by_name[org_name] = ScrapedOrganizer(
                        name=org_name,
                        # Only store as website if it's not a Tessera internal URL
                        website="" if (not org_url or "/o/" in org_url) else org_url,
                        external_id=ext_id,
                        source_url=org_url or _DISCOVER_URL,
                    )

                if org_url and "/o/" in org_url:
                    slug = _slug_from_url(org_url)
                    org_profile_by_slug.setdefault(slug, org_url)

            time.sleep(_DELAY)

        # Enrich organizers that have Tessera profile pages.
        for slug, org_url in org_profile_by_slug.items():
            logger.info("Tessera: organizer profile %s", org_url)
            html = _fetch_html(org_url, proxy)
            if not html:
                continue
            org = _parse_organizer_page(html, org_url)
            if org:
                # Replace the basic entry with the fully enriched version.
                org_by_name[org.name] = org
            time.sleep(_DELAY)

        organizers = list(org_by_name.values())
        logger.info(
            "Tessera: collected %d events, %d organizers",
            len(events), len(organizers),
        )
        return events, organizers

    def fetch(self):
        events, _ = self._collect()
        yield from events

    def run(self, **_kwargs) -> dict:
        events, organizers = self._collect()
        # Save organizers first so _resolve_organizer() can link the FK when
        # save_events() runs immediately after.
        organizers_result = save_organizers(self.source, organizers)
        events_result = save_events(self.source, events)
        return {
            **events_result,
            "organizers_created": organizers_result["created"],
            "organizers_updated": organizers_result["updated"],
        }
