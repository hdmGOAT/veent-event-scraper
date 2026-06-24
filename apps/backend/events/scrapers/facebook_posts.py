"""Facebook Posts scraper — mirrors veent-fb-scraper posts flow.

Navigates to Facebook group pages, FB pages, or FB post-search results and
extracts unstructured posts. Uses the Claude CLI (same pattern as ai_categories.py)
to determine if a post is an event and extract structured fields.

Reuses all browser infrastructure from FacebookEventsScraper (proxy, stealth,
modal dismissal, resource blocking, organizer page enrichment) via subclassing.
Reuses link detection from registration_patterns.py.

SearchQuery.query (source='facebook_posts') can be:
  - A full FB group URL:  https://www.facebook.com/groups/123456789
  - A FB page URL:        https://www.facebook.com/somepage
  - A search keyword:     "events cebu"  (→ /search/posts?q=...)

Flow mirrors veent-fb-scraper:
  content-posts.js  → _EXPAND_SEE_MORE_JS + _EXTRACT_POSTS_JS
  events-posts.js   → _is_eligible + _call_claude_structure + persist
  llm.js            → _build_post_prompt + _parse_structure_response
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import urllib.parse
from datetime import datetime, timezone as dt_timezone
from typing import Iterable

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from .base import ScrapedEvent, ScrapedOrganizer, ScrapedVenue, save_events, save_organizers
from .facebook_events import (
    FacebookEventsScraper,
    _DISMISS_MODAL_JS,
    _EXTRACT_ORGANIZER_JS,
    _pause,
    _human_scroll,
    _parse_fb_date,
)
from events.registration_patterns import find_registration_url

logger = logging.getLogger(__name__)

# ── Keyword pre-filters (mirrors veent-fb-scraper server/routes/events-posts.js) ─

_RESALE_RE = re.compile(
    r'\b(wts|wtb|wtt|lfs|lfb|lft|passaway|pasabay)\b'
    r'|ticket[s]?\s+(for sale|transfer|resell|selling)'
    r'|selling\s+ticket',
    re.I,
)
_SLOP_RE = re.compile(
    r'^(rt @|📢\s*rt|share this|follow us|stream now|streaming now'
    r'|out now|listen now|pre[-\s]?order now|dropping|available now)',
    re.I,
)
_MIN_CAPTION_LEN = 20

# Contact fallback regexes (mirrors events-posts.js EMAIL_RE / PHONE_RE)
_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_PHONE_RE = re.compile(
    r'(?:\+?63[\s.\-]?|(?<!\d))(?:9\d{2}[\s.\-]?\d{3}[\s.\-]?\d{4}'
    r'|0\d{1,2}[\s.\-]?\d{3,4}[\s.\-]?\d{4})'
)

# Strings Claude may output instead of JSON null (mirrors llm.js NULL_LIKE)
_NULL_LIKE = frozenset([
    '', 'null', 'none', 'n/a', 'na', 'n.a.', 'nil', 'unknown',
    'not available', 'not found', 'not provided', 'not specified',
    '-', '—', '–', 'no', 'false',
])

# ── "See more" expander (mirrors content-posts.js expandSeeMore, synchronous) ─

_EXPAND_SEE_MORE_JS = """
() => {
    const candidates = [];
    for (const el of document.querySelectorAll('div[dir="auto"] span, div[dir="auto"] div')) {
        const txt = (el.innerText || el.textContent || '').trim();
        if (/^see more$/i.test(txt) && el.offsetParent !== null) candidates.push(el);
    }
    candidates.forEach(el => el.click());
    return candidates.length;
}
"""

# ── Post extraction JS (mirrors content-posts.js extractPosts()) ──────────────

_EXTRACT_POSTS_JS = r"""
() => {
    const MIN_CAPTION_LEN = 20;
    const GFORM_PATTERNS = [
        /https?:\/\/forms\.gle\/[A-Za-z0-9_-]+/i,
        /https?:\/\/docs\.google\.com\/forms\/d\/[A-Za-z0-9_/?=&.-]+/i,
        /https?:\/\/(?:tinyurl\.com|bit\.ly|rb\.gy|ow\.ly|cutt\.ly)\/[A-Za-z0-9_-]+/i,
    ];

    function isPostHref(href) {
        if (!href || /\/photo[/?]/.test(href) || /\/media\//.test(href)) return false;
        return (
            /\/(posts|permalink)\//.test(href) ||
            /\/groups\/[^/]+\/(posts|permalink)\//.test(href) ||
            /story\.php\?/.test(href) ||
            /[?&](post_id|story_fbid)=\d+/.test(href) ||
            /\/videos\/\d/.test(href)
        );
    }

    function toAbsolute(href) {
        return href.startsWith('http') ? href : 'https://www.facebook.com' + href;
    }

    // 4-strategy permalink finder (mirrors content-posts.js findPostUrl)
    function findPostUrl(card) {
        const timeEl = card.querySelector('time[datetime], abbr[data-utime]');
        if (timeEl) {
            const a = timeEl.closest('a[href]');
            if (a) {
                const href = a.getAttribute('href') || '';
                if (!href.startsWith('#')) return toAbsolute(href);
            }
            let node = timeEl.parentElement;
            for (let i = 0; i < 12; i++) {
                if (!node || node === document.body) break;
                const dh = node.getAttribute('data-href') || '';
                if (dh && isPostHref(dh)) return toAbsolute(dh);
                const rl = node.getAttribute('href') || '';
                if (rl && isPostHref(rl)) return toAbsolute(rl);
                node = node.parentElement;
            }
        }
        for (const a of card.querySelectorAll('a[href]')) {
            const href = a.getAttribute('href') || '';
            if (isPostHref(href)) return toAbsolute(href);
        }
        for (const el of card.querySelectorAll('[data-href]')) {
            const dh = el.getAttribute('data-href') || '';
            if (isPostHref(dh)) return toAbsolute(dh);
        }
        return null;
    }

    function findAuthorName(card) {
        const headingLink =
            card.querySelector('h2 a, h3 a, h4 a') ||
            card.querySelector('strong a, span strong');
        if (headingLink) {
            const txt = (headingLink.innerText || headingLink.textContent || '').trim();
            if (txt) return txt.split('\n')[0].trim();
        }
        return null;
    }

    // Unwrap l.facebook.com redirect links + scan for Google Forms / short URLs
    function findRegistrationLinks(card, captionText) {
        const found = new Set();
        for (const a of card.querySelectorAll('a[href]')) {
            const href = a.getAttribute('href') || '';
            let target = href;
            const m = href.match(/l\.facebook\.com\/l\.php\?u=([^&]+)/i);
            if (m) { try { target = decodeURIComponent(m[1]); } catch {} }
            for (const re of GFORM_PATTERNS) {
                const hit = target.match(re);
                if (hit) found.add(hit[0]);
            }
        }
        for (const re of GFORM_PATTERNS) {
            const hit = (captionText || '').match(re);
            if (hit) found.add(hit[0]);
        }
        return [...found];
    }

    // Prefer the longest div[dir="auto"] block (post body, not metadata)
    function findPostCaption(card) {
        const dirDivs = [...card.querySelectorAll('div[dir="auto"]')];
        if (dirDivs.length) {
            const texts = dirDivs
                .map(el => (el.innerText || '').trim())
                .filter(t => t.length >= MIN_CAPTION_LEN);
            if (texts.length) return texts.sort((a, b) => b.length - a.length)[0];
        }
        return (card.innerText || '').trim();
    }

    function hashCaption(str) {
        let h = 5381;
        const s = str.substring(0, 150);
        for (let i = 0; i < s.length; i++) { h = ((h << 5) + h) ^ s.charCodeAt(i); h |= 0; }
        return Math.abs(h).toString(16).padStart(8, '0');
    }

    // Walk up from a text node to find its post container div
    function findPostContainerFromNode(el) {
        const baseLen = (el.innerText || '').trim().length;
        const minLen  = Math.max(200, baseLen + 20);
        let node = el.parentElement;
        for (let i = 0; i < 25; i++) {
            if (!node || node === document.body) break;
            if (node.tagName === 'DIV' && (node.innerText || '').trim().length >= minLen) return node;
            node = node.parentElement;
        }
        return null;
    }

    const seen = new Set(), seenCards = new WeakSet(), seenCaptions = new Set(), posts = [];

    for (const textEl of document.querySelectorAll('div[dir="auto"]')) {
        if ((textEl.innerText || '').trim().length < MIN_CAPTION_LEN) continue;
        const card = findPostContainerFromNode(textEl);
        if (!card || seenCards.has(card)) continue;
        seenCards.add(card);

        const rawCaption = findPostCaption(card);
        if (rawCaption.length < MIN_CAPTION_LEN) continue;

        const captionPrefix = rawCaption.substring(0, 200);
        if (seenCaptions.has(captionPrefix)) continue;
        seenCaptions.add(captionPrefix);

        const realHref = findPostUrl(card);
        const href = realHref || ('https://www.facebook.com/fbpost/posts/synth_' + hashCaption(rawCaption));
        const dedupeKey = href.replace(/[?#].*$/, '');
        if (seen.has(dedupeKey)) continue;
        seen.add(dedupeKey);

        posts.push({
            post_url:    href,
            author_name: findAuthorName(card),
            raw_caption: rawCaption.substring(0, 2000),
            raw_links:   findRegistrationLinks(card, rawCaption),
        });
    }

    return posts;
}
"""

# ── Claude CLI structuring (mirrors veent-fb-scraper server/lib/llm.js) ───────

def _build_post_prompt(raw_caption: str, author_name: str | None, timestamp: str, raw_links: list[str]) -> str:
    links_str = "\n".join(f"  [{i+1}] {url}" for i, url in enumerate(raw_links)) if raw_links else "  (none)"
    return "\n".join([
        "You are an event-detection and information-extraction engine.",
        "You are given the raw text of a Facebook post. Your job has two parts:",
        "1. Decide whether the post is announcing a REAL upcoming live event.",
        "2. If it is, extract the event details.",
        "",
        'Set "is_event" to false if the post is:',
        "  - Selling or reselling tickets (WTS, WTB, WTT, passaway, for sale, ticket transfer)",
        "  - A fan post, reaction, or general comment about an event",
        "  - Announcing a streaming release, album drop, or digital content",
        "  - A retweet or quote with no new event information",
        "  - Too vague or unrelated to live events",
        "",
        'Set "is_event" to true only if the post directly announces an upcoming live event.',
        "",
        "IMPORTANT — for start_datetime:",
        f"  The post was collected at approximately: {timestamp}",
        "  Use this to resolve relative date phrases:",
        '    "this Sunday" → next Sunday after the collection date',
        '    "tomorrow" → one day after the collection date',
        '    "next week" → 7 days after the collection date',
        '  "start_datetime" is the EVENT date/time, NOT a ticket sale date.',
        '  Use ISO 8601 when known (e.g. "2026-05-10T21:00:00"), or a short phrase',
        '  when only partial info is available (e.g. "Sunday, May 10").',
        "",
        "For organizer_email: ONLY return an email LITERALLY present in the post text.",
        "  Do NOT invent or guess. Return JSON null if absent.",
        "",
        "For organizer_phone: ONLY return a phone number LITERALLY present in the post.",
        "  Philippine formats: 09XXXXXXXXX, +639XXXXXXXXX, (02) XXXX-XXXX.",
        "  Return JSON null if absent.",
        "",
        "For registration_url: check the LINKS list below.",
        "  Return the first link that looks like a registration/sign-up page",
        "  (Google Forms, Eventbrite, Luma, Typeform, Jotform, bit.ly wrapping a form, etc.).",
        "  Return JSON null if none found.",
        "",
        "IMPORTANT: output JSON null — never the strings 'none', 'N/A', 'unknown', or '-'.",
        "",
        "Respond with ONLY a single JSON object, no prose, no markdown, no code fences.",
        "JSON keys:",
        '  "is_event"          - boolean',
        '  "title"             - event name/title (null if is_event is false)',
        '  "start_datetime"    - event start date/time (null if unknown)',
        '  "venue_name"        - venue/place name (null if unknown)',
        '  "city_location"     - city or location (null if unknown)',
        '  "organizer_name"    - organizer/host name (null if unknown)',
        '  "organizer_email"   - contact email (null if none)',
        '  "organizer_phone"   - contact phone (null if none)',
        '  "short_description" - one-sentence event summary (null if is_event is false)',
        '  "registration_url"  - registration URL (null if none)',
        "",
        f"Post author: {author_name or '(unknown)'}",
        "Post text:",
        '"""',
        raw_caption,
        '"""',
        "",
        "LINKS found in the post:",
        links_str,
        "",
        "Respond with ONLY the JSON object.",
    ])


def _coerce_str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return None if s.lower() in _NULL_LIKE else s


def _parse_structure_response(stdout: str) -> dict | None:
    """Extract and coerce the JSON object from Claude CLI output."""
    m = re.search(r'\{[\s\S]*\}', (stdout or "").strip())
    if not m:
        return None
    try:
        parsed = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return {
        "is_event":          parsed.get("is_event") is True or str(parsed.get("is_event", "")).lower() == "true",
        "title":             _coerce_str(parsed.get("title")),
        "start_datetime":    _coerce_str(parsed.get("start_datetime")),
        "venue_name":        _coerce_str(parsed.get("venue_name")),
        "city_location":     _coerce_str(parsed.get("city_location")),
        "organizer_name":    _coerce_str(parsed.get("organizer_name")),
        "organizer_email":   _coerce_str(parsed.get("organizer_email")),
        "organizer_phone":   _coerce_str(parsed.get("organizer_phone")),
        "short_description": _coerce_str(parsed.get("short_description")),
        "registration_url":  _coerce_str(parsed.get("registration_url")),
    }


def _call_llm_structure(
    raw_caption: str,
    author_name: str | None,
    timestamp: str,
    raw_links: list[str],
) -> dict | None:
    """Call Ollama to structure a raw FB post caption into event fields.

    Configurable via env vars (set in .env or shell):
      OLLAMA_BASE     Ollama server URL  (default: http://localhost:11434)
      OLLAMA_MODEL    Model to use       (default: llama3.2:3b)
      OLLAMA_TIMEOUT  Request timeout s  (default: 90)

    Returns the parsed dict on success, None if Ollama is unreachable or
    the model returns unparseable output (caller falls back to a minimal record).
    """
    import urllib.request
    import urllib.error

    base    = os.environ.get("OLLAMA_BASE",    "http://localhost:11434")
    model   = os.environ.get("OLLAMA_MODEL",   "llama3.2:3b")
    timeout = int(os.environ.get("OLLAMA_TIMEOUT", "90"))

    prompt  = _build_post_prompt(raw_caption, author_name, timestamp, raw_links)
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()

    req = urllib.request.Request(
        f"{base}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        text   = data.get("response", "")
        result = _parse_structure_response(text)
        if result is None:
            logger.warning(
                "[facebook_posts] Ollama (%s) returned unparseable output for: %s…",
                model, raw_caption[:60],
            )
        return result
    except urllib.error.URLError as exc:
        logger.warning(
            "[facebook_posts] Ollama unreachable at %s — is `ollama serve` running? (%s)",
            base, exc.reason,
        )
        return None
    except Exception as exc:
        logger.warning("[facebook_posts] Ollama structuring failed (%s/%s): %s", base, model, exc)
        return None


# Keep the old name as an alias so any other callers aren't broken.
_call_claude_structure = _call_llm_structure


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_contact_fallback(caption: str) -> dict:
    """Regex fallback to fill email/phone gaps the LLM missed."""
    text = caption or ""
    email_m = _EMAIL_RE.search(text)
    phone_m = _PHONE_RE.search(text)
    return {
        "email": email_m.group(0).strip() if email_m else None,
        "phone": phone_m.group(0).strip() if phone_m else None,
    }


def _is_eligible(caption: str) -> bool:
    if not caption or len(caption) < _MIN_CAPTION_LEN:
        return False
    if _RESALE_RE.search(caption):
        return False
    if _SLOP_RE.match(caption):
        return False
    return True


def _parse_post_date(raw: str | None) -> datetime | None:
    """Try ISO 8601 first, then fall back to FB human-readable formats.
    Always returns timezone-aware datetimes (defaults to UTC).
    """
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)
        return dt
    except ValueError:
        pass
    start_dt, _ = _parse_fb_date(raw)
    if start_dt is not None and start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=dt_timezone.utc)
    return start_dt


def _post_external_id(post_url: str) -> str:
    """Derive a stable dedup key from the post URL.

    Query params are preserved because story.php?story_fbid=123 and
    story.php?story_fbid=456 have the same path but are distinct posts.
    """
    # Keep everything after facebook.com/ including query string
    after_domain = post_url.split("facebook.com/")[-1].strip("/")
    return after_domain.replace("/", "_") or post_url[-40:]


# ── Scraper ───────────────────────────────────────────────────────────────────

class FacebookPostsScraper(FacebookEventsScraper):
    """Scrape unstructured Facebook group/page posts and extract events via Claude.

    Inherits browser setup, proxy, stealth, modal dismissal, resource blocking,
    and organizer page enrichment from FacebookEventsScraper. Adds post-specific
    extraction JS and Claude CLI structuring.

    Authentication (required — FB does not render post content to logged-out sessions):
      Set FB_COOKIES_FILE to a JSON file of exported Facebook cookies.
      Export from Chrome/Firefox using the "Cookie Editor" browser extension (→ Export All).
      The file must be a JSON array of cookie objects with at least: name, value, domain.

    SearchQuery.query examples (source='facebook_posts'):
      https://www.facebook.com/groups/123456789   ← public group
      https://www.facebook.com/somepage           ← public page
      events cebu                                  ← keyword → /search/posts?q=...
    """

    source = "facebook_posts"

    def fetch(self) -> Iterable[ScrapedEvent]:
        return iter([])

    def _wait_for_2fa(self, page) -> bool:
        """Block until the user completes 2FA in the visible browser (FB_HEADLESS=false).

        Polls the page URL every second — no API calls that could throw mid-navigation.
        Only exits early if the browser is explicitly disconnected/closed.
        """
        import time as _time
        headless = os.environ.get("FB_HEADLESS", "true").lower() != "false"
        if headless:
            logger.warning(
                "[%s] 2FA checkpoint at %s but FB_HEADLESS=true. "
                "Set FB_HEADLESS=false and re-run to complete 2FA in the browser window. "
                "After that the FB_PROFILE_DIR session will stay authenticated.",
                self.source, page.url[:80],
            )
            return False
        logger.info(
            "[%s] 2FA / checkpoint detected. "
            "Complete the verification in the browser window — waiting up to 3 minutes...",
            self.source,
        )
        _AUTH_BLOCKLIST = {"login", "two_step_verification", "checkpoint", "about:blank"}

        for tick in range(180):
            _time.sleep(1)
            try:
                current_url = page.url
            except Exception as exc:
                err = str(exc).lower()
                if any(w in err for w in ("closed", "disconnected", "destroyed")):
                    logger.warning("[%s] browser disconnected during 2FA wait: %s", self.source, exc)
                    return False
                # transient Playwright error mid-navigation — keep polling
                logger.debug("[%s] poll tick %d exception (retrying): %s", self.source, tick, exc)
                continue

            # Navigated away from all auth/checkpoint pages → login complete
            if (
                "facebook.com" in current_url
                and not any(w in current_url for w in _AUTH_BLOCKLIST)
            ):
                logger.info("[%s] 2FA completed — now at %s", self.source, current_url[:60])
                _pause(1.5, 2.5)
                return True

            if tick % 20 == 0 and tick > 0:
                logger.info("[%s] still waiting for 2FA... (%ds elapsed, url=%s)", self.source, tick, current_url[:60])

        logger.warning("[%s] 2FA timeout — verification not completed within 3 minutes.", self.source)
        return False

    def _login_with_credentials(self, page) -> bool:
        """Ensure the browser is authenticated via ACC_EMAIL / ACC_PASSWORD.

        State machine:
          1. Already logged in (c_user cookie present) → return True immediately.
          2. At a 2FA / checkpoint URL (from a previous partial login) → wait for
             the user to complete it in the visible browser window.
          3. At the login form → fill credentials, submit, then handle 2FA if needed.
        Returns True when c_user is confirmed, False on failure.
        """
        email    = os.environ.get("ACC_EMAIL", "")
        password = os.environ.get("ACC_PASSWORD", "")
        if not email or not password:
            logger.warning(
                "[%s] ACC_EMAIL / ACC_PASSWORD not set — no auth, posts will be empty.",
                self.source,
            )
            return False

        try:
            # ── 1. Check if already logged in (persistent profile may have valid session) ──
            if any(c["name"] == "c_user" for c in page.context.cookies()):
                logger.info("[%s] already authenticated (persistent profile active)", self.source)
                return True

            # ── 2. Fill the login form ─────────────────────────────────────────
            logger.info("[%s] authenticating as %s", self.source, email)
            page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=40_000)
            _pause(2.0, 3.5)

            # Profile may have resumed at a 2FA checkpoint from a previous run
            if "two_step_verification" in page.url or "checkpoint" in page.url:
                return self._wait_for_2fa(page)

            logger.info("[%s] login page url=%s title=%s", self.source, page.url[:80], page.title()[:60])
            page.evaluate(_DISMISS_MODAL_JS)
            _pause(0.8, 1.2)

            _EMAIL_SELS = ["#email", 'input[name="email"]', 'input[type="email"]', '[data-testid="royal_email"]']
            _PASS_SELS  = ["#pass",  'input[name="pass"]',  'input[type="password"]']

            email_filled = False
            for sel in _EMAIL_SELS:
                try:
                    page.wait_for_selector(sel, state="visible", timeout=6_000)
                    page.fill(sel, email)
                    email_filled = True
                    break
                except Exception:
                    continue

            if not email_filled:
                logger.warning(
                    "[%s] email input not found on login page (url=%s) — check proxy or page load",
                    self.source, page.url[:80],
                )
                return False

            _pause(0.4, 0.8)
            for sel in _PASS_SELS:
                try:
                    page.wait_for_selector(sel, state="visible", timeout=6_000)
                    page.fill(sel, password)
                    break
                except Exception:
                    continue

            _pause(0.4, 0.8)
            page.keyboard.press("Enter")

            try:
                page.wait_for_url(
                    lambda url: "facebook.com/login" not in url,
                    timeout=20_000,
                )
            except Exception:
                pass
            _pause(2.0, 3.0)

            # ── 3. Post-submit: 2FA or success ────────────────────────────────
            if "two_step_verification" in page.url or "checkpoint" in page.url:
                return self._wait_for_2fa(page)

            logged_in = any(c["name"] == "c_user" for c in page.context.cookies())
            if logged_in:
                logger.info("[%s] login successful for %s (url=%s)", self.source, email, page.url[:60])
            else:
                logger.warning(
                    "[%s] login failed — c_user absent (url=%s). Check credentials.",
                    self.source, page.url[:60],
                )
            return logged_in

        except Exception as exc:
            logger.warning("[%s] credential login error: %s", self.source, exc)
            return False

    def _load_fb_cookies(self, context) -> int:
        """Load FB session cookies from FB_COOKIES_FILE into the browser context.

        Accepts two formats:
          - Netscape cookies.txt  (exported by "Get cookies.txt LOCALLY" Chrome ext)
          - JSON array            (exported by "Cookie Editor" Chrome ext)

        Returns the number of cookies loaded, or 0 if not configured / on error.
        """
        cookies_file = os.environ.get("FB_COOKIES_FILE", "")
        if not cookies_file:
            return 0
        try:
            path = os.path.expanduser(cookies_file)
            with open(path, encoding="utf-8") as f:
                text = f.read()

            cookies: list[dict] = []

            if text.lstrip().startswith("# Netscape"):
                # ── Netscape / cookies.txt format ──────────────────────────────
                # Columns (tab-separated): domain  flag  path  secure  expiry  name  value
                for line in text.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) < 7:
                        continue
                    domain, _flag, path_, secure, expiry, name, value = parts[:7]
                    cookies.append({
                        "name":     name,
                        "value":    value,
                        "domain":   domain,
                        "path":     path_ or "/",
                        "expires":  float(expiry) if expiry and expiry != "0" else -1,
                        "httpOnly": False,
                        "secure":   secure.upper() == "TRUE",
                        "sameSite": "None",
                    })
            else:
                # ── JSON / Cookie Editor format ────────────────────────────────
                raw = json.loads(text)
                for c in raw:
                    if not isinstance(c, dict) or not c.get("name") or not c.get("domain"):
                        continue
                    same_site = str(c.get("sameSite", "None")).capitalize()
                    if same_site not in ("Strict", "Lax", "None"):
                        same_site = "None"
                    cookies.append({
                        "name":     c["name"],
                        "value":    str(c.get("value", "")),
                        "domain":   c["domain"],
                        "path":     c.get("path", "/"),
                        "expires":  float(c.get("expirationDate") or c.get("expires") or -1),
                        "httpOnly": bool(c.get("httpOnly", False)),
                        "secure":   bool(c.get("secure", False)),
                        "sameSite": same_site,
                    })

            if not cookies:
                logger.warning("[%s] FB_COOKIES_FILE %s parsed but contained no cookies", self.source, cookies_file)
                return 0

            context.add_cookies(cookies)
            logger.info("[%s] loaded %d cookies from %s", self.source, len(cookies), cookies_file)
            return len(cookies)
        except Exception as exc:
            logger.warning("[%s] failed to load FB_COOKIES_FILE %s: %s", self.source, cookies_file, exc)
            return 0

    def _navigate_to_query(self, page, query: str) -> None:
        """Go to a FB group/page URL directly, or to /search/posts for keywords.

        For page/profile URLs we append /posts so FB shows the timeline feed
        directly and avoids right-rail sidebar content polluting the extraction.
        Groups already include /posts in their URL structure so they're left as-is.
        """
        if re.match(r'https?://', query, re.I):
            url = query.rstrip("/")
            # Page URLs: append /posts to target the posts tab specifically
            if "/groups/" not in url and not url.endswith("/posts"):
                url = url + "/posts"
            self._goto(page, url)
        else:
            search_url = "https://www.facebook.com/search/posts?q=" + urllib.parse.quote(query)
            self._goto(page, search_url)

    def _fetch_raw_posts(self, page, query: str, max_posts: int | None = None) -> list[dict]:
        """Navigate, dismiss modal, expand "See more", scroll, and extract posts."""
        self._navigate_to_query(page, query)
        _pause(3.0, 5.0)

        page.evaluate(_DISMISS_MODAL_JS)
        _pause(1.0, 2.0)

        # Wait for post content: logged-in session shows posts in dir="auto" containers.
        # Unauthenticated sessions show 0 posts here; the wait exits on timeout.
        try:
            page.wait_for_selector('[role="article"] div[dir="auto"]', timeout=12_000)
        except Exception:
            pass

        page.evaluate(_EXPAND_SEE_MORE_JS)
        _pause(0.5, 1.0)

        _human_scroll(page)
        page.evaluate(_DISMISS_MODAL_JS)
        _pause(1.0, 2.0)
        page.evaluate(_EXPAND_SEE_MORE_JS)
        _pause(0.3, 0.7)

        logger.info("[%s] page: %s | title: %s", self.source, page.url[:80], page.title()[:60])
        raw_posts: list[dict] = page.evaluate(_EXTRACT_POSTS_JS)
        logger.info("[%s] '%s': %d raw posts extracted", self.source, query[:60], len(raw_posts))

        if max_posts is not None:
            raw_posts = raw_posts[:max_posts]
        return raw_posts

    supports_keywords = False

    def run(self, query_id: int | None = None, max_events: int | None = None) -> dict:
        from django.db import models as dj_models
        from django.utils import timezone
        from events.models import Event, SearchQuery

        # 1. Load queries (ORM outside Playwright block)
        qs = SearchQuery.objects.filter(is_active=True)
        if query_id:
            qs = qs.filter(pk=query_id)
        queries = list(qs)
        if not queries:
            logger.info("[%s] no active search queries — nothing to do.", self.source)
            return {"source": self.source, "created": 0, "updated": 0}

        # 2. Scrape raw posts (Playwright block — no Django ORM inside)
        raw_by_query: dict[int, list[dict]] = {}

        with sync_playwright() as pw:
            # Persistent profile (FB_PROFILE_DIR) keeps the session between runs so
            # 2FA only needs to be completed once.  Falls back to a normal context.
            profile_dir = os.environ.get("FB_PROFILE_DIR", "")
            if profile_dir:
                os.makedirs(profile_dir, exist_ok=True)
                headless = os.environ.get("FB_HEADLESS", "true").lower() != "false"
                proxy    = self._resolve_proxy()
                ctx_kw   = dict(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    ),
                    locale="en-US",
                    timezone_id="Asia/Manila",
                )
                if proxy:
                    ctx_kw["proxy"] = proxy
                logger.info("[%s] using persistent profile: %s", self.source, profile_dir)
                context = pw.chromium.launch_persistent_context(
                    profile_dir,
                    headless=headless,
                    args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-sandbox"],
                    **ctx_kw,
                )
                browser = None
            else:
                browser, context = self._browser_context(pw)

            cookie_count = self._load_fb_cookies(context)
            page = context.new_page()
            Stealth().use_sync(page)
            # NOTE: resource blocking is applied AFTER auth so CAPTCHA images load.
            if cookie_count == 0:
                self._login_with_credentials(page)
            self._block_heavy_resources(page)
            try:
                for sq in queries:
                    try:
                        raw_by_query[sq.id] = self._fetch_raw_posts(
                            page, sq.query, max_posts=max_events,
                        )
                    except Exception as exc:
                        logger.warning("[%s] query '%s' failed: %s", self.source, sq.query, exc)
                        raw_by_query[sq.id] = []
                    _pause(3.0, 6.0)
            finally:
                context.close()
                if browser:
                    browser.close()

        # 3. Structure posts via Claude CLI + persist (ORM outside Playwright)
        total_created = total_updated = 0

        for sq in queries:
            scraped_events: list[ScrapedEvent] = []
            scraped_orgs:   list[ScrapedOrganizer] = []
            collected_at = timezone.now().isoformat()

            for raw in raw_by_query.get(sq.id, []):
                caption   = raw.get("raw_caption", "")
                post_url  = raw.get("post_url", "")
                author    = raw.get("author_name") or ""
                raw_links = raw.get("raw_links") or []

                if not _is_eligible(caption):
                    logger.debug("[%s] SKIP pre-filter: %s", self.source, post_url[:60])
                    continue

                # Deterministic registration URL check before hitting the LLM
                direct_reg = find_registration_url(caption + " " + " ".join(raw_links))

                structured = _call_llm_structure(caption, author, collected_at, raw_links)

                if structured is not None and not structured["is_event"]:
                    logger.debug("[%s] SKIP not event: %s", self.source, post_url[:60])
                    continue

                # Fallback fields when Claude is offline or returned None
                fields = structured or {
                    "is_event": True, "title": None, "start_datetime": None,
                    "venue_name": None, "city_location": None,
                    "organizer_name": None, "organizer_email": None,
                    "organizer_phone": None, "short_description": None,
                    "registration_url": None,
                }

                # registration_url: LLM result → deterministic direct match → empty
                registration_url = fields.get("registration_url") or direct_reg or ""

                # Contact info: LLM first, regex fallback fills gaps
                contact_fb    = _extract_contact_fallback(caption)
                organizer_email = fields.get("organizer_email") or contact_fb["email"] or ""
                organizer_phone = fields.get("organizer_phone") or contact_fb["phone"] or ""

                title          = fields.get("title") or (f"{author}: {caption[:80]}" if author else caption[:80])
                organizer_name = fields.get("organizer_name") or author or ""

                city_raw  = fields.get("city_location") or ""
                loc_parts = [p.strip() for p in city_raw.split(",")] if city_raw else []
                city      = loc_parts[0] if loc_parts else ""
                country   = loc_parts[-1] if len(loc_parts) >= 2 else ""

                venue = (
                    ScrapedVenue(name=fields["venue_name"], city=city, country=country)
                    if fields.get("venue_name") else None
                )

                external_id = _post_external_id(post_url)

                scraped_events.append(ScrapedEvent(
                    name=title,
                    description=fields.get("short_description") or caption[:500],
                    starts_at=_parse_post_date(fields.get("start_datetime")),
                    url=post_url,
                    registration_url=registration_url,
                    external_id=external_id,
                    source_url=sq.query,
                    organizer=organizer_name,
                    venue=venue,
                ))

                if organizer_name:
                    scraped_orgs.append(ScrapedOrganizer(
                        name=organizer_name,
                        email=organizer_email,
                        phone=organizer_phone,
                    ))

                logger.info(
                    "[%s] %s | title=%s | org=%s | email=%s | phone=%s | reg=%s",
                    self.source, post_url[:60],
                    (title or "")[:40],
                    organizer_name[:30] if organizer_name else "—",
                    "present" if organizer_email else "—",
                    "present" if organizer_phone else "—",
                    registration_url or "—",
                )

            if scraped_orgs:
                save_organizers(self.source, scraped_orgs)

            result = save_events(self.source, scraped_events)

            Event.objects.filter(
                pk__in=result.get("event_ids", []),
                search_query__isnull=True,
            ).update(search_query=sq)

            SearchQuery.objects.filter(pk=sq.pk).update(
                last_run_at=timezone.now(),
                events_found_count=dj_models.F("events_found_count") + result["created"] + result["updated"],
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
        return {"source": self.source, "created": total_created, "updated": total_updated}
