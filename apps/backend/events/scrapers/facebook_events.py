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
from events.registration_patterns import find_registration_url

logger = logging.getLogger(__name__)

_FB_BASE   = "https://www.facebook.com"
_SEARCH_URL = _FB_BASE + "/events/search?q={query}"
_PHT        = dt_timezone(timedelta(hours=8))

# Block images only — everything else loads normally so FB renders correctly.
_BLOCK_TYPES = {"image", "media"}

# ── JS injected into the page — extracted from veent-fb-scraper content.js ──

_DISMISS_MODAL_JS = """
() => {
    let dismissed = false;

    // 1. Remove any [role="dialog"] containing login/signup text
    for (const dialog of document.querySelectorAll('[role="dialog"]')) {
        const text = dialog.textContent || '';
        if (!/log\\s*in|sign\\s*up|create\\s*(an?\\s*)?account|forgot\\s*(account|password)/i.test(text)) continue;
        const closeBtn = dialog.querySelector('[aria-label="Close"], [aria-label="close"]');
        if (closeBtn) { closeBtn.click(); } else { dialog.remove(); }
        dismissed = true;
    }

    // 2. Nuke ALL fixed/sticky overlays that block the page content.
    //    This catches FB's interstitial login wall even when it lacks role="dialog".
    document.querySelectorAll('*').forEach(el => {
        try {
            const s = el.style;
            const cs = getComputedStyle(el);
            const pos = s.position || cs.position;
            if (pos !== 'fixed' && pos !== 'sticky') return;
            const zIndex = parseInt(s.zIndex || cs.zIndex, 10);
            // Only remove high-z overlays that cover most of the viewport
            if (isNaN(zIndex) || zIndex < 100) return;
            const rect = el.getBoundingClientRect();
            if (rect.width > window.innerWidth * 0.5 && rect.height > window.innerHeight * 0.5) {
                el.remove();
                dismissed = true;
            }
        } catch {}
    });

    // 3. Restore scroll lock that FB sets when showing a modal
    document.body.style.overflow = '';
    document.documentElement.style.overflow = '';
    return dismissed;
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
    const UI_CHROME_SET = new Set(['events','home','watch','marketplace','menu','notifications','your events','facebook','log in','sign up','create account','anyone']);
    // Two-part "City, Country" OR three-part "City, State/Province, Country"
    const CITY_RE       = /^[A-Za-zÀ-ɏ][\w\sÀ-ɏ]{1,40},\s+[A-Za-zÀ-ɏ][\w\sÀ-ɏ]{1,40}(,\s+[A-Za-zÀ-ɏ][\w\sÀ-ɏ]{1,40})?$/;
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
    const UI_CHROME_SET = new Set(['events','home','watch','marketplace','menu','notifications','your events','facebook','log in','sign up','create account','anyone']);
    // Two-part "City, Country" OR three-part "City, State/Province, Country"
    const CITY_RE       = /^[A-Za-zÀ-ɏ][\w\sÀ-ɏ]{1,40},\s+[A-Za-zÀ-ɏ][\w\sÀ-ɏ]{1,40}(,\s+[A-Za-zÀ-ɏ][\w\sÀ-ɏ]{1,40})?$/;

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

    // ── Organizer: "Event by [linked NAME]" ─────────────────────────────────
    // On unauthenticated pages the organizer name appears as "Event by NAME"
    // where NAME is a clickable <a> linking to their FB page. We find this
    // element and walk up the DOM to locate the nearest FB page URL.
    let organizer_name = null;
    let organizer_url  = null;

    const FB_PAGE_RE = /^https?:\/\/(www\.)?facebook\.com\/(?!events\/|pages\/category\/|groups\/|photos\/|videos\/|share\/)([^/?#]{2,})/i;

    function cleanFbUrl(href) {
        // profile.php?id=123 must keep the id param — it's the only identifier.
        // All other FB page URLs have the slug in the path, so strip query string.
        if (/\/profile\.php/i.test(href)) {
            try {
                const id = new URL(href).searchParams.get('id');
                return id ? 'https://www.facebook.com/profile.php?id=' + id : href.split('?')[0];
            } catch { return href.split('?')[0]; }
        }
        return href.split('?')[0];
    }

    for (const el of document.querySelectorAll('span, div, a')) {
        if (isInSidebarNav(el)) continue;
        const t = (el.textContent || '').trim();
        if (!/^Event\s+by\b/i.test(t) || t.length > 150) continue;
        const m = t.match(/^Event\s+by\s+(.{1,100})$/i);
        if (m) organizer_name = m[1].trim();
        // Walk up to find a sibling/ancestor containing the organizer page link
        let node = el.parentElement || el;
        for (let i = 0; i < 6 && node && node !== document.body; i++) {
            for (const a of node.querySelectorAll('a[href]')) {
                const href = a.href || '';
                if (FB_PAGE_RE.test(href) && !/\/events\//.test(href)) {
                    organizer_url = cleanFbUrl(href);
                    if (!organizer_name) organizer_name = (a.textContent || '').trim() || null;
                    break;
                }
            }
            if (organizer_url) break;
            node = node.parentElement;
        }
        if (organizer_name) break;
    }

    // Strategy 1b: listitem scan — organizer link lives in a sibling branch of
    // the "Event by" text that the 6-level walk-up misses. FB consistently wraps
    // the organizer section in div[role="listitem"] (often also carrying
    // data-visualcompletion="ignore-dynamic"). Scan all such containers for any
    // FB profile/page URL — /people/<name>/<id>/, /<slug>/, profile.php?id=.
    if (!organizer_url) {
        for (const item of document.querySelectorAll('[role="listitem"]')) {
            if (isInSidebarNav(item)) continue;
            // Must contain "Event by" text to be the right listitem
            if (!/Event\s+by\b/i.test(item.textContent || '')) continue;
            for (const a of item.querySelectorAll('a[href]')) {
                const href = a.href || '';
                if (FB_PAGE_RE.test(href) && !/\/events\//.test(href)) {
                    organizer_url = cleanFbUrl(href);
                    if (!organizer_name) organizer_name = (a.textContent || '').trim() || null;
                    break;
                }
            }
            if (organizer_url) break;
        }
    }

    // Strategy 2: "Meet your host" section (visible when logged in)
    if (!organizer_url) {
        const hostHeading = Array.from(document.querySelectorAll('span, div, h2, h3, strong'))
            .find(el => /^meet\s+your\s+host$/i.test((el.textContent || '').trim()));
        if (hostHeading) {
            let container = hostHeading.parentElement;
            for (let i = 0; i < 10 && container && container !== document.body; i++) {
                for (const a of container.querySelectorAll('a[href]')) {
                    const href = a.href || '';
                    if (FB_PAGE_RE.test(href) && !/\/events\//.test(href)) {
                        organizer_url  = cleanFbUrl(href);
                        organizer_name = organizer_name || (a.textContent || '').trim() || null;
                        break;
                    }
                }
                if (organizer_url) break;
                container = container.parentElement;
            }
        }
    }

    // Normalised title used to skip the event title text that lives inside <span>
    // children of <h1> and would otherwise be mistaken for a venue name.
    const titleNorm = title.toLowerCase().replace(/\s+/g, ' ').trim();

    let venue_name = null;
    for (const el of document.querySelectorAll('span, div, a')) {
        if (isInSidebarNav(el)) continue;
        const t = leafText(el);
        if (!t || t.length < 5 || t.length > 150) continue;
        if (t.toLowerCase().replace(/\s+/g, ' ').trim() === titleNorm) continue; // skip event title
        if (DATE_WORD_RE.test(t) || FULL_MONTH_RE.test(t)) continue;
        if (NOISE_RE.test(t)) continue;
        if (CITY_RE.test(t)) continue;
        if (/^Event\s+by\b/i.test(t)) continue;
        if (/people\s+respond/i.test(t)) continue;
        if (/Public|Anyone\s+on/i.test(t)) continue;
        if (/Tickets?|Find\s+tickets/i.test(t)) continue;
        if (/Discussion|About|Going|Interested|Invite/i.test(t)) continue;
        if (UI_CHROME_SET.has(t.toLowerCase())) continue;
        // Skip platform/login UI text that leaks through as standalone leaf nodes
        if (/^(facebook|instagram|twitter|tiktok|youtube|privacy|terms|cookies?|see\s+more|see\s+less)$/i.test(t)) continue;
        if (/^(log\s*in|sign\s*up|create\s*(new\s*)?account|forgot\s*(account|password)\??|email\s*address|phone\s*number|password|new\s*to\s*facebook|advertising|sponsored|suggested\s+for\s+you)$/i.test(t)) continue;
        if (/^[A-Z]/.test(t) && t.length >= 5) { venue_name = t; break; }
    }

    let city_location = null;
    for (const el of document.querySelectorAll('a, span, div')) {
        if (isInSidebarNav(el)) continue;
        const t = leafText(el);
        if (!t || t.length > 60 || t.length < 5) continue;
        if (CITY_RE.test(t) && !DATE_WORD_RE.test(t) && !NOISE_RE.test(t)) { city_location = t; break; }
    }

    let description = null;
    const DESC_SKIP_RE = /^(public|anyone|events?|about|going|interested|invited|discussion|tickets?|see\s+(more|less)|privacy|terms|log\s+in|sign\s+up)/i;

    // Strategy A: FB's explicit event/post body container — textContent of the whole block
    for (const el of document.querySelectorAll('[data-ad-comet-preview="message"], [data-testid="event-permalink-details"]')) {
        const t = el.textContent?.trim();
        if (t && t.length >= 20) { description = t.substring(0, 2000); break; }
    }

    // Identify the event-details panel once — used by both Strategy B and C.
    // Walk up from the "Event by" organizer element to find the enclosing panel
    // that contains both the organizer line and [dir="auto"] description blocks.
    let eventPanel = null;
    {
        let organizerEl = null;
        for (const el of document.querySelectorAll('span, div')) {
            if (isInSidebarNav(el)) continue;
            const t = (el.textContent || '').trim();
            if (/^Event\s+by\b/i.test(t) && t.length < 150) { organizerEl = el; break; }
        }
        if (organizerEl) {
            let node = organizerEl.parentElement;
            for (let i = 0; i < 20 && node && node !== document.body; i++) {
                if (node.querySelectorAll('[dir="auto"]').length >= 2) { eventPanel = node; break; }
                node = node.parentElement;
            }
        }
    }
    const searchRoot = eventPanel || document;

    // Strategy B: Collect all [role="paragraph"] leaves within the panel and join.
    // FB breaks the description into many short <span role="paragraph"> nodes, each < 30 chars.
    if (!description) {
        const parts = [];
        for (const el of searchRoot.querySelectorAll('[role="paragraph"]')) {
            if (isInSidebarNav(el)) continue;
            const t = el.textContent?.trim();
            if (!t || t.toLowerCase() === titleNorm) continue;
            if (DESC_SKIP_RE.test(t)) continue;
            parts.push(t);
        }
        if (parts.length) description = parts.join('\n').substring(0, 2000);
    }

    // Strategy C: [dir="auto"] containers scoped to the event-details panel.
    if (!description) {
        for (const el of searchRoot.querySelectorAll('[dir="auto"]')) {
            if (isInSidebarNav(el)) continue;
            const t = el.textContent?.trim();
            if (!t || t.length < 80 || t.length > 6000) continue;
            if (t.toLowerCase().replace(/\s+/g, ' ') === titleNorm) continue;
            if (DESC_SKIP_RE.test(t)) continue;
            if (NOISE_RE.test(t)) continue;
            if (DATE_WORD_RE.test(t) && t.length < 100) continue;
            // Strip leading URL lines (some events post only a link at the top)
            const stripped = t.replace(/^(https?:\/\/\S+|www\.\S+)\s*/i, '').trim();
            if (!stripped) continue;
            description = stripped.substring(0, 2000);
            break;
        }
    }

    const linkRoot = eventPanel || document;
    const links = [...new Set(
        [...linkRoot.querySelectorAll('a[href]')]
            .map(a => a.href)
            .filter(h => h && /^https?:\/\//i.test(h) && !/facebook\.com/i.test(h))
    )];

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
            description,
            image_url:          document.querySelector('meta[property="og:image"]')?.content || '',
            links,
            respondent_count:   0,
            source_search_term: searchTerm,
        }],
        debug: {
            mode: 'detail',
            descStrategyA: !!document.querySelector('[data-ad-comet-preview="message"], [data-testid="event-permalink-details"]'),
            descParagraphCount: document.querySelectorAll('[role="paragraph"]').length,
            descDirAutoCount: document.querySelectorAll('div[dir="auto"], span[dir="auto"]').length,
            descFirstLong: (() => {
                for (const el of document.querySelectorAll('span, div, p')) {
                    const t = el.textContent?.trim();
                    if (t && t.length >= 80) return t.substring(0, 100);
                }
                return null;
            })(),
        },
    };
}
"""

# Organizer FB page extraction — email, phone, external website, description
_EXTRACT_ORGANIZER_JS = r"""
() => {
    const WEBSITE_RE = /^https?:\/\/(?!(?:www\.)?(?:facebook|fb|instagram|twitter|x)\.com)[\w\-.]+\.[a-z]{2,}(\/[\w\-./?%&=]*)?$/i;
    const EMAIL_RE   = /[\w.+\-]+@[\w\-]+\.[a-z]{2,}/i;
    const PHONE_RE   = /^[\+\d][\d\s\-().]{5,20}[\d]$/;

    function leafText(el) {
        if (el.querySelectorAll('span, div, p').length > 3) return null;
        return el.textContent?.trim() || null;
    }
    function isInSidebarNav(el) { return !!el.closest('[role="navigation"]'); }

    const name = document.title.replace(/\s*[|·–\-]\s*facebook\s*$/i, '').trim() || null;

    // Email — scan body text
    let email = null;
    const bodyText = document.body.innerText || '';
    const emailMatch = bodyText.match(EMAIL_RE);
    if (emailMatch) email = emailMatch[0];

    // External website — FB wraps outbound links in l.facebook.com/l.php?u=<encoded>.
    // We decode those first, then also check for any un-wrapped direct hrefs.
    let website = null;
    for (const a of document.querySelectorAll('a[href]')) {
        const href = (a.href || '').trim();
        if (/l\.facebook\.com\/l\.php/i.test(href)) {
            try {
                const real = decodeURIComponent(new URL(href).searchParams.get('u') || '');
                if (real && WEBSITE_RE.test(real)) { website = real.split('?')[0]; break; }
            } catch {}
        }
        if (WEBSITE_RE.test(href)) { website = href.split('?')[0]; break; }
    }

    // Phone — leaf elements whose text looks like a phone number
    let phone = null;
    for (const el of document.querySelectorAll('span, div, a')) {
        if (isInSidebarNav(el)) continue;
        const t = leafText(el);
        if (!t) continue;
        if (PHONE_RE.test(t) && (t.match(/\d/g) || []).length >= 7) {
            phone = t.replace(/\s+/g, ' ').trim();
            break;
        }
    }

    // Description — first substantial text block that isn't UI chrome
    let description = null;
    const SKIP_RE = /^(about|photos?|videos?|events?|posts?|reviews?|community|send message|follow|like|home|see more|write a review)/i;
    for (const el of document.querySelectorAll('div, p, span')) {
        if (isInSidebarNav(el)) continue;
        if (el.querySelectorAll('div, p').length > 2) continue;
        const t = el.textContent?.trim();
        if (!t || t.length < 40 || t.length > 2000) continue;
        if (SKIP_RE.test(t)) continue;
        if (/^\d+/.test(t) && t.length < 30) continue;
        description = t.substring(0, 600);
        break;
    }

    // Address — look for address-like text (street numbers, "St", "Ave", "Blvd", etc.)
    let address = null;
    const ADDR_RE = /\b\d+\s+[\w\s.,']{5,60}(?:st(?:reet)?|ave(?:nue)?|blvd|road|rd|drive|dr|lane|ln|barangay|brgy|purok)\b/i;
    const addrMatch = bodyText.match(ADDR_RE);
    if (addrMatch) address = addrMatch[0].trim();

    return { name, email, phone, website, description, address };
}
"""

def _sanitize_url(url: str) -> str:
    """Return scheme+host+path only, stripping query strings and fragments."""
    p = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse((p.scheme, p.netloc, p.path, "", "", ""))


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
    # Strip end-time suffix: "Saturday, June 28, 2025 at 8 PM – 11 PM" → "…at 8 PM"
    # FB always shows "start – end" in the same text element.
    raw = re.sub(r'\s*[–\-]\s*\d.*$', '', raw).strip()
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
    supports_keywords = True

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

    def _fetch_for_query(self, page, query: str, max_events: int | None = None) -> Iterable[ScrapedEvent]:
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

        processed = 0
        for card in cards:
            if max_events is not None and processed >= max_events:
                break
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

            # Dismiss modal, retrying until the event title is visible in the page
            # title (confirms the login wall is gone and real content is loaded).
            for _attempt in range(4):
                page.evaluate(_DISMISS_MODAL_JS)
                _pause(0.6, 1.2)
                page_title = page.title()
                if page_title and "log in" not in page_title.lower() and "facebook" != page_title.strip().lower():
                    break

            # Expand collapsed description ("See more") before extracting
            try:
                page.evaluate("""
                    () => {
                        const btn = Array.from(document.querySelectorAll('div[role="button"], span[role="button"]'))
                            .find(el => /^see\\s+more$/i.test((el.textContent || '').trim()));
                        if (btn) btn.click();
                    }
                """)
                _pause(0.4, 0.8)
            except Exception as exc:
                logger.debug("see-more expansion failed for %s: %s", event_url, exc)

            detail = page.evaluate(_EXTRACT_DETAIL_JS, query)
            detail_events = detail.get("events", [])
            d = detail_events[0] if detail_events else {}

            title = d.get("title") or card.get("title", "")
            if not title:
                continue

            venue_name     = d.get("venue_name") or card.get("venue_name") or ""
            city_location  = d.get("city_location", "")
            loc_parts      = [p.strip() for p in city_location.split(",")] if city_location else []
            city           = loc_parts[0] if loc_parts else ""
            country        = loc_parts[-1] if len(loc_parts) >= 2 else ""
            organizer      = d.get("organizer_name") or card.get("organizer_name") or ""
            organizer_url  = d.get("organizer_url") or ""
            start_raw      = d.get("start_datetime") or card.get("start_datetime")
            external_id    = d.get("event_id") or card.get("event_id", "")
            description    = d.get("description") or card.get("short_description") or ""
            image_url      = d.get("image_url") or ""
            # Scan description text + all non-FB anchor hrefs for a registration link.
            extra_links    = " ".join(d.get("links") or [])
            registration_url = find_registration_url(description + " " + extra_links)

            venue = (
                ScrapedVenue(
                    name=venue_name,
                    city=city,
                    country=country,
                )
                if venue_name
                else None
            )

            yield ScrapedEvent(
                name=title,
                description=description,
                image_url=image_url,
                registration_url=registration_url,
                starts_at=_parse_fb_date(start_raw),
                url=event_url,
                external_id=external_id,
                source_url=search_url,
                organizer=organizer,
                organizer_url=organizer_url,
                venue=venue,
            )
            processed += 1
            logger.info(
                "[%s] (%d/%d) %s | venue=%s | organizer=%s | img=%s | desc=%d chars | reg=%s",
                self.source, processed, len(cards),
                title,
                venue_name or "—",
                organizer or "—",
                "yes" if image_url else "no",
                len(description),
                _sanitize_url(registration_url) if registration_url else "—",
            )

    # ── Organizer page scrape ─────────────────────────────────────────────────

    def _fetch_organizer_page(self, page, url: str) -> dict:
        """Visit an organizer's FB page and extract contact details."""
        try:
            self._goto(page, url)
        except Exception as exc:
            logger.warning("organizer page load failed %s: %s", url, exc)
            return {}
        _pause(1.5, 3.0)
        page.evaluate(_DISMISS_MODAL_JS)
        try:
            return page.evaluate(_EXTRACT_ORGANIZER_JS) or {}
        except Exception as exc:
            logger.warning("organizer JS eval failed %s: %s", url, exc)
            return {}

    # ── BaseScraper overrides ─────────────────────────────────────────────────

    def fetch(self) -> Iterable[ScrapedEvent]:
        # fetch() is intentionally empty; run() drives the loop so we can do
        # per-SearchQuery FK updates. Direct callers of fetch() get nothing.
        return iter([])

    def run(
        self,
        query_id: int | None = None,
        query_ids: list[int] | None = None,
        locations: list[str] | None = None,
        max_events: int | None = None,
    ) -> dict:
        """Run the scraper for active SearchQuery rows.

        Loads all active SearchQuery rows by default (no source filter, since
        keywords are scraper-agnostic). Pass ``query_ids`` to restrict to a
        specific subset, or ``query_id`` for a single-query run (backwards
        compat). ``query_ids`` takes precedence when both are supplied.

        Django ORM calls are deliberately kept OUTSIDE the sync_playwright() block.
        Playwright's sync API runs its own event loop internally; Django detects that
        as an async context and raises SynchronousOnlyOperation if ORM is called inside.
        """
        from django.db import models
        from django.utils import timezone
        from events.models import Event, SearchQuery

        # ── 1. Load queries (ORM outside playwright) ──────────────────────────
        qs = SearchQuery.objects.filter(is_active=True)
        if query_ids:
            qs = qs.filter(pk__in=query_ids)
        elif query_id:
            qs = qs.filter(pk=query_id)
        queries = list(qs)
        if not queries:
            logger.info("[%s] no active search queries — nothing to do.", self.source)
            return {"source": self.source, "created": 0, "updated": 0}

        # Fan out queries × locations. Without locations, behaviour is unchanged.
        active_locs = locations or []
        if active_locs:
            work_items = [(sq, loc) for sq in queries for loc in active_locs]
        else:
            work_items = [(sq, "") for sq in queries]

        # ── 2. Scrape (inside playwright, no ORM) ─────────────────────────────
        # Phase 2a: scrape event cards + detail pages.
        # Phase 2b: visit each unique organizer FB page for enriched contact data.
        # No Django ORM calls inside this block.
        scraped: dict[int, list] = {}
        # url -> {name, email, phone, website, description, address}
        org_details: dict[str, dict] = {}

        with sync_playwright() as pw:
            browser, context = self._browser_context(pw)
            page = context.new_page()
            Stealth().use_sync(page)
            self._block_heavy_resources(page)
            try:
                # 2a — events
                for sq, location_suffix in work_items:
                    effective_term = f"{sq.query} {location_suffix}".strip()
                    try:
                        cards = list(self._fetch_for_query(page, effective_term, max_events=max_events))
                        bucket = scraped.setdefault(sq.id, [])
                        bucket.extend(cards)
                        n = len(cards)
                        with_img  = sum(1 for e in cards if e.image_url)
                        with_desc = sum(1 for e in cards if e.description)
                        logger.info(
                            "[%s] search '%s' done: %d events, %d with image, %d with description",
                            self.source, effective_term, n, with_img, with_desc,
                        )
                    except Exception as exc:
                        logger.warning("[%s] search '%s' failed, skipping: %s", self.source, effective_term, exc)
                        scraped.setdefault(sq.id, [])
                    _pause(3.0, 6.0)

                # 2b — organizer pages
                all_events_flat = [e for evts in scraped.values() for e in evts]
                seen_org_urls: set[str] = set()
                for se in all_events_flat:
                    url = (se.organizer_url or "").rstrip("/")
                    if not url or url in seen_org_urls:
                        continue
                    seen_org_urls.add(url)
                    logger.info("[%s] visiting organizer page: %s", self.source, url)
                    details = self._fetch_organizer_page(page, url)
                    # Merge: use scraped organizer name if page didn't return one
                    if not details.get("name"):
                        details["name"] = se.organizer
                    org_details[url] = details
                    _pause(2.0, 4.0)
            finally:
                context.close()
                browser.close()

        # ── 3. Persist (ORM outside playwright) ───────────────────────────────

        # Upsert organizers first so save_events() can resolve organizer_ref FK.
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
            # external_id: slug from path, or numeric id for profile.php?id= URLs
            if "profile.php" in url:
                m = re.search(r'[?&]id=(\d+)', url)
                external_id = m.group(1) if m else ""
            else:
                external_id = url.rstrip("/").split("/")[-1] if url else ""
            # Enrich with data fetched from the organizer's FB page
            d = org_details.get(url, {})
            scraped_orgs.append(ScrapedOrganizer(
                name=d.get("name") or name,
                # website MUST be the FB URL so _resolve_organizer() can match it
                # against Organizer.website when save_events() runs.
                # The external website (if found) goes into source_url for reference.
                website=url,
                email=d.get("email") or "",
                phone=d.get("phone") or "",
                address=d.get("address") or "",
                description=d.get("description") or "",
                facebook_url=url,
                external_id=external_id,
                source_url=d.get("website") or "",
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

            SearchQuery.objects.filter(pk=sq.pk).update(
                last_run_at=timezone.now(),
                events_found_count=models.F("events_found_count") + result["created"] + result["updated"],
                updated_at=timezone.now(),
            )

            total_created += result["created"]
            total_updated += result["updated"]
            logger.info(
                "[%s] saved query '%s': %d created, %d updated",
                self.source, sq.query, result["created"], result["updated"],
            )

        logger.info(
            "[%s] run complete — %d queries, %d created, %d updated",
            self.source, len(queries), total_created, total_updated,
        )
        return {
            "source": self.source,
            "created": total_created,
            "updated": total_updated,
        }
