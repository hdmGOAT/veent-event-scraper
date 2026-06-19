"""Facebook Events scraper.

Automates the same flow the veent-fb-scraper Chrome extension performs manually:
  1. Open a persistent browser session (cookies reused across runs → fewer logins).
  2. Log into Facebook with credentials from .env (FB_EMAIL / FB_PASSWORD).
  3. For every active SearchQuery where source='facebook_events':
       a. Navigate to https://www.facebook.com/events/search?q=<query>
       b. Scroll through results in a humanized way.
       c. Extract event cards (title, date, venue, URL, respondent count).
       d. Visit each event detail page to enrich: full date, description,
          organizer, city.
  4. Save via the shared save_events() pipeline and link events back to their
     SearchQuery row.

Credentials / config (.env):
    FB_EMAIL          Facebook account e-mail
    FB_PASSWORD       Facebook account password
    FB_USER_DATA_DIR  Path to persist browser session (default: ~/.cache/veent-fb-session)
    FB_HEADLESS       Set to "false" to run with a visible browser window (recommended
                      for Facebook — headless mode is more easily detected)

Run:
    python manage.py scrape facebook_events
"""
from __future__ import annotations

import os
import random
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Iterable

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from .base import BaseScraper, ScrapedEvent, ScrapedVenue, save_events

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FB_BASE = "https://www.facebook.com"
_SEARCH_URL = _FB_BASE + "/events/search?q={query}"
_EVENT_ID_RE = re.compile(r"facebook\.com/events/(\d+)", re.I)
_MIN_RESPONDENTS = 10

_PHT = dt_timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# Humanization helpers
# ---------------------------------------------------------------------------

def _pause(lo: float = 1.0, hi: float = 3.5) -> None:
    """Random pause to simulate reading or thinking."""
    time.sleep(random.uniform(lo, hi))


def _human_type(page, selector: str, text: str) -> None:
    """Type text character-by-character at a plausible human speed."""
    page.click(selector)
    time.sleep(random.uniform(0.3, 0.7))
    for ch in text:
        page.keyboard.type(ch)
        time.sleep(random.uniform(0.06, 0.22))


def _human_scroll(page, rounds: int | None = None) -> None:
    """Scroll down in natural, variable increments with pauses."""
    if rounds is None:
        rounds = random.randint(4, 7)
    for _ in range(rounds):
        px = random.randint(280, 650)
        page.evaluate(f"window.scrollBy(0, {px})")
        # Occasional longer pause as if the user stopped to read something
        if random.random() < 0.25:
            time.sleep(random.uniform(2.5, 5.0))
        else:
            time.sleep(random.uniform(1.2, 3.0))


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def _is_logged_in(page) -> bool:
    """Check whether the current page shows a logged-in Facebook state."""
    return (
        "/login" not in page.url
        and "checkpoint" not in page.url
        and page.query_selector('div[aria-label="Your profile"]') is not None
        or page.query_selector('[data-testid="royal_login_button"]') is None
    )


def _dismiss_cookie_banner(page) -> None:
    """Dismiss Facebook's cookie consent dialog if present."""
    for selector in (
        'button[data-cookiebanner="accept_button"]',
        'button[data-testid="cookie-policy-manage-dialog-accept-button"]',
        '[aria-label="Allow all cookies"]',
        '[aria-label="Accept all"]',
    ):
        try:
            btn = page.query_selector(selector)
            if btn:
                btn.click()
                _pause(0.8, 1.5)
                return
        except Exception:
            pass


def _login(page, email: str, password: str) -> None:
    """Navigate to Facebook home and log in if not already authenticated."""
    page.goto(_FB_BASE + "/", wait_until="domcontentloaded", timeout=60_000)
    _pause(2.0, 4.0)

    _dismiss_cookie_banner(page)

    # Wait up to 12 s for the email field — the FB SPA can be slow to render.
    try:
        page.wait_for_selector('input[name="email"]', timeout=12_000)
    except Exception:
        return  # Email field never appeared → assume already logged in

    _human_type(page, 'input[name="email"]', email)
    _pause(0.4, 1.0)
    _human_type(page, 'input[name="pass"]', password)
    _pause(0.5, 1.2)

    # Try name="login" first, fall back to the submit button
    login_btn = (
        page.query_selector('button[name="login"]')
        or page.query_selector('button[type="submit"]')
    )
    if login_btn:
        login_btn.click()
    else:
        page.keyboard.press("Enter")

    try:
        page.wait_for_load_state("domcontentloaded", timeout=30_000)
    except Exception:
        pass
    _pause(3.0, 5.0)

    # If Facebook landed on a checkpoint or 2FA page, pause longer to let
    # the human intervene (only relevant when FB_HEADLESS=false).
    if any(k in page.url for k in ("checkpoint", "login", "two_step")):
        _pause(10.0, 15.0)


# ---------------------------------------------------------------------------
# Card extraction (search results page)
# ---------------------------------------------------------------------------

_RESPONDENT_RE = re.compile(r"([\d,]+)\s+(?:people\s+)?(?:interested|going)", re.I)


def _parse_respondent_count(text: str) -> int:
    m = _RESPONDENT_RE.search(text)
    if not m:
        return 0
    return int(m.group(1).replace(",", ""))


def _extract_event_id(href: str) -> str:
    m = _EVENT_ID_RE.search(href)
    return m.group(1) if m else ""


def _extract_cards(page) -> list[dict]:
    """
    Extract event cards from a Facebook Events search results page.

    Mirrors the logic in veent-fb-scraper/extension/content/content.js
    extractFromSearchResults(): find all /events/<id> links, walk up to the
    card root, then pull text lines for title / date / venue.
    """
    # Collect all unique event links on the page
    links = page.query_selector_all('a[href*="/events/"]')
    seen_ids: set[str] = set()
    cards: list[dict] = []

    for link in links:
        href = link.get_attribute("href") or ""
        eid = _extract_event_id(href)
        if not eid or eid in seen_ids:
            continue
        seen_ids.add(eid)

        # Walk up to a container that has meaningful text
        root = link
        for _ in range(6):
            parent = root.query_selector("xpath=..")
            if parent is None:
                break
            text = (parent.inner_text() or "").strip()
            # Stop when we have a card-like block (multiple lines, respondent info)
            if len(text.splitlines()) >= 3 or _RESPONDENT_RE.search(text):
                root = parent
                break
            root = parent

        full_text = (root.inner_text() or "").strip()
        lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]

        respondent_count = _parse_respondent_count(full_text)
        if respondent_count < _MIN_RESPONDENTS:
            continue

        # Title: first non-date, non-respondent line of reasonable length
        title = next(
            (
                ln for ln in lines
                if len(ln) > 5
                and not _RESPONDENT_RE.search(ln)
                and not re.match(r"^\w{3,9}\s+\d", ln)  # skip bare date lines
            ),
            lines[0] if lines else "",
        )

        event_url = (
            _FB_BASE + href if href.startswith("/") else href
        ).split("?")[0]

        # Best-effort venue: a line that looks like a place name (not a date/number)
        venue_name = next(
            (
                ln for ln in lines
                if ln != title
                and not _RESPONDENT_RE.search(ln)
                and not re.match(r"^\d", ln)
                and len(ln) > 3
            ),
            "",
        )

        cards.append(
            {
                "event_url": event_url,
                "external_id": eid,
                "title": title,
                "venue_name": venue_name,
                "respondent_count": respondent_count,
                "raw_lines": lines,
            }
        )

    return cards


# ---------------------------------------------------------------------------
# Detail-page enrichment
# ---------------------------------------------------------------------------

_DATE_KEYWORDS = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|"
    r"october|november|december|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday)\b",
    re.I,
)
_CITY_RE = re.compile(r"([A-Z][a-zA-Z\s]+),\s+([A-Z][a-zA-Z\s]+)")


def _enrich_from_detail(page, event_url: str) -> dict:
    """
    Visit an individual event page and extract enriched fields.

    Replicates veent-fb-scraper content.js extractFromEventDetailPage():
    full date string, description, organizer (via "Event by X" pattern), city.
    """
    try:
        page.goto(event_url, wait_until="domcontentloaded", timeout=45_000)
        _pause(1.5, 3.5)

        full_text = page.inner_text("body") or ""
        lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]

        # Title: h1 text
        title_el = page.query_selector("h1")
        title = title_el.inner_text().strip() if title_el else ""

        # Full date: first line containing a day/month keyword
        start_datetime_str = next(
            (ln for ln in lines if _DATE_KEYWORDS.search(ln) and len(ln) > 8),
            "",
        )

        # Description: first substantial paragraph (>40 chars, not a date/button)
        description = next(
            (
                ln for ln in lines
                if len(ln) > 40
                and not _DATE_KEYWORDS.search(ln)
                and not re.match(r"^(event by|interested|going|share|invite)", ln, re.I)
            ),
            "",
        )

        # Organizer: line immediately after "Event by"
        organizer = ""
        for i, ln in enumerate(lines):
            if re.match(r"^event\s+by\b", ln, re.I) and i + 1 < len(lines):
                organizer = lines[i + 1]
                break

        # City: pattern "City, Country/Region"
        city_location = ""
        for ln in lines:
            m = _CITY_RE.search(ln)
            if m:
                city_location = m.group(0)
                break

        # Venue: look for the venue link text
        venue_name = ""
        venue_el = page.query_selector('a[href*="/l/"]') or page.query_selector(
            'a[href*="maps.google"]'
        )
        if venue_el:
            venue_name = (venue_el.inner_text() or "").strip()

        return {
            "title": title,
            "start_datetime_str": start_datetime_str,
            "description": description,
            "organizer": organizer,
            "city_location": city_location,
            "venue_name": venue_name,
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Datetime parsing
# ---------------------------------------------------------------------------

_DATE_FMTS = (
    "%A, %B %d, %Y at %I %p",
    "%A, %B %d, %Y at %I:%M %p",
    "%B %d, %Y at %I %p",
    "%B %d, %Y at %I:%M %p",
    "%A, %B %d at %I %p",
    "%B %d at %I %p",
)


def _parse_fb_date(raw: str) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    for fmt in _DATE_FMTS:
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.year == 1900:
                dt = dt.replace(year=datetime.now().year)
            return dt.replace(tzinfo=_PHT).astimezone(dt_timezone.utc)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Scraper class
# ---------------------------------------------------------------------------

class FacebookEventsScraper(BaseScraper):
    """Automated Facebook Events scraper following a humanized user flow."""

    source = "facebook_events"

    def _browser_context(self, pw):
        """Return a persistent browser context so cookies survive across runs."""
        user_data_dir = os.environ.get(
            "FB_USER_DATA_DIR",
            str(Path.home() / ".cache" / "veent-fb-session"),
        )
        headless = os.environ.get("FB_HEADLESS", "true").lower() != "false"

        context = pw.chromium.launch_persistent_context(
            user_data_dir,
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-sandbox",
            ],
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": random.randint(1280, 1440), "height": random.randint(768, 900)},
            locale="en-US",
            timezone_id="Asia/Manila",
        )
        return context

    def _fetch_for_query(self, page, query: str) -> Iterable[ScrapedEvent]:
        """Search Facebook Events for one query and yield enriched ScrapedEvents."""
        search_url = _SEARCH_URL.format(query=urllib.parse.quote(query))
        for attempt in range(3):
            try:
                page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
                break
            except Exception as exc:
                if attempt == 2:
                    raise
                _pause(3.0, 5.0 + attempt * 2)
        _pause(2.0, 4.5)

        # Scroll to load more results
        _human_scroll(page)

        cards = _extract_cards(page)

        for card in cards:
            event_url = card["event_url"]
            if not event_url:
                continue

            # Enrich from detail page
            _pause(1.0, 2.5)
            detail = _enrich_from_detail(page, event_url)

            title = detail.get("title") or card["title"]
            if not title:
                continue

            venue_name = detail.get("venue_name") or card["venue_name"]
            city_location = detail.get("city_location", "")
            city = city_location.split(",")[0].strip() if city_location else ""

            venue = (
                ScrapedVenue(
                    name=venue_name,
                    city=city,
                    country="Philippines" if city else "",
                )
                if venue_name
                else None
            )

            yield ScrapedEvent(
                name=title,
                description=detail.get("description", ""),
                starts_at=_parse_fb_date(detail.get("start_datetime_str", "")),
                url=event_url,
                external_id=card["external_id"],
                source_url=search_url,
                organizer=detail.get("organizer", ""),
                venue=venue,
            )

            # Humanized pause between detail page visits
            _pause(1.5, 3.5)

    def fetch(self) -> Iterable[ScrapedEvent]:
        # fetch() is intentionally empty; run() drives the per-query loop
        # so we can wire FK updates. Direct callers of fetch() get nothing.
        return iter([])

    def run(self, query_id: int | None = None) -> dict:
        """Run the scraper.

        ``query_id``: when provided, only the SearchQuery with that PK is
        processed (single-query mode triggered by the "Run" button in the UI).
        When None, all active queries for this source are run.
        """
        from django.utils import timezone
        from events.models import Event, SearchQuery

        email = os.environ.get("FB_EMAIL", "")
        password = os.environ.get("FB_PASSWORD", "")
        if not email or not password:
            raise RuntimeError(
                "FB_EMAIL and FB_PASSWORD must be set in .env to run the "
                "facebook_events scraper."
            )

        qs = SearchQuery.objects.filter(source=self.source, is_active=True)
        if query_id:
            qs = qs.filter(pk=query_id)
        queries = list(qs)
        if not queries:
            return {"source": self.source, "created": 0, "updated": 0}

        total_created = total_updated = 0

        with sync_playwright() as pw:
            context = self._browser_context(pw)
            Stealth().use_sync(context.pages[0] if context.pages else context.new_page())
            page = context.pages[0] if context.pages else context.new_page()

            _login(page, email, password)

            for sq in queries:
                events = list(self._fetch_for_query(page, sq.query))
                result = save_events(self.source, events)

                # Link newly-saved events to their SearchQuery row
                Event.objects.filter(
                    pk__in=result["event_ids"],
                    search_query__isnull=True,
                ).update(search_query=sq)

                sq.last_run_at = timezone.now()
                sq.events_found_count += result["created"]
                sq.save(update_fields=["last_run_at", "events_found_count", "updated_at"])

                total_created += result["created"]
                total_updated += result["updated"]

                # Pause between searches to look natural
                _pause(3.0, 6.0)

            context.close()

        return {
            "source": self.source,
            "created": total_created,
            "updated": total_updated,
        }
