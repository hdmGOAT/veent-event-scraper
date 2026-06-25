"""AllEvents.in PH scraper — headless via scrapling solve_cloudflare, no browser window."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .proxy_manager import get_proxy_enabled, get_proxy_session
from .base import BaseScraper, ScrapedEvent, ScrapedVenue

logger = logging.getLogger(__name__)

_MANILA_TZ = ZoneInfo("Asia/Manila")

_CITIES = [
    {"slug": "manila", "city": "Manila"},
    # cebu / cebu-city both 404 on allevents.in — verify correct slug manually
    {"slug": "davao", "city": "Davao City"},
    {"slug": "cagayan-de-oro", "city": "Cagayan de Oro"},
]


def _parse_date(text: str) -> datetime | None:
    # Format: "Sat, 27 Jun, 2026 - 08:00 PM"
    text = text.strip()
    try:
        naive = datetime.strptime(text, "%a, %d %b, %Y - %I:%M %p")
        return naive.replace(tzinfo=_MANILA_TZ)
    except ValueError:
        pass
    # Fallback: date only, no time
    try:
        naive = datetime.strptime(text.split(" - ")[0].strip(), "%a, %d %b, %Y")
        return naive.replace(tzinfo=_MANILA_TZ)
    except ValueError:
        return None


def _parse_cards(html: str, city: dict) -> list[ScrapedEvent]:
    soup = BeautifulSoup(html, "lxml")
    events = []
    for card in soup.select("li.event-card"):
        eid = card.get("data-eid")
        link = card.get("data-link", "")
        if not eid or not link:
            continue

        title_el = card.select_one("div.title")
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            img = card.select_one("img.banner-img")
            title = (img.get("alt") or "").strip() if img else ""
        if not title:
            continue

        img = card.select_one("img.banner-img")
        image_url = (img.get("src") or "").strip() if img else ""

        date_el = card.select_one("div.date")
        starts_at = _parse_date(date_el.get_text(strip=True)) if date_el else None

        loc_el = card.select_one("div.location")
        venue_name = loc_el.get_text(strip=True) if loc_el else ""

        price_el = card.select_one("span.price")
        price = price_el.get_text(strip=True) if price_el else ""

        # Strip ref query param from URL for cleaner dedup
        clean_link = link.split("?")[0]

        venue = ScrapedVenue(name=venue_name, city=city["city"], country="PH") if venue_name else None

        events.append(ScrapedEvent(
            name=title,
            starts_at=starts_at,
            url=clean_link,
            image_url=image_url,
            price=price,
            external_id=eid,
            source_url=f"https://allevents.in/{city['slug']}/all",
            venue=venue,
        ))
    return events


class AllEventsPHScraper(BaseScraper):
    source = "allevents_in"

    def fetch(self) -> Iterable[ScrapedEvent]:
        from scrapling.fetchers import StealthyFetcher

        _proxy_url = None
        if get_proxy_enabled():
            try:
                _sess = get_proxy_session()
                _proxy_url = _sess.proxies.get("https") or _sess.proxies.get("http")
            except Exception:
                pass

        for city in _CITIES:
            url = f"https://allevents.in/{city['slug']}/all"
            logger.info("Fetching %s", url)
            try:
                page = StealthyFetcher.fetch(
                    url,
                    headless=True,
                    solve_cloudflare=True,
                    network_idle=True,
                    proxy=_proxy_url,
                )
                html = page.html_content or ""
                if "Just a moment" in html:
                    logger.warning("Cloudflare blocked %s — skipping", url)
                    continue
                events = _parse_cards(html, city)
                logger.info("  %s: %d events", city["city"], len(events))
                yield from events
            except Exception as exc:
                logger.error("Error scraping %s: %s", url, exc)
