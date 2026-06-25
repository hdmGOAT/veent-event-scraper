"""Scraper for TicketMelon events (Philippines).

Discovery approach — no Playwright needed:
  1. Fetch sitemap.xml → enumerate sitemap-event*.xml files.
  2. Collect all event URLs from the sitemaps (~476 events as of 2026-06).
  3. Fetch each event page concurrently and parse the server-side rendered
     __NEXT_DATA__ JSON blob embedded in every Next.js page.
  4. Filter for Philippines events via currency.code == "PHP".

The event page is Next.js SSR — __NEXT_DATA__.props.pageProps.event
contains the complete event object with name, HTML description,
ms-precision start/end times, venue (name + address + lat/lon),
image URLs, categories, and organizer profile. No authentication or
CSRF token required for page fetches.

The /api/events/* JSON endpoints return "Connected Fail" without a
valid session CSRF token, so direct API calls are not used.
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import urllib3
from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapedEvent, ScrapedVenue, save_events

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; EventScraper/1.0)",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_TIMEOUT = 25
_SITEMAP_URL = "https://www.ticketmelon.com/sitemap.xml"
_SOURCE_URL = "https://www.ticketmelon.com"
_MAX_WORKERS = 8


def _make_session() -> requests.Session:
    from .proxy_manager import get_session
    s = get_session()
    s.headers.update(_HEADERS)
    s.verify = False  # certifi bundle absent in this venv
    return s


def _ms_to_dt(ms: int, tz: ZoneInfo) -> datetime | None:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=tz)
    except (OSError, OverflowError, ValueError):
        return None


def _extract_city_country(address: str) -> tuple[str, str]:
    """Best-effort split of a comma-separated address into (city, country)."""
    parts = [p.strip() for p in address.split(",") if p.strip()]
    country = parts[-1] if parts else ""
    city = parts[-2] if len(parts) >= 2 else ""
    return city, country


def _organizer_website(contacts: list[dict]) -> str:
    for c in contacts or []:
        if c.get("type") == "website":
            addr = (c.get("address") or "").strip()
            if addr:
                return addr if addr.startswith("http") else f"https://{addr}"
    return ""


class TicketmelonScraper(BaseScraper):
    source = "ticketmelon"

    def _get_sitemap_event_urls(self, session: requests.Session) -> list[str]:
        try:
            r = session.get(_SITEMAP_URL, timeout=_TIMEOUT)
            r.raise_for_status()
        except Exception as exc:
            logger.error("Ticketmelon: sitemap index failed: %s", exc)
            return []
        sitemap_files = re.findall(r"<loc>([^<]+)</loc>", r.text)
        urls: list[str] = []
        for sm_url in sitemap_files:
            try:
                rs = session.get(sm_url, timeout=_TIMEOUT)
                rs.raise_for_status()
                urls.extend(re.findall(r"<loc>([^<]+)</loc>", rs.text))
            except Exception as exc:
                logger.warning("Ticketmelon: sitemap %s failed: %s", sm_url, exc)
        logger.info("Ticketmelon: %d event URLs from sitemaps", len(urls))
        return urls

    def _fetch_event_data(self, url: str, session: requests.Session) -> dict | None:
        try:
            r = session.get(url, timeout=_TIMEOUT)
            r.raise_for_status()
        except Exception as exc:
            logger.debug("Ticketmelon: page fetch failed %s: %s", url, exc)
            return None
        soup = BeautifulSoup(r.text, "lxml")
        nd_tag = soup.find("script", id="__NEXT_DATA__")
        if not nd_tag or not nd_tag.string:
            return None
        try:
            import json
            nd = json.loads(nd_tag.string)
            return nd.get("props", {}).get("pageProps", {}).get("event")
        except Exception as exc:
            logger.debug("Ticketmelon: JSON parse failed %s: %s", url, exc)
            return None

    def _to_scraped(self, ev: dict, url: str) -> ScrapedEvent | None:
        name = (ev.get("name") or "").strip()
        if not name:
            return None

        tz_str = (ev.get("timezone") or {}).get("country") or "Asia/Manila"
        try:
            tz = ZoneInfo(tz_str)
        except Exception:
            tz = ZoneInfo("Asia/Manila")

        start_ms = ev.get("show_starttime") or 0
        end_ms = ev.get("show_endtime") or 0
        starts_at = _ms_to_dt(start_ms, tz)
        ends_at = _ms_to_dt(end_ms, tz) if end_ms and end_ms > start_ms else None

        image_url = (ev.get("img_poster") or ev.get("img_banner") or "").strip()

        cats = ev.get("categories") or []
        category = cats[0] if cats else ""

        eo = ev.get("eo_profile") or {}
        organizer_name = (eo.get("name") or eo.get("company_name") or "").strip()
        organizer_url = _organizer_website(eo.get("contact") or [])

        venue_data = ev.get("venue") or {}
        venue = None
        venue_name = (venue_data.get("name") or "").strip()
        if venue_name:
            full_address = venue_data.get("address") or ""
            city, country = _extract_city_country(full_address)
            venue = ScrapedVenue(
                name=venue_name,
                address=full_address,
                city=city,
                country=country,
                latitude=venue_data.get("latitude"),
                longitude=venue_data.get("longitude"),
                source_url=url,
            )

        return ScrapedEvent(
            name=name,
            description=ev.get("description") or "",
            starts_at=starts_at,
            ends_at=ends_at,
            url=url,
            image_url=image_url,
            category=category,
            external_id=ev.get("event_id") or "",
            source_url=_SOURCE_URL,
            organizer=organizer_name,
            organizer_url=organizer_url,
            venue=venue,
        )

    def fetch(self):
        session = _make_session()
        urls = self._get_sitemap_event_urls(session)
        if not urls:
            return

        ph_events: list[tuple[dict, str]] = []

        def _worker(url: str):
            ev = self._fetch_event_data(url, session)
            if ev and (ev.get("currency") or {}).get("code") == "PHP":
                return ev, url
            return None

        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {pool.submit(_worker, url): url for url in urls}
            done = 0
            total = len(futures)
            for future in as_completed(futures):
                done += 1
                if done % 50 == 0:
                    logger.debug("Ticketmelon: checked %d/%d pages", done, total)
                result = future.result()
                if result:
                    ph_events.append(result)

        logger.info("Ticketmelon: %d PH events found in %d pages", len(ph_events), total)
        for ev, url in ph_events:
            scraped = self._to_scraped(ev, url)
            if scraped:
                yield scraped

    def run(self, **_kwargs) -> dict:
        events = list(self.fetch())
        logger.info("Ticketmelon: saving %d PH events", len(events))
        return save_events(self.source, events)
