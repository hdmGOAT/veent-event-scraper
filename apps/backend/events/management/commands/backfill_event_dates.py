"""Backfill starts_at / ends_at / country for Facebook events.

Visits each event's URL with a headless browser (same proxy + stealth setup
as the main scraper), extracts the date and location via _EXTRACT_DETAIL_JS,
and saves them.

Usage:
    python manage.py backfill_event_dates
    python manage.py backfill_event_dates --limit 100
    python manage.py backfill_event_dates --source facebook_events --dry-run
"""
import logging
import os
import re
import time

from django.core.management.base import BaseCommand
from django.db.models import Q

from events.models import BandwidthLog, Event, Venue
from events.scrapers.facebook_events import (
    FacebookEventsScraper,
    _DISMISS_MODAL_JS,
    _EXTRACT_DETAIL_JS,
    _normalize_country,
    _parse_fb_date,
    log_bandwidth,
)
from events.scrapers.geo_normalize import geocode_country, has_alias

logger = logging.getLogger(__name__)

_PAUSE_BETWEEN = (1.5, 3.0)
_PAGE_RETRIES = 4


def _pause(lo, hi):
    import random
    time.sleep(random.uniform(lo, hi))


def _mb(b):
    return f"{b / 1_048_576:.2f} MB"


class Command(BaseCommand):
    help = "Backfill starts_at / ends_at / country for Facebook events missing date or country."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=50,
            help="Maximum number of events to process (default: 50).",
        )
        parser.add_argument(
            "--source", default="facebook_events",
            help="Scraper source key to filter on (default: facebook_events).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Parse dates but do not write to the database.",
        )

    def handle(self, *args, **options):
        import os as _os
        _os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

        limit = options["limit"]
        source = options["source"]
        dry_run = options["dry_run"]

        qs = (
            Event.objects
            .filter(source=source)
            .filter(Q(starts_at__isnull=True) | Q(venue__isnull=True) | Q(venue__country=""))
            .exclude(url="")
            .select_related("venue")
            .order_by("id")[:limit]
        )
        events = list(qs)
        if not events:
            self.stdout.write("No events missing date or venue country found.")
            return

        scraper = FacebookEventsScraper()
        proxy = scraper._resolve_proxy()
        using_free_proxy = scraper._is_free_proxy(proxy)
        proxy_label = "DataImpulse" if not using_free_proxy else "free proxy"
        proxy_server = proxy.get("server", "?")

        self.stdout.write(
            f"\nBackfilling {len(events)} events  "
            f"[{'DRY RUN — ' if dry_run else ''}source={source}  proxy={proxy_label} ({proxy_server})]\n"
            + "─" * 70
        )

        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth

        updated = skipped = failed = 0
        bytes_transferred = 0

        def _make_page(pw, proxy, warmup=False):
            browser, context = scraper._browser_context(pw, proxy)
            page = context.new_page()

            cdp = context.new_cdp_session(page)
            cdp.send("Network.enable")

            def _on_loading_finished(params):
                nonlocal bytes_transferred
                try:
                    bytes_transferred += int(params.get("encodedDataLength", 0))
                except Exception:
                    pass

            cdp.on("Network.loadingFinished", _on_loading_finished)

            Stealth().use_sync(page)
            scraper._block_heavy_resources(page)

            if warmup:
                # Navigate to facebook.com first to establish the proxy tunnel and
                # get session cookies — matches what the main scraper does implicitly
                # via its search-page navigation before visiting event detail pages.
                try:
                    page.goto("https://www.facebook.com/", wait_until="commit", timeout=15_000)
                    _pause(1.5, 3.0)
                except Exception as _wu_exc:
                    # If the warmup crashes the browser, close everything and start
                    # a fresh browser without warmup rather than returning a dead page.
                    _wu_str = str(_wu_exc)
                    if any(e in _wu_str for e in ("closed", "crashed", "Target page")):
                        try:
                            context.close()
                        except Exception:
                            pass
                        try:
                            browser.close()
                        except Exception:
                            pass
                        browser, context = scraper._browser_context(pw, proxy)
                        page = context.new_page()
                        cdp2 = context.new_cdp_session(page)
                        cdp2.send("Network.enable")
                        cdp2.on("Network.loadingFinished", _on_loading_finished)
                        Stealth().use_sync(page)
                        scraper._block_heavy_resources(page)

            return browser, context, page

        with sync_playwright() as pw:
            for i, event in enumerate(events, 1):
                prefix = f"[{i}/{len(events)}]"
                name   = event.name[:55]
                bw_before = bytes_transferred
                detail = None

                self.stdout.write(f"\n{prefix} {name}")
                self.stdout.write(f"  url     : {event.url[:90]}")
                venue_str = f'"{event.venue.name[:30]}"' if event.venue else "none"
                country_str = repr(event.venue.country) if event.venue else "n/a"
                self.stdout.write(
                    f"  db state: starts_at={'set' if event.starts_at else 'NULL'}  "
                    f"venue={venue_str}  country={country_str}"
                )

                for attempt in range(_PAGE_RETRIES):
                    self.stdout.write(f"  → loading (attempt {attempt+1}/{_PAGE_RETRIES})...")
                    # Fresh browser context per event — forces a new DataImpulse residential
                    # IP each time and avoids stale connection state from previous events.
                    browser, context, page = _make_page(pw, proxy, warmup=(attempt == 0))
                    try:
                        page.goto(event.url, wait_until="domcontentloaded", timeout=30_000)
                        # Wait for React to finish its XHR calls after domcontentloaded —
                        # without this the FB logo is still rendering when JS extraction runs.
                        try:
                            page.wait_for_load_state("networkidle", timeout=20_000)
                        except Exception:
                            pass  # timeout is fine — just means a long-running XHR, proceed anyway
                        _pause(1.5, 3.5)

                        # Exact same post-navigation flow as _fetch_for_query in the main scraper.
                        for _dm in range(4):
                            page.evaluate(_DISMISS_MODAL_JS)
                            _pause(0.6, 1.2)
                            page_title = page.title()
                            if page_title and "log in" not in page_title.lower() and "facebook" != page_title.strip().lower():
                                break

                        try:
                            page.evaluate("""
                                () => {
                                    const btn = Array.from(document.querySelectorAll('div[role="button"], span[role="button"]'))
                                        .find(el => /^see\\s+more$/i.test((el.textContent || '').trim()));
                                    if (btn) btn.click();
                                }
                            """)
                            _pause(0.4, 0.8)
                        except Exception:
                            pass

                        detail = page.evaluate(_EXTRACT_DETAIL_JS, event.name or "")
                        page_title = page.title()
                        if "log in" in page_title.lower():
                            raise RuntimeError("LOGIN_WALL: page requires login")
                        self.stdout.write(f"     page loaded OK  ({_mb(bytes_transferred - bw_before)} this event so far)")
                        break
                    except Exception as exc:
                        exc_str = str(exc)
                        if attempt < _PAGE_RETRIES - 1:
                            self.stdout.write(f"  ~  attempt {attempt+1} failed — retrying with fresh browser: {exc_str[:100]}")
                            if using_free_proxy:
                                new_proxy = scraper._rotate_free_proxy()
                                if new_proxy:
                                    proxy = new_proxy
                                    self.stdout.write(f"     rotated proxy: {proxy.get('server','?')}")
                            _pause(3.0, 6.0)
                        else:
                            self.stdout.write(f"  !  FAILED after {_PAGE_RETRIES} attempts: {exc_str[:150]}")
                            failed += 1
                            detail = None
                    finally:
                        context.close()
                        browser.close()

                if detail is None:
                    _pause(*_PAUSE_BETWEEN)
                    continue

                d = (detail.get("events") or [{}])[0]
                raw          = d.get("start_datetime")
                venue_name   = d.get("venue_name") or ""
                address      = d.get("address") or ""
                city_location= d.get("city_location") or ""
                loc_parts    = [p.strip() for p in city_location.split(",")] if city_location else []
                # Skip GPS coordinate strings (e.g. "1.2921, 103.8572")
                _GPS_RE = re.compile(r'^-?\d+\.\d+$')
                if loc_parts and all(_GPS_RE.match(p) for p in loc_parts):
                    loc_parts = []
                _raw_country = loc_parts[-1] if len(loc_parts) >= 2 else ""
                if has_alias(_raw_country):
                    # Fast path: known alias (country code, state name, etc.)
                    country = _normalize_country(_raw_country)
                elif city_location:
                    # Geocode the full location string — handles city/town names that
                    # aren't in our alias table (e.g. "Camp Aguinaldo, Quezon City" → Philippines).
                    import time as _time
                    _geo = geocode_country(city_location)
                    country = _geo or ""
                    if _geo:
                        self.stdout.write(f"     geocoded: {city_location!r} → {_geo!r}")
                    _time.sleep(1.1)  # Nominatim rate limit: 1 req/s
                else:
                    country = ""

                # Venue-name fallback: when city_location gave no country, try parsing the
                # venue name as a location string (e.g. venue="Singapore" → "Singapore",
                # venue="Rochester, NY, United States, New York" → "United States").
                if not country and venue_name:
                    _vparts = [p.strip() for p in venue_name.split(",")]
                    _vraw   = _vparts[-1] if _vparts else ""
                    if _vraw and has_alias(_vraw):
                        country = _normalize_country(_vraw)
                    elif has_alias(venue_name.strip()):
                        country = _normalize_country(venue_name.strip())

                _city_raw    = loc_parts[-2] if len(loc_parts) >= 3 else (loc_parts[0] if loc_parts else "")
                # Strip leading postal codes: "FI-00100 Helsinki" → "Helsinki", "2600 Baguio City" → "Baguio City"
                city = re.sub(r'^[A-Z]{2,3}[-\s]\d{3,}[A-Z0-9-]*\s*', '', _city_raw).strip()
                city = re.sub(r'^\d{3,}[A-Z0-9-]*\s*', '', city).strip()
                city = city.lstrip("0123456789 ").strip()

                self.stdout.write(
                    f"  extracted: date={raw!r}  venue={venue_name!r}  "
                    f"city={city!r}  country={country!r}  address={address[:50]!r}"
                )

                if event.starts_at and event.venue and event.venue.country:
                    self.stdout.write(f"  ·  already complete — skipping")
                    skipped += 1
                    _pause(*_PAUSE_BETWEEN)
                    continue

                if not raw and not country:
                    self.stdout.write(f"  -  nothing useful extracted  debug={detail.get('debug')}")
                    skipped += 1
                    _pause(*_PAUSE_BETWEEN)
                    continue

                starts_at = event.starts_at
                ends_at   = event.ends_at
                if raw:
                    parsed_start, parsed_end = _parse_fb_date(raw)
                    if parsed_start is None:
                        self.stdout.write(f"  ✗  date parse failed (raw={raw!r})")
                        failed += 1
                        _pause(*_PAUSE_BETWEEN)
                        continue
                    starts_at, ends_at = parsed_start, parsed_end

                saved = []
                if not dry_run:
                    event_updates = {}
                    if starts_at is not None:
                        event_updates["starts_at"] = starts_at
                        event_updates["ends_at"]   = ends_at
                    if event_updates:
                        Event.objects.filter(pk=event.pk).update(**event_updates)
                        saved.append(f"date→{starts_at.date()}")

                    if country or city or address:
                        if event.venue:
                            venue_updates = {}
                            if country and not event.venue.country:
                                venue_updates["country"] = country
                            if city and not event.venue.city:
                                venue_updates["city"] = city
                            if address and not event.venue.address:
                                venue_updates["address"] = address
                            if venue_updates:
                                Venue.objects.filter(pk=event.venue.pk).update(**venue_updates)
                                saved.append(f"venue.country→{country}")
                        elif venue_name:
                            from events.scrapers.base import _unique_slug
                            venue = Venue.objects.create(
                                name=venue_name,
                                slug=_unique_slug(Venue, venue_name),
                                city=city, country=country, address=address,
                                source=event.source,
                            )
                            Event.objects.filter(pk=event.pk).update(venue=venue)
                            saved.append(f"new venue ({venue_name[:30]})")

                event_bw = bytes_transferred - bw_before
                ends_str = f" → {ends_at.date()}" if ends_at else ""
                saved_str = "  saved: " + ", ".join(saved) if saved else ("  (dry run)" if dry_run else "")
                self.stdout.write(
                    f"  ✓  {starts_at}{ends_str} | {country or '—'}"
                    f"  [{_mb(event_bw)} this event | {_mb(bytes_transferred)} total]{saved_str}"
                )
                updated += 1
                _pause(*_PAUSE_BETWEEN)

        if bytes_transferred and not dry_run:
            proxy_type = BandwidthLog.PROXY_DATAIMPULSE if not using_free_proxy else BandwidthLog.PROXY_FREE
            try:
                log_bandwidth(source=f"{source}_backfill", bytes_transferred=bytes_transferred, proxy_type=proxy_type)
            except Exception:
                pass

        self.stdout.write(
            f"\n{'─' * 70}\n"
            f"Done.  Updated={updated}  Skipped={skipped}  Failed={failed}"
            f"  |  {_mb(bytes_transferred)} via {proxy_label}"
            + (" (dry run — nothing written)" if dry_run else "")
        )
