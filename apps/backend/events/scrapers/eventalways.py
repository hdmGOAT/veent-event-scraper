"""EventAlways.com Philippines scraper.

SSR site protected by Cloudflare Turnstile. Strategy:
  1. Iterate category listing pages (?page=N) via StealthyFetcher + solve_cloudflare.
  2. Collect event URLs and basic metadata from listing cards.
  3. Fetch each unique event detail page to extract LD+JSON (description, endDate,
     venue coordinates) and organizer info.
  4. Save both events and organizers to the database.

No browser window appears — StealthyFetcher runs headless.

Run:
    python manage.py scrape eventalways
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Iterable
from zoneinfo import ZoneInfo

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

_MANILA_TZ = ZoneInfo("Asia/Manila")
_BASE_URL = "https://www.eventalways.com"
_SOURCE_URL = f"{_BASE_URL}/philippines"

# Category listing pages to scrape; add more slugs as needed.
_CATEGORY_URLS = [
    f"{_BASE_URL}/philippines",
    f"{_BASE_URL}/philippines/exhibitions",
    f"{_BASE_URL}/philippines/business",
    f"{_BASE_URL}/philippines/it-technology",
    f"{_BASE_URL}/philippines/education-training",
    f"{_BASE_URL}/philippines/arts-entertainment",
    f"{_BASE_URL}/philippines/sports",
    f"{_BASE_URL}/philippines/music",
]

_MAX_PAGES = 20  # safety cap per category URL


# ---------------------------------------------------------------------------
# Fetch helper
# ---------------------------------------------------------------------------

def _fetch_html(url: str) -> str:
    from scrapling.fetchers import StealthyFetcher
    try:
        page = StealthyFetcher.fetch(
            url,
            headless=True,
            solve_cloudflare=True,
            network_idle=True,
        )
        return page.html_content or ""
    except Exception as exc:
        logger.error("EventAlways: fetch failed %s: %s", url, exc)
        return ""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_date(s: str) -> datetime | None:
    """Parse YYYY-MM-DD from LD+JSON startDate / endDate."""
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s.strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=_MANILA_TZ)
    except ValueError:
        return None


def _extract_ld_json(html: str) -> dict:
    """Return the first schema.org Event object from LD+JSON script tags."""
    for match in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    ):
        try:
            data = json.loads(match.group(1))
        except Exception:
            continue
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@type") == "Event":
                    return item
        elif isinstance(data, dict) and data.get("@type") == "Event":
            return data
    return {}


def _float_or_none(val) -> float | None:
    try:
        return float(val) if val is not None else None
    except (ValueError, TypeError):
        return None


def _build_venue(location: dict, event_url: str) -> ScrapedVenue | None:
    name = (location.get("name") or "").strip()
    if not name:
        return None
    addr = location.get("address") or {}
    geo = location.get("geo") or {}
    return ScrapedVenue(
        name=name,
        address=(addr.get("streetAddress") or "").strip(),
        city=(addr.get("addressLocality") or "").strip(),
        country=(addr.get("addressCountry") or "Philippines").strip(),
        latitude=_float_or_none(geo.get("latitude")),
        longitude=_float_or_none(geo.get("longitude")),
        source_url=event_url,
    )


def _extract_price(soup: BeautifulSoup) -> str:
    el = soup.select_one("span.event-item-price, .price-display, .ticket-price")
    return el.get_text(strip=True) if el else ""


def _extract_category(soup: BeautifulSoup) -> str:
    el = soup.select_one("div.event-label span, .event-category span, span.event-type")
    return el.get_text(strip=True) if el else ""


def _extract_organizer(soup: BeautifulSoup) -> tuple[str, str, str, str]:
    """Return (name, source_url, description, external_id)."""
    link = soup.select_one("h3.organizer-name a, .organizer-name a")
    if not link:
        return "", "", "", ""

    name = link.get_text(strip=True)
    href = link.get("href", "")
    org_url = href if href.startswith("http") else f"{_BASE_URL}{href}"

    desc_el = soup.select_one("div.organizer-desc p, .organizer-description p")
    desc = (desc_el.get_text(strip=True) if desc_el else "")[:1000]

    # Numeric organizer ID from follow onclick handler
    external_id = ""
    for tag in soup.find_all(onclick=True):
        m = re.search(r"set_event_session\(['\"]follow['\"],\s*(\d+)\)", tag.get("onclick", ""))
        if m:
            external_id = m.group(1)
            break

    return name, org_url, desc, external_id


def _parse_listing_cards(html: str, source_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    cards = []
    for card in soup.select("div.result-block[data_id], div.result-block.map_evevent_list_item"):
        external_id = (card.get("data_id") or "").strip()
        link_el = card.select_one("h3.title a, h2.title a")
        if not link_el:
            continue

        name = link_el.get_text(strip=True)
        href = link_el.get("href", "")
        event_url = href if href.startswith("http") else f"{_BASE_URL}{href}"

        img_el = card.select_one("img.lazy, img[data-src]")
        image_url = (img_el.get("data-src") or img_el.get("src") or "") if img_el else ""

        price_el = card.select_one("span.event-item-price")
        price = price_el.get_text(strip=True) if price_el else ""

        cat_el = card.select_one("div.event-label span, .event-category span")
        category = cat_el.get_text(strip=True) if cat_el else ""

        # Date: day/month/year split across sub-elements
        starts_at_raw = ""
        date_block = card.select_one("div.result-month")
        if date_block:
            day_el = date_block.select_one(".result-time-date")
            mon_el = date_block.select_one(".result-time-month")
            yr_el = date_block.select_one(".result-time-year")
            day = day_el.get_text(strip=True) if day_el else ""
            mon = mon_el.get_text(strip=True) if mon_el else ""
            yr = yr_el.get_text(strip=True) if yr_el else ""
            if day and mon and yr:
                try:
                    dt = datetime.strptime(f"{day} {mon} {yr}", "%d %b %Y")
                    starts_at_raw = dt.strftime("%Y-%m-%d")
                except ValueError:
                    pass

        cards.append({
            "external_id": external_id,
            "name": name,
            "url": event_url,
            "image_url": image_url,
            "price": price,
            "category": category,
            "starts_at_raw": starts_at_raw,
            "source_url": source_url,
        })
    return cards


def _has_next_page(html: str, current_page: int) -> bool:
    soup = BeautifulSoup(html, "lxml")
    next_href = f"?page={current_page + 1}"
    return bool(soup.select_one(f'div.pagination a[href="{next_href}"], .pagination a[href="{next_href}"]'))


def _build_event_from_detail(
    html: str, url: str, card: dict
) -> tuple[ScrapedEvent | None, ScrapedOrganizer | None]:
    soup = BeautifulSoup(html, "lxml")
    ld = _extract_ld_json(html)

    name = (ld.get("name") or card.get("name") or "").strip()
    if not name:
        return None, None

    description = (ld.get("description") or "").strip()[:5000]
    starts_at = _parse_date(ld.get("startDate") or card.get("starts_at_raw") or "")
    ends_at = _parse_date(ld.get("endDate") or "")
    image_url = (ld.get("image") or card.get("image_url") or "").strip()
    price = _extract_price(soup) or card.get("price", "")
    category = _extract_category(soup) or card.get("category", "")

    venue = _build_venue(ld.get("location") or {}, url)

    org_name, org_url, org_desc, org_ext_id = _extract_organizer(soup)

    event = ScrapedEvent(
        name=name,
        description=description,
        starts_at=starts_at,
        ends_at=ends_at,
        url=url,
        image_url=image_url,
        price=price,
        category=category,
        external_id=card.get("external_id", ""),
        source_url=card.get("source_url", _SOURCE_URL),
        organizer=org_name[:255],
        organizer_url=org_url,
        venue=venue,
    )

    organizer = None
    if org_name:
        organizer = ScrapedOrganizer(
            name=org_name,
            external_id=org_ext_id,
            source_url=org_url,
            description=org_desc,
        )

    return event, organizer


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

def _collect_all_cards() -> dict[str, dict]:
    """Paginate all category URLs and return deduped cards keyed by external_id."""
    all_cards: dict[str, dict] = {}
    for base_url in _CATEGORY_URLS:
        page_num = 1
        while page_num <= _MAX_PAGES:
            url = base_url if page_num == 1 else f"{base_url}?page={page_num}"
            logger.info("EventAlways: loading %s", url)
            html = _fetch_html(url)
            if not html or "Just a moment" in html:
                logger.warning("EventAlways: blocked or empty at %s — skipping", url)
                break
            cards = _parse_listing_cards(html, base_url)
            for card in cards:
                key = card["external_id"] or card["url"]
                if key and key not in all_cards:
                    all_cards[key] = card
            if not _has_next_page(html, page_num):
                break
            page_num += 1
    logger.info("EventAlways: %d unique event cards collected", len(all_cards))
    return all_cards


class EventAlwaysScraper(BaseScraper):
    source = "eventalways"

    def _scrape_detail(self, card: dict) -> tuple[ScrapedEvent | None, ScrapedOrganizer | None]:
        html = _fetch_html(card["url"])
        if not html or "Just a moment" in html:
            logger.warning("EventAlways: blocked on detail page %s", card["url"])
            return None, None
        return _build_event_from_detail(html, card["url"], card)

    def fetch(self) -> Iterable[ScrapedEvent]:
        for card in _collect_all_cards().values():
            event, _ = self._scrape_detail(card)
            if event:
                yield event

    def run(self, **_kwargs) -> dict:
        cards = _collect_all_cards()
        events: list[ScrapedEvent] = []
        organizers: dict[str, ScrapedOrganizer] = {}

        for card in cards.values():
            event, organizer = self._scrape_detail(card)
            if event:
                events.append(event)
            if organizer and organizer.name not in organizers:
                organizers[organizer.name] = organizer

        logger.info(
            "EventAlways: %d events, %d organizers to save",
            len(events),
            len(organizers),
        )
        events_result = save_events(self.source, events)
        organizers_result = save_organizers(self.source, list(organizers.values()))
        return {
            **events_result,
            "organizers_created": organizers_result["created"],
            "organizers_updated": organizers_result["updated"],
        }
