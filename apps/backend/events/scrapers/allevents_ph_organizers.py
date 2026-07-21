"""AllEvents.in organizer scraper — two-phase enrichment.

Phase 1: Visit each scraped allevents_in event detail page to extract the
         "Host Details" org URL and name. Updates Event.organizer /
         Event.organizer_url in-place for events that are still blank.

Phase 2: Visit each unique org profile page (/org/<slug>/<id>) and extract
         full contact details. Persists ScrapedOrganizer records via
         save_organizers.

Run with:
    manage.py scrape allevents_in_organizers
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Iterable

from bs4 import BeautifulSoup

from .proxy_manager import get_proxy_enabled, get_proxy_session
from .base import BaseScraper, ScrapedOrganizer, save_organizers

logger = logging.getLogger(__name__)

_BASE = "https://allevents.in"


def _fetch_html(url: str, proxy: str | None = None) -> str:
    from scrapling.fetchers import StealthyFetcher

    fetch_timeout = 90  # seconds per URL before giving up on Cloudflare

    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(
            StealthyFetcher.fetch,
            url,
            headless=True,
            solve_cloudflare=True,
            network_idle=True,
            proxy=proxy,
        )
        try:
            page = future.result(timeout=fetch_timeout)
        except FuturesTimeoutError:
            logger.warning("Cloudflare solve timed out after %ss for %s — skipping", fetch_timeout, url)
            future.cancel()
            raise RuntimeError(f"Cloudflare solve timed out for {url}")
    html = page.html_content or ""
    if "Just a moment" in html:
        raise RuntimeError(f"Cloudflare blocked {url}")
    return html


def _extract_org_from_event_page(html: str) -> tuple[str, str]:
    """Return (org_name, org_url) from an event detail page, or ('', '')."""
    soup = BeautifulSoup(html, "lxml")

    # Find any <a> that links to an /org/ profile — this is the host section link.
    a = soup.select_one('a[href*="/org/"]')
    if not a:
        return "", ""

    href = a["href"].strip()
    org_url = href if href.startswith("http") else f"{_BASE}{href}"

    # Prefer visible text; fall back to img alt attribute.
    name = a.get_text(strip=True)
    if not name:
        img = a.find("img")
        name = (img.get("alt") or "").strip() if img else ""

    return name, org_url


def _extract_org_profile(html: str, org_url: str) -> ScrapedOrganizer | None:
    """Parse an org profile page and return a ScrapedOrganizer, or None on failure."""
    soup = BeautifulSoup(html, "lxml")

    # Name: try common heading selectors, then fall back to the first <h1>.
    name = ""
    for sel in [".org-name", ".organizer-name", ".org-title", "h1"]:
        el = soup.select_one(sel)
        if el:
            name = el.get_text(strip=True)
            if name:
                break
    if not name:
        return None

    # Description / bio.
    description = ""
    for sel in [".org-description", ".organizer-about", ".about-text", ".bio", ".description"]:
        el = soup.select_one(sel)
        if el:
            description = el.get_text(strip=True)
            if description:
                break

    # Location (city).
    city = ""
    for sel in [".org-city", ".organizer-location", ".city"]:
        el = soup.select_one(sel)
        if el:
            city = el.get_text(strip=True)
            if city:
                break

    # External website — any outbound link that is not allevents.in or a social network.
    _social = re.compile(r"facebook\.com|instagram\.com|twitter\.com|x\.com|linkedin\.com", re.I)
    website = ""
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("http") and "allevents.in" not in href and not _social.search(href):
            website = href
            break

    # Social links.
    facebook_url = ""
    instagram_url = ""
    for a in soup.find_all("a", href=re.compile(r"facebook\.com/", re.I)):
        facebook_url = a["href"].strip()
        break
    for a in soup.find_all("a", href=re.compile(r"instagram\.com/", re.I)):
        instagram_url = a["href"].strip()
        break

    # external_id: last path segment when it is numeric (/org/<slug>/<id>).
    parts = org_url.rstrip("/").split("/")
    external_id = parts[-1] if parts and parts[-1].isdigit() else ""

    return ScrapedOrganizer(
        name=name,
        website=website,
        description=description,
        city=city,
        country="PH",
        facebook_url=facebook_url,
        instagram_url=instagram_url,
        external_id=external_id,
        source_url=org_url,
    )


class AllEventsPHOrganizersScraper(BaseScraper):
    source = "allevents_in"

    def fetch(self) -> Iterable[ScrapedOrganizer]:
        # Not used — run() orchestrates the two-phase logic directly.
        return iter([])

    def run(self, **_kwargs) -> dict:  # type: ignore[override]
        from events.models import Event

        _proxy_url = None
        if get_proxy_enabled():
            try:
                _sess = get_proxy_session()
                _proxy_url = _sess.proxies.get("https") or _sess.proxies.get("http")
            except Exception:
                pass

        # ── Phase 1: collect org URLs from event detail pages ─────────────────
        events_qs = list(
            Event.objects.filter(source="allevents_in", organizer_url="")
            .exclude(url="")
            .order_by("id")
        )
        total = len(events_qs)
        logger.info("Phase 1: enriching %d events with organizer info", total)

        org_urls: dict[str, str] = {}  # org_url -> org_name (first seen)

        for i, event in enumerate(events_qs, 1):
            logger.info("  [%d/%d] %s", i, total, event.url)
            try:
                html = _fetch_html(event.url, proxy=_proxy_url)
                org_name, org_url = _extract_org_from_event_page(html)
                if org_url:
                    Event.objects.filter(pk=event.pk).update(
                        organizer=org_name,
                        organizer_url=org_url,
                    )
                    org_urls.setdefault(org_url, org_name)
                    logger.info("    → %s", org_url)
                else:
                    logger.warning("    → no org link found on page")
            except Exception as exc:
                logger.error("    error: %s", exc)

        logger.info(
            "Phase 1 done: %d events updated, %d unique orgs found",
            total,
            len(org_urls),
        )

        # ── Phase 2: scrape each unique org profile page ───────────────────────
        logger.info("Phase 2: scraping %d org profiles", len(org_urls))

        organizers: list[ScrapedOrganizer] = []
        for org_url, fallback_name in org_urls.items():
            logger.info("  Org: %s", org_url)
            try:
                html = _fetch_html(org_url, proxy=_proxy_url)
                org = _extract_org_profile(html, org_url)
                if org:
                    organizers.append(org)
                    logger.info("    → %s", org.name)
                else:
                    # Minimal record using what we already know.
                    parts = org_url.rstrip("/").split("/")
                    external_id = parts[-1] if parts[-1].isdigit() else ""
                    slug_name = parts[-2].replace("-", " ").title() if len(parts) >= 2 else ""
                    organizers.append(ScrapedOrganizer(
                        name=fallback_name or slug_name or "Unknown",
                        external_id=external_id,
                        source_url=org_url,
                        country="PH",
                    ))
                    logger.warning("    → used fallback name: %s", fallback_name or slug_name)
            except Exception as exc:
                logger.error("    error scraping org profile: %s", exc)

        logger.info("Phase 2 done: %d org records to persist", len(organizers))
        return save_organizers(self.source, organizers)
