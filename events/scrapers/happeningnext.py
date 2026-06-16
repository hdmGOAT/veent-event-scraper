"""HappeningNext CDO event scraper.

Fetches upcoming events in Cagayan de Oro from happeningnext.com using
Scrapling's StealthyFetcher (Camoufox-based browser that auto-solves
Cloudflare's non-interactive Turnstile).

Strategy:
  1. Open the listing page → Cloudflare solved once.
  2. Inside the same browser session (page_action), navigate to each event
     detail page to extract organizer info — no CF re-solve needed.

Run:
    python manage.py scrape happeningnext_cdo
"""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone as dt_timezone, timedelta
from typing import Iterable

from .base import BaseScraper, ScrapedEvent, ScrapedVenue

BASE_URL = "https://happeningnext.com/cagayan%2Bde%2Boro"
_PHT = dt_timezone(timedelta(hours=8))


class HappeningNextCDOScraper(BaseScraper):
    source = "happeningnext_cdo"

    def fetch(self) -> Iterable[ScrapedEvent]:
        from scrapling.fetchers import StealthyFetcher

        collected: list[ScrapedEvent] = []

        def _scrape_all(page) -> None:
            """Runs inside the live browser session after CF is solved."""
            from bs4 import BeautifulSoup

            listing_html = _page_html(page)
            soup = BeautifulSoup(listing_html, "lxml")
            events = [ev for card in soup.select(".event-item.card") if (ev := _card_to_event(card))]

            for ev in events:
                ev = _enrich_with_detail(page, ev)
                collected.append(ev)

        StealthyFetcher.fetch(
            BASE_URL,
            headless=True,
            network_idle=True,
            timeout=90_000,
            solve_cloudflare=True,
            page_action=_scrape_all,
        )

        yield from collected


# ---------------------------------------------------------------------------
# Detail-page enrichment (organizer)
# ---------------------------------------------------------------------------

def _enrich_with_detail(page, ev: ScrapedEvent) -> ScrapedEvent:
    if not ev.url:
        return ev
    from bs4 import BeautifulSoup
    try:
        page.goto(ev.url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(1_500)
        soup = BeautifulSoup(_page_html(page), "lxml")
        org_el = soup.select_one(".ep-organizer-name")
        if org_el:
            ev = replace(ev, organizer=org_el.get_text(strip=True))
    except Exception:
        pass
    return ev


def _page_html(page) -> str:
    html = page.content()
    return html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html


# ---------------------------------------------------------------------------
# Listing-page parsers
# ---------------------------------------------------------------------------

def _card_to_event(card) -> ScrapedEvent | None:
    title_el = card.select_one("h3") or card.select_one(".card-body a")
    name = title_el.get_text(strip=True) if title_el else None
    if not name:
        return None

    link_el = card.select_one(".card-body a[href]")
    url = link_el["href"] if link_el else ""

    return ScrapedEvent(
        name=name,
        starts_at=_parse_date(card),
        url=url,
        image_url=_extract_image(card),
        external_id=_extract_eid(url),
        source_url=BASE_URL,
        venue=_extract_venue(card),
    )


def _extract_eid(url: str) -> str:
    m = re.search(r"(eid[a-z0-9]+)", url)
    return m.group(1) if m else ""


def _parse_date(card) -> datetime | None:
    date_el = card.select_one("small.d-block") or card.select_one("[class*=text-sm]")
    if not date_el:
        return None
    raw = date_el.get_text(strip=True)
    for fmt in ("%d %b %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=_PHT).astimezone(dt_timezone.utc)
        except ValueError:
            continue
    return None


def _extract_image(card) -> str:
    banner = card.select_one(".banner-sec a")
    if not banner:
        return ""
    img = banner.get("data-background-image", "")
    if not img:
        style = banner.get("style", "")
        m = re.search(r"url\(['\"]?([^'\")\s]+)['\"]?\)", style)
        img = m.group(1) if m else ""
    return img.strip("\"'")


def _extract_venue(card) -> ScrapedVenue | None:
    venue_el = card.select_one("small.limit-1")
    name = venue_el.get_text(strip=True) if venue_el else ""
    if not name:
        return None
    return ScrapedVenue(
        name=name,
        city="Cagayan de Oro",
        country="Philippines",
    )
