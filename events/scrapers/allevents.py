"""AllEvents.in scraper for Cagayan de Oro events.

Uses Playwright (sync API) to bypass Cloudflare's managed JS challenge and
intercepts the AJAX JSON response that allevents.in uses to populate event
cards. Falls back to DOM parsing if no JSON intercept is captured.

Run:
    python manage.py scrape allevents_cdo
"""
from __future__ import annotations

import re
from datetime import datetime
from datetime import timezone as dt_timezone
from typing import Iterable

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from .base import BaseScraper, ScrapedEvent, ScrapedVenue

BASE_URL = "https://allevents.in/cagayan-de-oro/all"

# CDO events are in Philippine Standard Time (UTC+8).
# We store datetimes as UTC in Django (USE_TZ=True), so unix timestamps are
# converted directly; string dates without tz are assumed UTC+8 and shifted.
from datetime import timedelta
_PHT = dt_timezone(timedelta(hours=8))


class AllEventsCDOScraper(BaseScraper):
    source = "allevents_cdo"

    def fetch(self) -> Iterable[ScrapedEvent]:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            Stealth().use_sync(page)  # Hide automation signals from Cloudflare

            intercepted: list[object] = []

            def _on_response(response):
                if "allevents.in" not in response.url:
                    return
                if response.status != 200:
                    return
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                try:
                    intercepted.append(response.json())
                except Exception:
                    pass

            page.on("response", _on_response)
            # Use "load" — "networkidle" never fires on Cloudflare-protected pages
            # because the CF challenge script keeps polling indefinitely.
            page.goto(BASE_URL, wait_until="load", timeout=90_000)
            # Give Cloudflare's JS challenge time to complete and redirect
            page.wait_for_timeout(8_000)

            # Scroll and paginate to load more events
            for _ in range(6):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2_500)
                btn = page.query_selector("text=Load More") or page.query_selector(
                    "button:has-text('more')"
                )
                if btn:
                    btn.click()
                    page.wait_for_timeout(2_500)

            html = page.content()
            browser.close()

        # Primary: parse intercepted AJAX JSON payloads
        events = list(_parse_json_payloads(intercepted))
        # Fallback: parse rendered HTML
        if not events:
            events = list(_parse_html(html))

        yield from events


# ---------------------------------------------------------------------------
# JSON payload parsing
# ---------------------------------------------------------------------------

def _parse_json_payloads(payloads: list) -> Iterable[ScrapedEvent]:
    for payload in payloads:
        items = (
            payload.get("data")
            or payload.get("events")
            or payload.get("items")
            or payload.get("results")
            or (payload if isinstance(payload, list) else None)
        )
        if not items:
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            ev = _item_to_event(item)
            if ev:
                yield ev


def _item_to_event(item: dict) -> ScrapedEvent | None:
    name = (
        item.get("name")
        or item.get("title")
        or item.get("event_name")
        or item.get("eventname")
    )
    if not name:
        return None

    event_url = item.get("url") or item.get("event_url") or item.get("link") or ""
    external_id = _extract_id(item, event_url)

    starts_at = _parse_dt(
        item.get("start_time") or item.get("start_date") or item.get("startDate") or item.get("start")
    )
    ends_at = _parse_dt(
        item.get("end_time") or item.get("end_date") or item.get("endDate") or item.get("end")
    )

    image_url = (
        item.get("banner")
        or item.get("image")
        or item.get("thumbnail")
        or item.get("pic")
        or ""
    )
    price = str(item.get("ticket_price") or item.get("price") or item.get("cost") or "")
    category = item.get("category") or item.get("type") or item.get("cat") or ""
    description = item.get("description") or item.get("desc") or ""

    venue = _extract_venue(item)

    return ScrapedEvent(
        name=name,
        description=description,
        starts_at=starts_at,
        ends_at=ends_at,
        url=event_url,
        image_url=image_url,
        price=price,
        category=category,
        external_id=external_id,
        source_url=BASE_URL,
        venue=venue,
    )


def _extract_venue(item: dict) -> ScrapedVenue | None:
    venue_data = item.get("venue") or {}
    if isinstance(venue_data, str):
        name = venue_data
        address = ""
    else:
        name = venue_data.get("name") or item.get("venue_name") or item.get("location_name") or ""
        address = venue_data.get("address") or item.get("venue_address") or item.get("address") or ""
    if not name:
        return None
    return ScrapedVenue(
        name=name,
        address=address,
        city="Cagayan de Oro",
        country="Philippines",
    )


def _extract_id(item: dict, url: str) -> str:
    id_val = item.get("id") or item.get("event_id") or item.get("eid") or item.get("eventid")
    if id_val:
        return str(id_val)
    m = re.search(r"/(\d+)(?:[/?#]|$)", url)
    return m.group(1) if m else ""


def _parse_dt(raw) -> datetime | None:
    if raw is None:
        return None
    # Unix timestamp (int or float)
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=dt_timezone.utc)
    s = str(raw).strip()
    if not s:
        return None
    # Try ISO formats with and without tz suffix
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
                # Assume Philippine Standard Time, convert to UTC
                dt = dt.replace(tzinfo=_PHT).astimezone(dt_timezone.utc)
            return dt
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# HTML fallback
# ---------------------------------------------------------------------------

def _parse_html(html: str) -> Iterable[ScrapedEvent]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    cards = (
        soup.select("li.event-item")
        or soup.select("div.event-item")
        or soup.select("[class*='event-card']")
        or soup.select("article[class*='event']")
        or soup.select("[data-eid]")
    )

    for card in cards:
        name_el = (
            card.select_one("[class*='title']")
            or card.select_one("h2")
            or card.select_one("h3")
        )
        name = name_el.get_text(strip=True) if name_el else None
        if not name:
            continue

        link_el = card.select_one("a[href*='/e/']") or card.select_one("a[href]")
        event_url = link_el["href"] if link_el else ""
        if event_url and event_url.startswith("/"):
            event_url = "https://allevents.in" + event_url

        external_id = card.get("data-eid") or ""
        if not external_id:
            m = re.search(r"/(\d+)(?:[/?#]|$)", event_url)
            external_id = m.group(1) if m else ""

        date_el = (
            card.select_one("time")
            or card.select_one("[class*='date']")
            or card.select_one("[class*='time']")
        )
        raw_date = None
        if date_el:
            raw_date = date_el.get("datetime") or date_el.get_text(strip=True)
        starts_at = _parse_dt(raw_date)

        img_el = card.select_one("img")
        image_url = ""
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src") or ""

        venue_el = (
            card.select_one("[class*='venue']")
            or card.select_one("[class*='location']")
        )
        venue_name = venue_el.get_text(strip=True) if venue_el else None
        venue = (
            ScrapedVenue(
                name=venue_name,
                city="Cagayan de Oro",
                country="Philippines",
            )
            if venue_name
            else None
        )

        price_el = card.select_one("[class*='price']") or card.select_one("[class*='ticket']")
        price = price_el.get_text(strip=True) if price_el else ""

        yield ScrapedEvent(
            name=name,
            starts_at=starts_at,
            url=event_url,
            image_url=image_url,
            price=price,
            external_id=external_id,
            source_url=BASE_URL,
            venue=venue,
        )
