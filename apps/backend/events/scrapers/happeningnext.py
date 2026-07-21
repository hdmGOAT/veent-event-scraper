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

import logging
import re
from dataclasses import replace
from datetime import datetime, timezone as dt_timezone, timedelta
from typing import Iterable

from .proxy_manager import get_proxy_enabled, get_proxy_session
from .base import BaseScraper, ScrapedEvent, ScrapedOrganizer, ScrapedVenue, save_organizers

logger = logging.getLogger(__name__)

BASE_URL = "https://happeningnext.com/cagayan%2Bde%2Boro"
_PHT = dt_timezone(timedelta(hours=8))


class HappeningNextCDOScraper(BaseScraper):
    source = "happeningnext_cdo"

    def __init__(self):
        self._scraped_organizers: list[ScrapedOrganizer] = []

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
                ev, org = _enrich_with_detail(page, ev)
                collected.append(ev)
                if org:
                    self._scraped_organizers.append(org)

        _proxy_url = None
        if get_proxy_enabled():
            try:
                _sess = get_proxy_session()
                _proxy_url = _sess.proxies.get("https") or _sess.proxies.get("http")
            except Exception:
                pass

        StealthyFetcher.fetch(
            BASE_URL,
            headless=True,
            network_idle=True,
            solve_cloudflare=True,
            page_action=_scrape_all,
            proxy=_proxy_url,
            timeout=60000,
            retries=2,
        )

        yield from collected

    def run(self, **_kwargs) -> dict:
        result = super().run()
        org_result = save_organizers(self.source, self._scraped_organizers)
        result["organizers_created"] = org_result["created"]
        result["organizers_updated"] = org_result["updated"]
        return result


# ---------------------------------------------------------------------------
# Detail-page enrichment (organizer)
# ---------------------------------------------------------------------------

def _enrich_with_detail(page, ev: ScrapedEvent) -> tuple[ScrapedEvent, ScrapedOrganizer | None]:
    if not ev.url:
        return ev, None
    from bs4 import BeautifulSoup
    try:
        page.goto(ev.url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(1_500)
        soup = BeautifulSoup(_page_html(page), "lxml")
        name, url = _extract_organizer(soup)
        if name:
            ev = replace(ev, organizer=name, organizer_url=url)
            fb_url = url if "facebook.com" in url else ""
            org = ScrapedOrganizer(
                name=name,
                facebook_url=fb_url,
                external_id=_fb_username(url),
                source_url=ev.url,
            )
            return ev, org
    except Exception:
        pass
    return ev, None


def _extract_organizer(soup) -> tuple[str, str]:
    org_el = soup.select_one(".ep-organizer-name")
    if not org_el:
        return "", ""
    name = org_el.get_text(strip=True)
    # Case 1: the element itself is a link
    if org_el.name == "a":
        return name, org_el.get("href", "")
    # Case 2: name is wrapped in a parent <a>
    parent_a = org_el.find_parent("a")
    if parent_a:
        return name, parent_a.get("href", "")
    # Case 3: .ep-organizer container has a direct child link
    container = soup.select_one(".ep-organizer")
    if container:
        link = container.find("a", href=True)
        if link:
            return name, link["href"]
    # Case 4: any link whose href contains /org/ (allevents.in organizer path)
    org_link = soup.select_one("a[href*='/org/']")
    if org_link:
        return name, org_link.get("href", "")
    # Case 5: happeningnext.com uses Facebook Graph API for organizer avatars.
    # Extract the username and build a Facebook profile URL as the organizer link.
    # e.g. src="https://graph.facebook.com/karposmm/picture?..." → facebook.com/karposmm
    if container:
        img = container.find("img", src=True)
        if img:
            m = re.search(r"graph\.facebook\.com/([^/?]+)/picture", img["src"])
            if m:
                return name, f"https://www.facebook.com/{m.group(1)}"
    return name, ""


def _fb_username(url: str) -> str:
    m = re.search(r"facebook\.com/([^/?#]+)", url)
    return m.group(1) if m else ""


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
