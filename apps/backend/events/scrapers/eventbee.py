"""Scraper for Eventbee events (Philippines).

Discovery approach — no Playwright needed:
  POST https://www.eventbee.com/search!searchResult with PH-specific
  search terms and parse the HTML fragment response.  The server-side
  browse/filter pages return "Sorry, this request cannot be processed"
  regardless of country param, so the AJAX search endpoint is the only
  reliable discovery path.

Each result card provides: name, date/time, venue name + address + city
+ country, event URL, and eid.  Event detail pages are Angular-rendered
and require JS execution; description/price/organizer are unavailable
without a real browser, so those fields are left empty.

Deduplicates by eid across search terms.  Filters to Philippines-only
events by checking the country field in the search result card.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .proxy_manager import get_session
from .base import BaseScraper, ScrapedEvent, ScrapedVenue, save_events

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; EventScraper/1.0)",
    "Referer": "https://www.eventbee.com/search",
    "Origin": "https://www.eventbee.com",
    "X-Requested-With": "XMLHttpRequest",
}
_TIMEOUT = 25
_SEARCH_URL = "https://www.eventbee.com/search!searchResult"
_SOURCE_URL = "https://www.eventbee.com/search?q=philippines"
_NOPIC_URL = "https://d10sjcptbl6vkd.cloudfront.net/images/home/nopic.gif"
_TZ = ZoneInfo("Asia/Manila")

# Terms that reliably surface PH events; overlap is handled by eid dedup.
_SEARCH_TERMS = ["manila", "philippines"]


def _parse_date(raw: str) -> datetime | None:
    if not raw:
        return None
    cleaned = re.sub(r"\s+", " ", raw).strip()
    for fmt in ("%A, %B %d, %Y, %I:%M %p", "%A, %B %d, %Y, %H:%M"):
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=_TZ)
        except ValueError:
            continue
    logger.debug("Eventbee: could not parse date %r", cleaned)
    return None


def _parse_venue_tag(p_tag) -> tuple[str, str, str, str]:
    """Extract (venue_name, address, city, country) from the venue <p> element."""
    if not p_tag:
        return "", "", "", ""
    parts = [
        ln.strip().rstrip(",")
        for ln in p_tag.get_text(separator="\n").splitlines()
        if ln.strip().rstrip(",")
    ]
    if not parts:
        return "", "", "", ""
    country = parts[-1]
    city = parts[-2] if len(parts) >= 2 else ""
    venue_name = parts[0] if len(parts) >= 3 else ""
    address = ", ".join(parts[1:-2]) if len(parts) > 3 else ""
    return venue_name, address, city, country


class EventbeeScraper(BaseScraper):
    source = "eventbee"

    def _search(self, term: str) -> list[dict]:
        try:
            r = get_session().post(
                _SEARCH_URL,
                headers=_HEADERS,
                data={"searchcontent": term},
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
        except Exception as exc:
            logger.error("Eventbee: search %r failed: %s", term, exc)
            return []
        soup = BeautifulSoup(r.text, "lxml")
        rows = []
        for tr in soup.select("tr.edata"):
            a = tr.find("a", href=re.compile(r"\?eid=\d+"))
            if not a:
                continue
            img_tag = tr.find("img")
            date_p = tr.find("p", class_="mb-1")
            venue_p = tr.find("p", class_="mb-0")
            eid_m = re.search(r"eid=(\d+)", a["href"])
            img_src = img_tag.get("src", "") if img_tag else ""
            rows.append({
                "eid": eid_m.group(1) if eid_m else "",
                "name": a.get_text(strip=True),
                "url": a["href"],
                "date_raw": date_p.get_text(strip=True) if date_p else "",
                "venue_p": venue_p,
                "img": img_src if img_src != _NOPIC_URL else "",
            })
        return rows

    def fetch(self):
        seen: set[str] = set()
        for term in _SEARCH_TERMS:
            for row in self._search(term):
                eid = row["eid"]
                if not eid or eid in seen:
                    continue
                venue_name, address, city, country = _parse_venue_tag(row["venue_p"])
                # Skip events not in the Philippines
                if "Philippines" not in country:
                    continue
                seen.add(eid)
                venue = None
                if venue_name:
                    venue = ScrapedVenue(
                        name=venue_name,
                        address=address,
                        city=city,
                        country=country,
                        source_url=row["url"],
                    )
                yield ScrapedEvent(
                    name=row["name"],
                    starts_at=_parse_date(row["date_raw"]),
                    url=row["url"],
                    image_url=row["img"],
                    external_id=eid,
                    source_url=_SOURCE_URL,
                    venue=venue,
                )

    def run(self, **_kwargs) -> dict:
        events = list(self.fetch())
        logger.info("Eventbee: %d PH events", len(events))
        return save_events(self.source, events)
