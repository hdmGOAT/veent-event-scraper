"""Facebook Events scraper — unauthenticated, proxy-backed.

Flow (mirrors veent-fb-scraper/extension/content/content.js):
  1. Launch a headless Chromium via DataImpulse residential proxy (if configured).
  2. Block images / media / fonts to minimise data usage.
  3. For every active SearchQuery where source='facebook_events':
       a. Navigate to https://www.facebook.com/events/search?q=<query>
       b. Dismiss the login-gate modal via JS injection.
       c. Scroll in a humanised pattern to trigger FB's infinite scroll.
       d. Extract event cards by running the same JS logic as the Chrome extension.
       e. Visit each event detail page and extract enriched fields.
  4. Save via the shared save_events() pipeline and link events to their SearchQuery.

No Facebook credentials required. Login-wall is worked around by dismissing the
overlay — the card data is present in the DOM regardless of auth state.

Proxy configuration (DataImpulse residential — optional but recommended):
    DATAIMPULSE_USER   e.g. 69358f718a3e81816efa__cr.ph
    DATAIMPULSE_PASS   proxy password
    DATAIMPULSE_HOST   default: gw.dataimpulse.com
    DATAIMPULSE_PORT   default: 823

Other env vars:
    FB_HEADLESS        set to "false" to watch the browser (default: true)
"""
from __future__ import annotations

import logging
import os
import random
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Iterable

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from .base import BaseScraper, ScrapedEvent, ScrapedOrganizer, ScrapedVenue, save_events, save_organizers
from .social_proxy import social_proxy_configured

logger = logging.getLogger(__name__)

_FB_BASE   = "https://www.facebook.com"
_SEARCH_URL = _FB_BASE + "/events/search?q={query}"
_PHT        = dt_timezone(timedelta(hours=8))

# Block images only — everything else loads normally so FB renders correctly.
_BLOCK_TYPES = {"image", "media"}

# ── JS injected into the page — extracted from veent-fb-scraper content.js ──

_DISMISS_MODAL_JS = """
() => {
    for (const dialog of document.querySelectorAll('[role="dialog"]')) {
        const text = dialog.textContent || '';
        if (!/log\\s*in|sign\\s*up|create\\s*(an?\\s*)?account/i.test(text)) continue;
        const closeBtn = dialog.querySelector('[aria-label="Close"], [aria-label="close"]');
        if (closeBtn) {
            closeBtn.click();
        } else {
            dialog.remove();
            document.querySelectorAll('[data-visualcompletion="ignore-dynamic"]').forEach(el => {
                const pos = el.style?.position || getComputedStyle(el).position;
                if (pos === 'fixed') el.remove();
            });
        }
        document.body.style.overflow = '';
        document.documentElement.style.overflow = '';
        return true;
    }
    return false;
}
"""

# Search-results extraction — returns {events: [...], debug: {...}}
_EXTRACT_SEARCH_JS = r"""
(searchTerm) => {
    const EVENT_PATH_RE = /facebook\.com\/events\/(?!search|upcoming|calendar|explore|birthdays|create|feed|going|invited)([a-z0-9])/i;
    const EVENT_ID_RE   = /\/events\/[^?#]*?(\d{8,})/;
    const DATE_WORD_RE  = /\b(mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|today|tomorrow|happening|yesterday)\b/i;
    const FULL_MONTH_RE = /\b(january|february|march|april|may|june|july|august|september|october|november|december)\b/i;
    const NOISE_RE      = /\b(interested|going|attending|share|invited|maybe)\b|\d+\s+(interested|going)|notifications?/i;
    const UI_CHROME_SET = new Set(['events','home','watch','marketplace','menu','notifications','your events']);
    const CITY_RE       = /^[A-Za-zÀ-ɏ][\w\sÀ-ɏ]{1,40},\s+[A-Za-zÀ-ɏ][\w\sÀ-ɏ]{1,40}$/;
    const MIN_RESPONDENTS = 10;

    function leafText(el) {
        if (el.querySelectorAll('span, div, p').length > 3) return null;
        return el.textContent?.trim() || null;
    }

    function parseRespondentCount(lines) {
        for (const t of lines) {
            if (!/\b(interested|going|attended|went|responded|people)\b/i.test(t)) continue;
            const nums = t.match(/\d+/g);
            if (nums) return nums.reduce((s, n) => s + parseInt(n, 10), 0);
        }
        return null;
    }

    function findCardRoot(anchor, maxSteps = 10) {
        let el = anchor.parentElement;
        for (let i = 0; i < maxSteps; i++) {
            if (!el || el === document.body) break;
            const rect = el.getBoundingClientRect();
            if (rect.height > 80 && rect.width > 200) return el;
            el = el.parentElement;
        }
        return anchor.parentElement;
    }

    function getTextLines(card) {
        const lines = [], seen = new Set();
        for (const el of card.querySelectorAll('span, div')) {
            if (el.querySelectorAll('span, div').length > 2) continue;
            const t = el.textContent?.trim();
            if (!t || t.length < 3 || t.length > 300 || seen.has(t)) continue;
            seen.add(t); lines.push(t);
        }
        return lines;
    }

    function isNoise(t) {
        return NOISE_RE.test(t) || /^\d+$/.test(t) || t.length < 3 || t.length > 200 || UI_CHROME_SET.has(t.toLowerCase());
    }

    function pickLineAfterDate(lines, n) {
        let passedDate = false, count = 0;
        for (const t of lines) {
            if (DATE_WORD_RE.test(t)) { passedDate = true; continue; }
            if (!passedDate) continue;
            if (isNoise(t)) continue;
            if (count === n) return t;
            count++;
        }
        count = 0;
        for (const t of lines) {
            if (isNoise(t)) continue;
            if (count === n) return t;
            count++;
        }
        return null;
    }

    const seenRoots = new Set(), seenUrls = new Set(), events = [];
    let skippedLowCount = 0;

    for (const a of document.querySelectorAll('a[href]')) {
        const href = a.href || '';
        if (!EVENT_PATH_RE.test(href)) continue;
        const idMatch  = href.match(EVENT_ID_RE);
        const eventUrl = href.split('?')[0];
        if (seenUrls.has(eventUrl)) continue;
        const root = findCardRoot(a);
        if (!root || seenRoots.has(root)) { seenUrls.add(eventUrl); continue; }
        seenRoots.add(root); seenUrls.add(eventUrl);

        const lines           = getTextLines(root);
        const respondent_count = parseRespondentCount(lines);
        if (respondent_count !== null && respondent_count < MIN_RESPONDENTS) { skippedLowCount++; continue; }

        const title = pickLineAfterDate(lines, 0);
        if (!title) continue;

        const timeEl = root.querySelector('time[datetime]');
        const start_datetime = timeEl
            ? (timeEl.getAttribute('datetime') || timeEl.textContent.trim())
            : (lines.find(t => DATE_WORD_RE.test(t) && t.length < 80) || null);

        // organizer: "Event by NAME"
        let organizer_name = null;
        for (const el of root.querySelectorAll('span, div')) {
            const t = leafText(el);
            if (!t) continue;
            const m = t.match(/^Event\s+by\s+(.{1,100})$/i);
            if (m && !/https?:\/\//.test(m[1])) { organizer_name = m[1].trim(); break; }
        }

        let short_description = null;
        for (const p of root.querySelectorAll('p, [role="paragraph"]')) {
            const t = p.textContent.trim();
            if (t.length > 20) { short_description = t.substring(0, 500); break; }
        }

        events.push({
            event_url:          eventUrl,
            event_id:           idMatch ? idMatch[1] : '',
            title,
            start_datetime,
            venue_name:         pickLineAfterDate(lines, 1) || null,
            organizer_name,
            short_description,
            respondent_count:   respondent_count ?? 0,
            source_search_term: searchTerm,
        });
    }

    return { events, debug: { cardRoots: seenRoots.size, skippedLowCount } };
}
"""

# Detail-page extraction — returns {events: [...], debug: {...}}
_EXTRACT_DETAIL_JS = r"""
(searchTerm) => {
    const EVENT_ID_RE   = /\/events\/[^?#]*?(\d{8,})/;
    const DATE_WORD_RE  = /\b(mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|today|tomorrow|happening|yesterday)\b/i;
    const FULL_MONTH_RE = /\b(january|february|march|april|may|june|july|august|september|october|november|december)\b/i;
    const NOISE_RE      = /\b(interested|going|attending|share|invited|maybe)\b|\d+\s+(interested|going)|notifications?/i;
    const UI_CHROME_SET = new Set(['events','home','watch','marketplace','menu','notifications','your events']);
    const CITY_RE       = /^[A-Za-zÀ-ɏ][\w\sÀ-ɏ]{1,40},\s+[A-Za-zÀ-ɏ][\w\sÀ-ɏ]{1,40}$/;

    function leafText(el) {
        if (el.querySelectorAll('span, div, p').length > 3) return null;
        return el.textContent?.trim() || null;
    }
    function isInSidebarNav(el) { return !!el.closest('[role="navigation"]'); }

    const eventUrl = location.href.split('?')[0];
    const idMatch  = eventUrl.match(EVENT_ID_RE);

    // Title: page <title> is "Event Name | Facebook" — more reliable than h1
    // which often contains the nav breadcrumb "Events" instead of the actual name.
    let title = document.title.replace(/\s*[|·–\-]\s*facebook\s*$/i, '').trim();
    if (!title || UI_CHROME_SET.has(title.toLowerCase())) {
        // Fallback: first h1/h2 that isn't nav chrome
        for (const el of document.querySelectorAll('h1, h2')) {
            const t = el.textContent?.trim();
            if (t && !UI_CHROME_SET.has(t.toLowerCase()) && t.length > 3) { title = t; break; }
        }
    }
    if (!title) return { events: [], debug: { error: 'no title' } };

    let start_datetime = null;
    for (const el of document.querySelectorAll('span, div, h2, strong')) {
        if (isInSidebarNav(el)) continue;
        const t = leafText(el);
        if (!t || t.length < 8 || t.length > 100) continue;
        if (FULL_MONTH_RE.test(t) && /\bat\b/i.test(t)) { start_datetime = t; break; }
        if (FULL_MONTH_RE.test(t) && /\d{4}/.test(t))   { start_datetime = t; break; }
    }

    // ── Host: "Meet your host" section ───────────────────────────────────────
    // FB renders a card with the exact heading "Meet your host" that contains a
    // link to the organiser's Facebook page. We find the heading by exact text
    // match (no leafText nesting limit), then walk up to the card container.
    let organizer_name = null;
    let organizer_url  = null;

    const FB_PAGE_RE = /^https?:\/\/(www\.)?facebook\.com\/(?!events\/|pages\/category\/|groups\/|photos\/|videos\/|share\/)([^/?#]{2,})/i;

    const hostHeading = Array.from(document.querySelectorAll('span, div, h2, h3, strong'))
        .find(el => /^meet\s+your\s+host$/i.test((el.textContent || '').trim()));

    if (hostHeading) {
        let container = hostHeading.parentElement;
        for (let i = 0; i < 10 && container && container !== document.body; i++) {
            for (const a of container.querySelectorAll('a[href]')) {
                const href = a.href || '';
                if (FB_PAGE_RE.test(href) && !/\/events\//.test(href)) {
                    organizer_url  = href.split('?')[0];
                    organizer_name = (a.textContent || '').trim() || null;
                    break;
                }
            }
            if (organizer_url) break;
            container = container.parentElement;
        }
    }

    // Fallback: plain "Event by NAME" text anywhere in the page body
    if (!organizer_name) {
        for (const el of document.querySelectorAll('span, div, a')) {
            if (isInSidebarNav(el)) continue;
            const t = leafText(el);
            if (!t) continue;
            const m = t.match(/^Event\s+by\s+(.{1,100})$/i);
            if (m && !/https?:\/\//.test(m[1])) { organizer_name = m[1].trim(); break; }
        }
    }

    let venue_name = null;
    for (const el of document.querySelectorAll('span, div, a')) {
        if (isInSidebarNav(el)) continue;
        const t = leafText(el);
        if (!t || t.length < 5 || t.length > 150) continue;
        if (DATE_WORD_RE.test(t) || FULL_MONTH_RE.test(t)) continue;
        if (NOISE_RE.test(t)) continue;
        if (CITY_RE.test(t)) continue;
        if (/^Event\s+by\b/i.test(t)) continue;
        if (/people\s+respond/i.test(t)) continue;
        if (/Public|Anyone\s+on/i.test(t)) continue;
        if (/Tickets?|Find\s+tickets/i.test(t)) continue;
        if (/Discussion|About|Going|Interested|Invite/i.test(t)) continue;
        if (UI_CHROME_SET.has(t.toLowerCase())) continue;
        if (/^[A-Z]/.test(t) && t.length >= 5) { venue_name = t; break; }
    }

    let city_location = null;
    for (const el of document.querySelectorAll('a, span, div')) {
        if (isInSidebarNav(el)) continue;
        const t = leafText(el);
        if (!t || t.length > 60 || t.length < 5) continue;
        if (CITY_RE.test(t) && !DATE_WORD_RE.test(t) && !NOISE_RE.test(t)) { city_location = t; break; }
    }

    // Description: FB rarely uses <p> — scan leaf-ish divs for the first
    // substantial block that isn't a date, noise, or section heading.
    let short_description = null;
    const DESC_SKIP_RE = /^(meet your host|about|going|interested|invited|share|discussion|ticket|find ticket|public|anyone on)/i;
    for (const el of document.querySelectorAll('div, p, span')) {
        if (isInSidebarNav(el)) continue;
        if (el.querySelectorAll('div, p').length > 2) continue; // skip containers
        const t = el.textContent?.trim();
        if (!t || t.length < 50 || t.length > 3000) continue;
        if (FULL_MONTH_RE.test(t.substring(0, 40))) continue; // skip date blocks
        if (NOISE_RE.test(t)) continue;
        if (DESC_SKIP_RE.test(t)) continue;
        if (UI_CHROME_SET.has(t.toLowerCase())) continue;
        if (CITY_RE.test(t)) continue;
        short_description = t.substring(0, 1000);
        break;
    }

    return {
        events: [{
            event_url:          eventUrl,
            event_id:           idMatch ? idMatch[1] : '',
            title,
            start_datetime,
            venue_name,
            city_location,
            organizer_name,
            organizer_url,
            short_description,
            respondent_count:   0,
            source_search_term: searchTerm,
        }],
        debug: { mode: 'detail' },
    };
}
"""

# ── Humanization helpers ──────────────────────────────────────────────────────

def _pause(lo: float = 1.0, hi: float = 3.5) -> None:
    time.sleep(random.uniform(lo, hi))


def _human_scroll(page, rounds: int | None = None) -> None:
    if rounds is None:
        rounds = random.randint(4, 7)
    for _ in range(rounds):
        px = random.randint(280, 650)
        page.evaluate(f"window.scrollBy(0, {px})")
        if random.random() < 0.20:
            time.sleep(random.uniform(2.5, 5.0))
        else:
            time.sleep(random.uniform(1.2, 3.0))


# ── Date parsing ──────────────────────────────────────────────────────────────

_DATE_FMTS = (
    "%A, %B %d, %Y at %I %p",
    "%A, %B %d, %Y at %I:%M %p",
    "%B %d, %Y at %I %p",
    "%B %d, %Y at %I:%M %p",
    "%A, %B %d at %I %p",
    "%B %d at %I %p",
)


def _parse_fb_date(raw: str | None) -> datetime | None:
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


# ── Scraper ───────────────────────────────────────────────────────────────────

class FacebookEventsScraper(BaseScraper):
    """Unauthenticated Facebook Events scraper.

    Navigates public Facebook Events search pages as a guest, dismisses the
    login-gate modal, and extracts event data from the DOM — no credentials
    required. Routes traffic through DataImpulse residential proxies when
    configured; falls back to direct connections with a warning.
    """

    source = "facebook_events"

    # ── Proxy ─────────────────────────────────────────────────────────────────

    def _playwright_proxy(self) -> dict | None:
        if not social_proxy_configured():
            logger.warning(
                "DATAIMPULSE_USER/PASS not set — running without proxy. "
                "Facebook may rate-limit or block datacenter IPs."
            )
            return None
        user     = os.environ["DATAIMPULSE_USER"]
        password = os.environ["DATAIMPULSE_PASS"]
        host     = os.environ.get("DATAIMPULSE_HOST", "gw.dataimpulse.com")
        port     = os.environ.get("DATAIMPULSE_PORT", "823")
        return {"server": f"http://{host}:{port}", "username": user, "password": password}

    # ── Browser context ───────────────────────────────────────────────────────

    def _browser_context(self, pw):
        headless = os.environ.get("FB_HEADLESS", "true").lower() != "false"
        proxy    = self._playwright_proxy()

        launch_kwargs: dict = {
            "headless": headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-sandbox",
            ],
        }
        if proxy:
            launch_kwargs["proxy"] = proxy

        browser = pw.chromium.launch(**launch_kwargs)
        context = browser.new_context(
            viewport={"width": random.randint(1280, 1440), "height": random.randint(768, 900)},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="Asia/Manila",
            java_script_enabled=True,
        )
        return browser, context

    # ── Resource blocking ─────────────────────────────────────────────────────

    def _block_heavy_resources(self, page) -> None:
        def _handle(route):
            if route.request.resource_type in _BLOCK_TYPES:
                route.abort()
            else:
                route.continue_()
        page.route("**/*", _handle)

    # ── Navigation helper ─────────────────────────────────────────────────────

    def _goto(self, page, url: str, retries: int = 3) -> None:
        for attempt in range(retries):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                return
            except Exception as exc:
                if attempt == retries - 1:
                    raise
                logger.warning("goto %s attempt %d failed: %s", url, attempt + 1, exc)
                _pause(3.0, 6.0 + attempt * 3)

    # ── Per-query scrape ──────────────────────────────────────────────────────

    def _fetch_for_query(self, page, query: str) -> Iterable[ScrapedEvent]:
        search_url = _SEARCH_URL.format(query=urllib.parse.quote(query))
        self._goto(page, search_url)
        _pause(2.5, 5.0)

        # Dismiss login modal then scroll to load more results
        page.evaluate(_DISMISS_MODAL_JS)
        _pause(0.8, 1.5)
        _human_scroll(page)

        # Re-dismiss — FB can re-show the modal after scroll
        page.evaluate(_DISMISS_MODAL_JS)
        _pause(1.0, 2.0)

        result = page.evaluate(_EXTRACT_SEARCH_JS, query)
        cards  = result.get("events", [])
        debug  = result.get("debug", {})
        logger.info(
            "[%s] search '%s': %d cards (%d skipped low-count)",
            self.source, query, len(cards), debug.get("skippedLowCount", 0),
        )

        for card in cards:
            event_url = card.get("event_url", "")
            if not event_url:
                continue

            _pause(1.5, 3.5)
            try:
                self._goto(page, event_url)
            except Exception as exc:
                logger.warning("detail page failed for %s: %s", event_url, exc)
                continue
            _pause(1.5, 3.5)

            page.evaluate(_DISMISS_MODAL_JS)

            detail = page.evaluate(_EXTRACT_DETAIL_JS, query)
            detail_events = detail.get("events", [])
            d = detail_events[0] if detail_events else {}

            title = d.get("title") or card.get("title", "")
            if not title:
                continue

            venue_name     = d.get("venue_name") or card.get("venue_name") or ""
            city_location  = d.get("city_location", "")
            city           = city_location.split(",")[0].strip() if city_location else ""
            organizer      = d.get("organizer_name") or card.get("organizer_name") or ""
            organizer_url  = d.get("organizer_url") or ""
            description    = d.get("short_description") or card.get("short_description") or ""
            start_raw      = d.get("start_datetime") or card.get("start_datetime")
            external_id    = d.get("event_id") or card.get("event_id", "")

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
                description=description,
                starts_at=_parse_fb_date(start_raw),
                url=event_url,
                external_id=external_id,
                source_url=search_url,
                organizer=organizer,
                organizer_url=organizer_url,
                venue=venue,
            )

    # ── BaseScraper overrides ─────────────────────────────────────────────────

    def fetch(self) -> Iterable[ScrapedEvent]:
        # fetch() is intentionally empty; run() drives the loop so we can do
        # per-SearchQuery FK updates. Direct callers of fetch() get nothing.
        return iter([])

    def run(self, query_id: int | None = None) -> dict:
        """Run the scraper for all active SearchQuery rows (or just one if query_id set).

        Django ORM calls are deliberately kept OUTSIDE the sync_playwright() block.
        Playwright's sync API runs its own event loop internally; Django detects that
        as an async context and raises SynchronousOnlyOperation if ORM is called inside.
        """
        from django.utils import timezone
        from events.models import Event, SearchQuery

        # ── 1. Load queries (ORM outside playwright) ──────────────────────────
        qs = SearchQuery.objects.filter(source=self.source, is_active=True)
        if query_id:
            qs = qs.filter(pk=query_id)
        queries = list(qs)
        if not queries:
            logger.info("[%s] no active search queries — nothing to do.", self.source)
            return {"source": self.source, "created": 0, "updated": 0}

        # ── 2. Scrape (inside playwright, no ORM) ─────────────────────────────
        # Collect {sq.id: [ScrapedEvent, ...]} without touching Django ORM.
        scraped: dict[int, list] = {}

        with sync_playwright() as pw:
            browser, context = self._browser_context(pw)
            page = context.new_page()
            Stealth().use_sync(page)
            self._block_heavy_resources(page)
            try:
                for sq in queries:
                    scraped[sq.id] = list(self._fetch_for_query(page, sq.query))
                    _pause(3.0, 6.0)
            finally:
                context.close()
                browser.close()

        # ── 3. Persist (ORM outside playwright) ───────────────────────────────

        # Upsert organizers first so save_events() can resolve organizer_ref FK.
        # Dedup key: FB page slug from URL when available, otherwise organizer name.
        all_events = [e for events in scraped.values() for e in events]
        seen_org_keys: set[str] = set()
        scraped_orgs: list[ScrapedOrganizer] = []
        for se in all_events:
            name = (se.organizer or "").strip()
            url  = (se.organizer_url or "").rstrip("/")
            if not name:
                continue
            key = url or name.lower()
            if key in seen_org_keys:
                continue
            seen_org_keys.add(key)
            # Use the FB page slug as external_id (e.g. "orbitzatexconeoncdo")
            # so re-runs update rather than duplicate; empty string is fine for name-only rows.
            external_id = url.split("/")[-1] if url else ""
            scraped_orgs.append(ScrapedOrganizer(
                name=name,
                website=url,
                facebook_url=url,
                external_id=external_id,
            ))
        if scraped_orgs:
            save_organizers(self.source, scraped_orgs)

        total_created = total_updated = 0
        for sq in queries:
            result = save_events(self.source, scraped.get(sq.id, []))

            Event.objects.filter(
                pk__in=result.get("event_ids", []),
                search_query__isnull=True,
            ).update(search_query=sq)

            sq.last_run_at = timezone.now()
            sq.events_found_count += result["created"]
            sq.save(update_fields=["last_run_at", "events_found_count", "updated_at"])

            total_created += result["created"]
            total_updated += result["updated"]

        return {
            "source": self.source,
            "created": total_created,
            "updated": total_updated,
        }
