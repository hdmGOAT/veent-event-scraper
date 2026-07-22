"""Scraper for TicketSpice event pages.

TicketSpice (a Webconnex product) is a white-label ticketing SaaS where
organizers publish pages at [organizer].ticketspice.com/[event-slug].
There is no public event directory and the Webconnex API requires auth.

Discovery (two-phase):
  1. Google SERP via StealthyFetcher (camoufox browser) — searches multiple
     queries and paginates through results to collect event URLs.
  2. Per-organizer sitemap.xml probe — each discovered subdomain is probed
     for a sitemap that may list all of that organizer's event slugs.

Fetching: plain requests + lxml (event pages are server-side rendered).
Parsing:  Open Graph meta tags → BeautifulSoup DOM fallbacks → text heuristics.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone as dt_timezone
from urllib.parse import urlparse, quote_plus, unquote

import requests
from bs4 import BeautifulSoup

from .proxy_manager import get_session, get_proxy_enabled, get_proxy_session
from .base import (
    BaseScraper,
    ScrapedEvent,
    ScrapedOrganizer,
    ScrapedVenue,
    save_events,
    save_organizers,
)

logger = logging.getLogger(__name__)

_SOURCE_URL = "https://www.ticketspice.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}
_TIMEOUT = 30
_DELAY = 1.5  # seconds between page requests

# Google queries — variety of terms broadens coverage across event types
_SEARCH_QUERIES = [
    "site:ticketspice.com event tickets 2026",
    "site:ticketspice.com festival fair registration 2026",
    "site:ticketspice.com concert show 2026",
    "site:ticketspice.com 2026 admission pass",
    "site:ticketspice.com Philippines",
    "site:ticketspice.com Asia event 2026",
]
# Google result pages to fetch per query (each page has ~10 results, start=N)
_GOOGLE_PAGES_PER_QUERY = 3
_GOOGLE_PAGE_SIZE = 10

# Date formats observed on TicketSpice pages
_DATE_FORMATS = [
    "%B %d, %Y",   # "October 18, 2026"
    "%b %d, %Y",   # "Oct 18, 2026"
    "%B %d %Y",    # "October 18 2026"
]
_UTC = dt_timezone.utc


# ---------------------------------------------------------------------------
# HTTP session (for event page fetching)
# ---------------------------------------------------------------------------

def _make_session() -> requests.Session:
    s = get_session()
    s.headers.update(_HEADERS)
    return s


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def _is_event_url(parsed) -> bool:
    """True for organizer-subdomain event pages, not marketing/signup pages."""
    host = parsed.netloc.lower()
    return (
        host.endswith(".ticketspice.com")
        and host not in ("www.ticketspice.com", "signup.ticketspice.com",
                         "help.ticketspice.com", "app.ticketspice.com")
        and len(parsed.path.strip("/")) > 0
    )


def _clean_url(url: str) -> str:
    """Strip tracking params and anchors from a TicketSpice event URL."""
    try:
        parsed = urlparse(url)
        # Drop query string (tracking params like _gl=) and fragment
        return f"https://{parsed.netloc}{parsed.path}".rstrip("/")
    except Exception:
        return url


# ---------------------------------------------------------------------------
# Discovery — Phase 1: Google SERP via StealthyFetcher
# ---------------------------------------------------------------------------

def _google_search_urls(queries: list[str], pages_per_query: int) -> set[str]:
    """Run Google queries via StealthyFetcher, one fresh browser session per page for reliability."""
    from scrapling.fetchers import StealthyFetcher

    _proxy_url = None
    if get_proxy_enabled():
        try:
            _sess = get_proxy_session()
            _proxy_url = _sess.proxies.get("https") or _sess.proxies.get("http")
        except Exception:
            pass

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
                    if ".ticketspice.com/" not in link:
                        continue
                    try:
                        parsed = urlparse(link)
                        if _is_event_url(parsed):
                            clean = _clean_url(link)
                            if clean not in found:
                                found.add(clean)
                                new_on_page += 1
                    except Exception:
                        pass

            try:
                StealthyFetcher.fetch(
                    search_url,
                    headless=True,
                    network_idle=False,
                    page_action=_collect,
                    proxy=_proxy_url,
                    timeout=60000,
                    retries=0,
                )
            except Exception as exc:
                logger.warning(
                    "TicketSpice: Google search error (query=%r page=%d): %s",
                    query, page_num, exc,
                )
                break  # Browser crashed — skip remaining pages for this query

            logger.debug(
                "TicketSpice Google: query=%r page=%d → %d new",
                query, page_num, new_on_page,
            )
            if new_on_page == 0:
                break  # No new results → stop paginating this query

    logger.info("TicketSpice: Google discovery → %d URLs", len(found))

    # Fallback: if Google returned nothing (CAPTCHA / browser failure), try the
    # DuckDuckGo HTML endpoint over plain requests (no proxy, no browser).
    if not found:
        logger.info("TicketSpice: Google returned 0 URLs — trying DuckDuckGo HTML fallback")
        found = _ddg_search_urls(queries)
        logger.info("TicketSpice: DuckDuckGo discovery → %d URLs", len(found))

    return found


_DDG_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_DDG_URL_RE = re.compile(r'([a-zA-Z0-9\-]+\.ticketspice\.com[^\s<"\'%&]{1,150})')


def _ddg_search_urls(queries: list[str]) -> set[str]:
    """DuckDuckGo HTML fallback: extract TicketSpice event URLs via plain requests."""
    session = requests.Session()
    session.headers.update({"User-Agent": _DDG_UA})

    found: set[str] = set()
    for query in queries:
        ddg_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            resp = session.get(ddg_url, timeout=_TIMEOUT)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("TicketSpice DDG: error for query=%r: %s", query, exc)
            continue

        for raw in _DDG_URL_RE.findall(resp.text):
            candidate = unquote(raw)
            url = candidate if candidate.startswith("http") else f"https://{candidate}"
            try:
                parsed = urlparse(url)
            except Exception:
                continue
            if _is_event_url(parsed):
                found.add(_clean_url(url))

        time.sleep(_DELAY)

    return found


# ---------------------------------------------------------------------------
# Discovery — Phase 2: organizer sitemap probing
# ---------------------------------------------------------------------------

def _probe_organizer_sitemap(subdomain: str, session: requests.Session) -> list[str]:
    """Check [organizer].ticketspice.com/sitemap.xml for event page slugs."""
    sitemap_url = f"https://{subdomain}.ticketspice.com/sitemap.xml"
    try:
        resp = session.get(sitemap_url, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return []
        locs = re.findall(r"<loc>([^<]+ticketspice\.com[^<]+)</loc>", resp.text)
        urls = []
        for loc in locs:
            loc = loc.strip()
            try:
                parsed = urlparse(loc)
                if _is_event_url(parsed):
                    urls.append(_clean_url(loc))
            except Exception:
                pass
        if urls:
            logger.info("TicketSpice: sitemap %s → %d extra event URLs", subdomain, len(urls))
        return urls
    except Exception:
        return []


def _discover_all_urls(session: requests.Session) -> list[str]:
    """Full two-phase discovery: Google SERP → organizer sitemap probing."""
    seed_urls = _google_search_urls(_SEARCH_QUERIES, _GOOGLE_PAGES_PER_QUERY)

    # Extract unique organizer subdomains from what we already found
    subdomains: set[str] = set()
    for url in seed_urls:
        try:
            host = urlparse(url).netloc
            sub = host.replace(".ticketspice.com", "")
            if sub:
                subdomains.add(sub)
        except Exception:
            pass

    # Probe each organizer's sitemap for additional event slugs
    all_urls: set[str] = set(seed_urls)
    for subdomain in sorted(subdomains):
        extra = _probe_organizer_sitemap(subdomain, session)
        for u in extra:
            all_urls.add(u)
        if extra:
            time.sleep(_DELAY)

    result = sorted(all_urls)
    logger.info("TicketSpice: %d total unique event URLs after sitemap probing", len(result))
    return result


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------

def _og(soup: BeautifulSoup, prop: str) -> str:
    tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
    return (tag.get("content") or "").strip() if tag else ""


def _event_name(soup: BeautifulSoup) -> str:
    name = _og(soup, "og:title")
    if not name:
        t = soup.find("title")
        name = t.get_text(strip=True) if t else ""
    if not name:
        h1 = soup.find("h1")
        name = h1.get_text(strip=True) if h1 else ""
    for suffix in (" | TicketSpice", " - TicketSpice", " | Tickets", " - Tickets", " | Webconnex"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.strip()


def _parse_date_raw(raw: str) -> datetime | None:
    raw = raw.strip().rstrip(",").strip()
    if not re.search(r"\d{4}", raw):
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=_UTC)
        except ValueError:
            continue
    return None


_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
    "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)
_MONTH_PAT = "|".join(_MONTH_NAMES)


def _parse_dates(text: str, fallback_year: int | None = None) -> tuple[datetime | None, datetime | None]:
    """Return (starts_at, ends_at) from page text.

    Pass 1 — date with explicit year:
      "October 18, 2026", "August 21-23, 2026", "August 21 - September 5, 2026"

    Pass 2 — yearless date (e.g. "Sunday, October 18 10am"):
      Uses fallback_year (typically extracted from the event title or current year).
    """
    text = re.sub(r"[–—]", "-", text)

    # --- Pass 1: date with explicit 4-digit year ---
    date_re = re.compile(
        r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s+)?"
        r"(\w+ \d{1,2})"           # "August 21" or "Aug 21"
        r"(?:\s*-\s*(\w+ )?\s*"    # optional: " - [Month] "
        r"(\d{1,2}))?"             # end day
        r",?\s*(\d{4})",           # ", 2026"
        re.IGNORECASE,
    )
    for m in date_re.finditer(text):
        year_str = m.group(4)
        year_int = int(year_str)
        if year_int < 2020 or year_int > 2040:
            continue  # skip spurious matches (phone numbers, zip-adjacent digits)

        start_part = m.group(1)
        mid_month = m.group(2)
        end_day = m.group(3)

        starts_at = _parse_date_raw(f"{start_part}, {year_str}")
        if not starts_at:
            continue

        ends_at = None
        if end_day:
            if mid_month:
                ends_at = _parse_date_raw(f"{mid_month.strip()} {end_day}, {year_str}")
            else:
                month = start_part.split()[0]
                ends_at = _parse_date_raw(f"{month} {end_day}, {year_str}")

        return starts_at, ends_at

    # --- Pass 2: yearless date — requires fallback_year ---
    if fallback_year:
        yearless_re = re.compile(
            r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s+)?"
            r"((?:" + _MONTH_PAT + r")\s+\d{1,2})"   # "October 18"
            r"(?:\s*-\s*(\d{1,2}))?",                  # optional "- 23" same-month range
            re.IGNORECASE,
        )
        for m in yearless_re.finditer(text):
            start_part = m.group(1)
            end_day = m.group(2)

            starts_at = _parse_date_raw(f"{start_part}, {fallback_year}")
            if not starts_at:
                continue

            ends_at = None
            if end_day:
                month = start_part.split()[0]
                ends_at = _parse_date_raw(f"{month} {end_day}, {fallback_year}")

            return starts_at, ends_at

    return None, None


def _extract_price(soup: BeautifulSoup) -> str:
    text = soup.get_text(" ")
    prices = []
    for p in re.findall(r"\$(\d+(?:\.\d{2})?)", text):
        try:
            v = float(p)
            if v >= 5.0:  # service/processing fees are typically < $5; real tickets are $5+
                prices.append(v)
        except ValueError:
            pass
    if prices:
        return f"${min(prices):.2f}"
    if re.search(r"\bfree\b", text, re.IGNORECASE):
        return "Free"
    return ""


def _extract_image(soup: BeautifulSoup) -> str:
    img_url = _og(soup, "og:image")
    if img_url:
        return img_url
    img = soup.find("img", src=re.compile(r"uploads\.webconnex\.com|webconnex"))
    return (img.get("src") or "").strip() if img else ""


def _extract_email(soup: BeautifulSoup) -> str:
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("mailto:"):
            return href[7:].split("?")[0].strip()
    m = re.search(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}", soup.get_text())
    return m.group(0) if m else ""


_SKIP_DOMAINS = frozenset([
    "ticketspice.com", "webconnex.com", "webconnex.io",
    "google.com", "google.co", "bing.com", "msn.com",
    "apple.com", "microsoft.com", "tiktok.com", "linkedin.com",
    "purchaseprotection.com",  # TicketSpice upsell — not the organizer's site
    "mapq.st", "maps.google.com",  # map embeds — not the organizer's site
])
_SOCIAL_DOMAINS = {
    "facebook.com": "facebook_url",
    "fb.com": "facebook_url",
    "instagram.com": "instagram_url",
    "twitter.com": None,   # not stored in schema
    "youtube.com": None,
}


def _extract_social_and_website(soup: BeautifulSoup) -> tuple[str, str, str]:
    """Return (website, facebook_url, instagram_url) from page links."""
    website = facebook_url = instagram_url = ""
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith("http"):
            continue
        netloc = urlparse(href).netloc.lower().lstrip("www.")

        # Social media
        for domain, field in _SOCIAL_DOMAINS.items():
            if netloc.endswith(domain):
                if field == "facebook_url" and not facebook_url:
                    facebook_url = href
                elif field == "instagram_url" and not instagram_url:
                    instagram_url = href
                break
        else:
            # External non-social website
            if not website and netloc and not any(netloc.endswith(d) for d in _SKIP_DOMAINS):
                parsed = urlparse(href)
                website = f"{parsed.scheme}://{parsed.netloc}"

        if website and facebook_url and instagram_url:
            break

    return website, facebook_url, instagram_url


def _extract_venue(page_text: str) -> ScrapedVenue | None:
    # Exclude 4-digit years as street numbers (e.g. "2026 Location Info...")
    addr_re = re.compile(
        r"(?<!\d)(?!20\d\d\b)\d{1,5}\s+[A-Z][\w\s.]+?"
        r"(?:Ave(?:nue)?|St(?:reet)?|Rd|Road|Blvd|Boulevard|Dr(?:ive)?|"
        r"Ln|Lane|Way|Circle|Cir|Pkwy|Parkway|Hwy|Highway)"
        r"[\w\s,.]+?\d{5}(?:\s*(?:US|USA))?",
        re.IGNORECASE,
    )
    m = addr_re.search(page_text)
    if not m:
        return None
    address = m.group(0).strip().rstrip(",")
    parts = [p.strip() for p in address.split(",")]
    city = ""
    for part in reversed(parts[:-1]):
        part_clean = re.sub(r"\s+[A-Z]{2}\s+\d{5}.*", "", part).strip()
        if part_clean and not part_clean.isdigit():
            city = part_clean
            break
    return ScrapedVenue(name="", address=address, city=city, country="US")


# ---------------------------------------------------------------------------
# Per-page parse
# ---------------------------------------------------------------------------

def _parse_page(soup: BeautifulSoup, url: str) -> tuple[ScrapedEvent | None, ScrapedOrganizer | None]:
    name = _event_name(soup)
    if not name:
        return None, None

    description = _og(soup, "og:description") or _og(soup, "description")
    image_url = _extract_image(soup)
    page_text = soup.get_text(" ", strip=True)
    # Extract year from event name or URL for yearless date fallback
    yr_m = re.search(r"\b(202[5-9]|20[3-9]\d)\b", name + " " + url)
    fallback_year = int(yr_m.group(1)) if yr_m else None
    starts_at, ends_at = _parse_dates(page_text, fallback_year=fallback_year)
    price = _extract_price(soup)
    venue = _extract_venue(page_text)

    parsed_url = urlparse(url)
    subdomain = parsed_url.netloc.replace(".ticketspice.com", "")
    organizer_name = subdomain.replace("-", " ").title()
    organizer_website, facebook_url, instagram_url = _extract_social_and_website(soup)
    organizer_email = _extract_email(soup)
    organizer_source_url = f"https://{parsed_url.netloc}"
    external_id = parsed_url.path.strip("/")

    event = ScrapedEvent(
        name=name,
        description=description,
        starts_at=starts_at,
        ends_at=ends_at,
        url=url,
        image_url=image_url,
        price=price,
        external_id=external_id,
        source_url=_SOURCE_URL,
        organizer=organizer_name,
        organizer_url=organizer_website or organizer_source_url,
        venue=venue,
    )

    organizer = ScrapedOrganizer(
        name=organizer_name,
        website=organizer_website,
        email=organizer_email,
        facebook_url=facebook_url,
        instagram_url=instagram_url,
        external_id=subdomain,
        source_url=organizer_source_url,
    )

    return event, organizer


# ---------------------------------------------------------------------------
# Main scraper class
# ---------------------------------------------------------------------------

def _fetch_page(url: str, session: requests.Session) -> BeautifulSoup | None:
    try:
        resp = session.get(url, timeout=_TIMEOUT, allow_redirects=True)
        if resp.status_code in (404, 410):
            logger.debug("TicketSpice: %s → %d (skip)", url, resp.status_code)
            return None
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except Exception as exc:
        logger.debug("TicketSpice: fetch failed %s: %s", url, exc)
        return None


class TicketSpiceScraper(BaseScraper):
    source = "ticketspice"

    def _collect(self) -> tuple[list[ScrapedEvent], list[ScrapedOrganizer]]:
        session = _make_session()
        urls = _discover_all_urls(session)
        if not urls:
            logger.warning("TicketSpice: no event URLs discovered — check network connectivity")
            return [], []

        events: list[ScrapedEvent] = []
        organizers: dict[str, ScrapedOrganizer] = {}

        for url in urls:
            soup = _fetch_page(url, session)
            if not soup:
                continue
            try:
                event, organizer = _parse_page(soup, url)
            except Exception as exc:
                logger.error("TicketSpice: parse error for %s: %s", url, exc)
                continue

            if not event:
                continue

            events.append(event)

            if organizer and organizer.external_id not in organizers:
                organizers[organizer.external_id] = organizer

            time.sleep(_DELAY)

        logger.info("TicketSpice: %d events, %d organizers", len(events), len(organizers))
        return events, list(organizers.values())

    def fetch(self):
        events, _ = self._collect()
        yield from events

    def run(self, **_kwargs) -> dict:
        events, organizers = self._collect()
        organizers_result = save_organizers(self.source, organizers)
        events_result = save_events(self.source, events)
        return {
            **events_result,
            "organizers_created": organizers_result["created"],
            "organizers_updated": organizers_result["updated"],
        }
