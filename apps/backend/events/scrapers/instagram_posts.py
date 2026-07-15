"""Instagram Posts scraper — cookie-authenticated, proxy-backed.

Flow (mirrors facebook_events.py):
  1. Load session cookies from www.instagram.com_cookies.txt (Netscape format).
  2. Launch headless Chromium via DataImpulse residential proxy (if configured).
  3. For every active SearchQuery where source='instagram_posts':
       a. Navigate to https://www.instagram.com/explore/tags/<hashtag>/
       b. Scroll in a humanised pattern to trigger IG's infinite scroll.
       c. Extract post URLs and captions from the page (grid or article elements).
          Instagram populates img[alt] with the post caption for accessibility —
          this works on both grid (explore/tags) and article (feed) views even
          when image resources are blocked.
  4. Save via the shared save_events() pipeline and link to the SearchQuery.

Cookie file (Netscape format, exported with "Cookie Editor" extension):
    IG_COOKIES_FILE    path to www.instagram.com_cookies.txt
                       (default: www.instagram.com_cookies.txt relative to manage.py)

Other env vars:
    IG_HEADLESS        set to "false" to watch the browser (default: true)
    DATAIMPULSE_USER   DataImpulse proxy username  (optional but recommended)
    DATAIMPULSE_PASS   DataImpulse proxy password
    DATAIMPULSE_HOST   default: gw.dataimpulse.com
    DATAIMPULSE_PORT   default: 823

SearchQuery setup:
    Create SearchQuery rows in the admin with source='instagram_posts' and
    query set to the hashtag WITHOUT the leading # (e.g. 'manilaevents').
    These are separate from the Facebook keyword queries.
"""
from __future__ import annotations

import logging
import os
import random
import re
import time
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import quote as _urlquote

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from .base import BaseScraper, ScrapedEvent, ScrapedOrganizer, ScrapedVenue, SessionExpiredError, save_events, save_organizers
from .facebook_posts import (
    _call_llm_structure,
    _is_eligible,
    _extract_contact_fallback,
    _parse_post_date,
)
from events.registration_patterns import find_registration_url

logger = logging.getLogger(__name__)

_IG_BASE = "https://www.instagram.com"
_TAG_URL  = _IG_BASE + "/explore/tags/{hashtag}/"

# Block images/media/fonts — img[alt] captions are in the HTML markup, so
# we still get full captions without loading any image files.
_BLOCK_TYPES = {"image", "media", "font"}


# ── Cookie loading ────────────────────────────────────────────────────────────

def _load_netscape_cookies(path: str | Path) -> list[dict]:
    """Parse a Netscape-format cookie file into Playwright cookie dicts."""
    cookies = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            domain, _include_sub, ck_path, secure, expiry, name, value = parts[:7]
            try:
                expires = float(expiry) if expiry and expiry not in ("0", "") else -1.0
            except ValueError:
                expires = -1.0
            cookies.append({
                "name":     name,
                "value":    value,
                "domain":   domain,
                "path":     ck_path,
                "expires":  expires,
                "httpOnly": False,
                "secure":   secure.upper() == "TRUE",
                "sameSite": "None",
            })
    return cookies


# ── JS injected into the page ─────────────────────────────────────────────────

_EXTRACT_POSTS_JS = r"""
() => {
    const posts = [];
    const seen  = new Set();

    function isPostHref(href) {
        return /^\/(p|reel|tv)\/[A-Za-z0-9_-]+/.test(href);
    }

    // Instagram embeds the full caption in img[alt] for accessibility.
    // It also includes the author handle in the format:
    //   "Photo by @handle on Instagram: caption text..."
    // We extract both the handle and the actual caption from this string.
    function parseAlt(altText) {
        const text  = (altText || '').trim();
        const byRe  = /^(?:Photo|Video|Reel)\s+by\s+@([\w.]+)\s+on\s+Instagram(?::\s*)?/i;
        const m     = text.match(byRe);
        const handle = m ? '@' + m[1] : null;
        const caption = m ? text.slice(m[0].length).trim() : text;
        return { handle, caption };
    }

    // ── Strategy 1: article elements (home feed / profile list view) ──────────
    // Article elements contain the full post card including author link and
    // timestamp — richer data than the grid strategy below.
    for (const article of document.querySelectorAll('article')) {
        let postUrl = null;
        for (const a of article.querySelectorAll('a[href]')) {
            const href = a.getAttribute('href') || '';
            if (isPostHref(href)) { postUrl = 'https://www.instagram.com' + href; break; }
        }
        if (!postUrl) continue;

        const sc = postUrl.match(/\/(p|reel|tv)\/([A-Za-z0-9_-]+)/)?.[2];
        if (!sc || seen.has(sc)) continue;
        seen.add(sc);

        const img = article.querySelector('img[alt]');
        const { handle: altHandle, caption: altCaption } = img
            ? parseAlt(img.getAttribute('alt') || '')
            : { handle: null, caption: '' };

        // Prefer article-level author link over the img[alt] handle — it's
        // more reliable on the home feed where the link is always present.
        let authorHandle = null;
        for (const a of article.querySelectorAll('a[href^="/"]')) {
            const href = a.getAttribute('href') || '';
            if (!isPostHref(href) && /^\/[A-Za-z0-9._]+\/?$/.test(href)) {
                authorHandle = '@' + href.replace(/\//g, '');
                break;
            }
        }
        authorHandle = authorHandle || altHandle;

        // Full caption text — fallback to longest visible text block if img[alt]
        // only has the author prefix.
        let caption = altCaption;
        if (!caption) {
            let best = '';
            for (const el of article.querySelectorAll('span, div')) {
                const t = (el.innerText || '').trim();
                if (t.length > best.length && t.length >= 30) best = t;
            }
            caption = best;
        }

        // Image URL — src attribute is set by IG's JS before the browser fetches,
        // so it's present in the DOM even when image loading is blocked.
        // Prefer srcset (highest-res entry) over src; skip data: URIs.
        let imageUrl = '';
        if (img) {
            const srcset = img.getAttribute('srcset') || '';
            if (srcset) {
                // srcset entries: "url width", pick the last (largest)
                const last = srcset.trim().split(',').pop().trim().split(/\s+/)[0];
                if (last && !last.startsWith('data:')) imageUrl = last;
            }
            if (!imageUrl) {
                const src = img.getAttribute('src') || '';
                if (src && !src.startsWith('data:')) imageUrl = src;
            }
        }

        const timeEl = article.querySelector('time[datetime]');
        let mediaType = null;
        if (article.querySelector('video')) mediaType = 'reel';
        else if (img) mediaType = 'photo';

        posts.push({
            post_url:      postUrl,
            shortcode:     sc,
            caption:       caption.substring(0, 2200),
            author_handle: authorHandle,
            media_type:    mediaType,
            timestamp:     timeEl ? timeEl.getAttribute('datetime') : null,
            image_url:     imageUrl,
        });
    }

    // ── Strategy 2: grid thumbnail links (explore/tags, profile grid) ─────────
    // Runs only when no article-based posts were found — avoids double-counting.
    if (!posts.length) {
        for (const a of document.querySelectorAll('a[href]')) {
            const href = a.getAttribute('href') || '';
            if (!isPostHref(href)) continue;
            const m = href.match(/\/(p|reel|tv)\/([A-Za-z0-9_-]+)/);
            if (!m) continue;
            const sc = m[2];
            if (seen.has(sc)) continue;
            seen.add(sc);

            const postUrl = 'https://www.instagram.com' + href;
            const img     = a.querySelector('img[alt]');
            const { handle, caption } = img
                ? parseAlt(img.getAttribute('alt') || '')
                : { handle: null, caption: '' };

            let gridImageUrl = '';
            if (img) {
                const srcset = img.getAttribute('srcset') || '';
                if (srcset) {
                    const last = srcset.trim().split(',').pop().trim().split(/\s+/)[0];
                    if (last && !last.startsWith('data:')) gridImageUrl = last;
                }
                if (!gridImageUrl) {
                    const src = img.getAttribute('src') || '';
                    if (src && !src.startsWith('data:')) gridImageUrl = src;
                }
            }

            posts.push({
                post_url:      postUrl,
                shortcode:     sc,
                caption:       caption.substring(0, 2200),
                author_handle: handle,
                media_type:    a.querySelector('video') ? 'reel' : (img ? 'photo' : null),
                timestamp:     null,
                image_url:     gridImageUrl,
            });
        }
    }

    console.log('[instagram] extracted', posts.length, 'post(s)');
    return posts;
}
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pause(lo: float = 1.0, hi: float = 3.5) -> None:
    time.sleep(random.uniform(lo, hi))


def _human_scroll(page, rounds: int | None = None) -> None:
    if rounds is None:
        rounds = random.randint(5, 9)
    for _ in range(rounds):
        px = random.randint(300, 700)
        page.evaluate(f"window.scrollBy(0, {px})")
        if random.random() < 0.15:
            time.sleep(random.uniform(2.0, 4.0))
        else:
            time.sleep(random.uniform(1.0, 2.5))


def _parse_ig_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(dt_timezone.utc)
    except ValueError:
        return None


# ── Scraper ───────────────────────────────────────────────────────────────────

class InstagramPostsScraper(BaseScraper):
    """Cookie-authenticated Instagram Posts scraper.

    Navigates hashtag explore pages as a logged-in user and extracts post
    captions, URLs, and author handles. Routes traffic through DataImpulse
    residential proxies when configured; falls back to direct connection with
    a warning (valid session cookies reduce the need for proxy rotation).

    Populate SearchQuery rows (admin → Search Queries) with:
        source = 'instagram_posts'
        query  = hashtag without # (e.g. 'manilaevents', 'cebuevents')
    """

    source = "instagram_posts"
    supports_keywords = True

    # ── Cookie helpers ────────────────────────────────────────────────────────

    def _cookies_path(self) -> Path:
        raw = os.environ.get("IG_COOKIES_FILE", "www.instagram.com_cookies.txt")
        p = Path(raw)
        if p.is_absolute():
            return p
        # Resolve relative to the Django project root (where manage.py lives).
        # __file__ = .../apps/backend/events/scrapers/instagram_posts.py
        # .parent x3  = .../apps/backend/
        return Path(__file__).parent.parent.parent / raw

    # ── Proxy ─────────────────────────────────────────────────────────────────

    def _resolve_proxy(self) -> dict | None:
        """Return a Playwright proxy dict, or None to run without proxy.

        DataImpulse only — free public proxies are untrusted third parties that
        could intercept session cookies via SSL MITM. Falls back to a direct
        connection (acceptable because valid IG session cookies reduce IP-based
        blocking risk).
        """
        from .social_proxy import social_proxy_configured, dataimpulse_playwright_proxy
        if not social_proxy_configured():
            logger.info(
                "[%s] No DataImpulse credentials — running without proxy.",
                self.source,
            )
            return None
        try:
            return dataimpulse_playwright_proxy(source=self.source)
        except RuntimeError as exc:
            logger.warning(
                "[%s] DataImpulse unavailable (%s) — falling back to direct connection.",
                self.source, exc,
            )
            return None

    # ── Browser context ───────────────────────────────────────────────────────

    def _browser_context(self, pw, proxy: dict | None = None):
        headless = os.environ.get("IG_HEADLESS", "true").lower() != "false"

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

        # Inject session cookies so we browse as a logged-in user.
        cookies_path = self._cookies_path()
        if cookies_path.exists():
            cookies = _load_netscape_cookies(cookies_path)
            context.add_cookies(cookies)
            logger.info("[%s] loaded %d cookies from %s", self.source, len(cookies), cookies_path)
        else:
            logger.warning(
                "[%s] cookies file not found at %s — scraper may be shown the login wall.",
                self.source, cookies_path,
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

    # ── Navigation ────────────────────────────────────────────────────────────

    def _goto(self, page, url: str, retries: int = 3) -> None:
        for attempt in range(retries):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=90_000)
                return
            except Exception as exc:
                if attempt == retries - 1:
                    raise
                logger.warning("goto %s attempt %d failed: %s", url, attempt + 1, exc)
                _pause(3.0, 6.0 + attempt * 2)

    # ── Per-hashtag scrape ────────────────────────────────────────────────────

    def _fetch_for_hashtag(self, page, hashtag: str) -> list[dict]:
        """Navigate to the IG hashtag explore page, scroll, and extract posts."""
        tag = hashtag.lstrip("#")
        url = _TAG_URL.format(hashtag=_urlquote(tag, safe=""))

        self._goto(page, url)
        _pause(2.5, 5.0)

        # Detect session expiry: IG redirects to /accounts/login/ when cookies are expired.
        if "accounts/login" in page.url or "challenge" in page.url:
            raise SessionExpiredError(
                f"session_expired:{self.source} — redirected to {page.url[:120]}"
            )

        # Wait for the first post thumbnail or article to appear.
        try:
            page.wait_for_selector(
                'article, a[href*="/p/"], a[href*="/reel/"]',
                timeout=20_000,
            )
        except Exception:
            logger.warning("[%s] no post elements found on %s — may be blocked or empty tag.", self.source, url)
            return []

        # Scroll in two bursts: load the initial grid, pause, load more.
        _human_scroll(page)
        _pause(1.5, 3.0)
        _human_scroll(page, rounds=random.randint(4, 7))
        _pause(1.0, 2.0)

        posts = page.evaluate(_EXTRACT_POSTS_JS)
        logger.info(
            "[%s] hashtag #%s: extracted %d post(s) from %s",
            self.source, tag, len(posts), page.url,
        )

        for p in posts[:5]:
            logger.debug(
                "[%s]   shortcode=%s handle=%s caption_len=%d",
                self.source, p.get("shortcode"), p.get("author_handle"), len(p.get("caption") or ""),
            )

        return posts

    # ── BaseScraper overrides ─────────────────────────────────────────────────

    def fetch(self) -> Iterable[ScrapedEvent]:
        # fetch() intentionally empty — run() drives the loop.
        return iter([])

    def run(
        self,
        query_id: int | None = None,
        query_ids: list[int] | None = None,
        max_events: int | None = None,
        on_progress=None,
    ) -> dict:
        """Run the scraper for active SearchQuery rows with source='instagram_posts'.

        Django ORM calls are kept OUTSIDE the sync_playwright() block to avoid
        SynchronousOnlyOperation errors (Playwright runs its own event loop).
        """
        from django.db import models, connection as db_connection, close_old_connections
        from django.utils import timezone
        from events.models import Event, SearchQuery

        # ── 1. Load queries (ORM outside playwright) ──────────────────────────
        qs = SearchQuery.objects.filter(is_active=True, source=self.source)
        if query_ids:
            qs = qs.filter(pk__in=query_ids)
        elif query_id:
            qs = qs.filter(pk=query_id)
        queries = list(qs)

        if not queries:
            logger.info(
                "[%s] no active SearchQuery rows with source='%s' — add them in the admin.",
                self.source, self.source,
            )
            return {"source": self.source, "created": 0, "updated": 0}

        proxy = self._resolve_proxy()
        total_created = total_updated = 0

        # ── 2. Collect raw posts (Playwright block — NO Django ORM inside) ─────
        # raw_by_query maps sq.pk → (raw_posts, hashtag, source_url)
        raw_by_query: dict[int, tuple[list[dict], str, str]] = {}

        with sync_playwright() as pw:
            for i, sq in enumerate(queries, 1):
                hashtag    = sq.query.strip()
                source_url = _TAG_URL.format(hashtag=_urlquote(hashtag.lstrip("#"), safe=""))
                logger.info(
                    "[%s] query %d/%d: #%s",
                    self.source, i, len(queries), hashtag.lstrip("#"),
                )

                browser = context = None
                try:
                    browser, context = self._browser_context(pw, proxy)
                    page = context.new_page()
                    Stealth().use_sync(page)
                    self._block_heavy_resources(page)
                    raw_posts = self._fetch_for_hashtag(page, hashtag)
                    if max_events is not None:
                        raw_posts = raw_posts[:max_events]
                    raw_by_query[sq.pk] = (raw_posts, hashtag, source_url)
                except SessionExpiredError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "[%s] #%s failed: %s — skipping this query.",
                        self.source, hashtag, exc,
                    )
                    raw_by_query[sq.pk] = ([], hashtag, source_url)
                finally:
                    if context is not None:
                        context.close()
                    if browser is not None:
                        browser.close()

                _pause(3.0, 7.0)

        # ── 3. Structure via Ollama + persist (ORM outside Playwright) ──────────
        for sq in queries:
            data = raw_by_query.get(sq.pk)
            if not data:
                continue
            raw_posts, hashtag, source_url = data

            collected_at = timezone.now().isoformat()
            scraped_events: list[ScrapedEvent]    = []
            scraped_orgs:   list[ScrapedOrganizer] = []

            for p in raw_posts:
                post_url  = p.get("post_url", "")
                shortcode = p.get("shortcode") or ""
                caption   = (p.get("caption") or "").strip()
                handle    = (p.get("author_handle") or "").strip()
                image_url = p.get("image_url") or ""

                if not _is_eligible(caption):
                    logger.debug("[%s] SKIP pre-filter: %s", self.source, post_url[:60])
                    continue

                direct_reg = find_registration_url(caption)
                structured = _call_llm_structure(caption, handle or None, collected_at, [])

                if structured is not None and not structured["is_event"]:
                    logger.debug("[%s] SKIP not event: %s", self.source, post_url[:60])
                    continue

                fields = structured or {
                    "is_event": True, "title": None, "start_datetime": None,
                    "venue_name": None, "city_location": None,
                    "organizer_name": None, "organizer_email": None,
                    "organizer_phone": None, "short_description": None,
                    "registration_url": None,
                }

                # Regex extraction is the source of truth for URLs — LLM hallucinates
                # links that don't exist in the caption, so only use it as a fallback
                # when the suggested URL is literally present in the caption text.
                llm_reg = fields.get("registration_url") or ""
                if llm_reg and llm_reg not in caption:
                    llm_reg = ""
                registration_url = direct_reg or llm_reg or ""

                contact         = _extract_contact_fallback(caption)
                # Validate LLM email — must look like a real address (has @domain.tld),
                # not an Instagram handle like "@a1official".
                _llm_email = fields.get("organizer_email") or ""
                if _llm_email and not re.search(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', _llm_email):
                    _llm_email = ""
                organizer_email = _llm_email or contact["email"] or ""
                organizer_phone = fields.get("organizer_phone") or contact["phone"] or ""

                title          = fields.get("title") or (f"{handle}: {caption[:80]}" if handle else caption[:80])
                organizer_name = fields.get("organizer_name") or handle.lstrip("@") or ""

                city_raw   = fields.get("city_location") or ""
                loc_parts  = [s.strip() for s in city_raw.split(",")] if city_raw else []
                city       = loc_parts[0] if loc_parts else ""
                country    = loc_parts[-1] if len(loc_parts) >= 2 else ""

                venue = (
                    ScrapedVenue(name=fields["venue_name"], city=city, country=country)
                    if fields.get("venue_name") else None
                )

                scraped_events.append(ScrapedEvent(
                    name=title[:255],
                    description=fields.get("short_description") or caption[:500],
                    starts_at=_parse_post_date(fields.get("start_datetime")),
                    url=post_url,
                    image_url=image_url,
                    registration_url=registration_url,
                    external_id=shortcode,
                    source_url=source_url,
                    organizer=organizer_name,
                    organizer_url=f"{_IG_BASE}/{handle.lstrip('@')}/" if handle else "",
                    venue=venue,
                ))

                if organizer_name:
                    ig_profile = f"{_IG_BASE}/{handle.lstrip('@')}/" if handle else ""
                    scraped_orgs.append(ScrapedOrganizer(
                        name=organizer_name,
                        email=organizer_email,
                        phone=organizer_phone,
                        instagram_url=ig_profile,
                        source_url=post_url,
                        external_id=handle.lstrip("@") if handle else "",
                    ))

                logger.info(
                    "[%s] %s | title=%s | org=%s | reg=%s",
                    self.source, post_url[:60],
                    (title or "")[:40],
                    organizer_name[:30] if organizer_name else "—",
                    registration_url or "—",
                )

            if not scraped_events:
                logger.info("[%s] #%s: 0 usable events extracted.", self.source, hashtag)
                db_connection.close()
                SearchQuery.objects.filter(pk=sq.pk).update(
                    last_run_at=timezone.now(),
                    updated_at=timezone.now(),
                )
                continue

            # LLM calls can take minutes (especially on timeouts) — force a fresh
            # DB connection before writes so Neon's pooler SSL drop doesn't abort.
            db_connection.close()

            if scraped_orgs:
                save_organizers(self.source, scraped_orgs)

            result = save_events(self.source, scraped_events)

            # Backfill organizer_ref for any events (this run or older) that share
            # an organizer name but were saved before the Organizer row existed.
            if scraped_orgs:
                from events.models import Organizer as OrgModel
                for so in scraped_orgs:
                    if not so.name:
                        continue
                    org = OrgModel.objects.filter(
                        source=self.source, name=so.name
                    ).first()
                    if org:
                        updated = Event.objects.filter(
                            source=self.source,
                            organizer__iexact=so.name,
                            organizer_ref__isnull=True,
                        ).update(organizer_ref=org)
                        if updated:
                            logger.info(
                                "[%s] backfilled organizer_ref for %d event(s) → %s",
                                self.source, updated, so.name,
                            )

            Event.objects.filter(
                pk__in=result.get("event_ids", []),
                search_query__isnull=True,
            ).update(search_query=sq)

            SearchQuery.objects.filter(pk=sq.pk).update(
                last_run_at=timezone.now(),
                events_found_count=(
                    models.F("events_found_count") + result["created"] + result["updated"]
                ),
                updated_at=timezone.now(),
            )

            total_created += result["created"]
            total_updated += result["updated"]
            logger.info(
                "[%s] saved #%s: %d created, %d updated",
                self.source, hashtag, result["created"], result["updated"],
            )

            if on_progress is not None:
                try:
                    on_progress({})
                except Exception as exc:
                    logger.debug("[%s] on_progress callback raised: %s", self.source, exc)

        logger.info(
            "[%s] run complete — %d queries, %d created, %d updated",
            self.source, len(queries), total_created, total_updated,
        )
        return {
            "source":  self.source,
            "created": total_created,
            "updated": total_updated,
        }
