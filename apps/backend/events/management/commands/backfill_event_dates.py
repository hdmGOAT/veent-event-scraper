"""Backfill starts_at / ends_at for Facebook events that have a null date.

Visits each event's URL with a headless browser (same proxy + stealth setup
as the main scraper), extracts the date via _EXTRACT_DETAIL_JS, and saves it.

Usage:
    python manage.py backfill_event_dates
    python manage.py backfill_event_dates --limit 100
    python manage.py backfill_event_dates --source facebook_events --dry-run
"""
import logging
import os
import time

from django.core.management.base import BaseCommand

from events.models import Event
from events.scrapers.facebook_events import (
    FacebookEventsScraper,
    _DISMISS_MODAL_JS,
    _EXTRACT_DETAIL_JS,
    _parse_fb_date,
)

logger = logging.getLogger(__name__)

_PAUSE_BETWEEN = (1.5, 3.0)
_PAGE_RETRIES = 4   # rotate proxy and retry this many times per event


def _pause(lo, hi):
    import random
    time.sleep(random.uniform(lo, hi))


class Command(BaseCommand):
    help = "Backfill starts_at / ends_at for Facebook events with a null date."

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
            .filter(source=source, starts_at__isnull=True)
            .exclude(url="")
            .order_by("id")[:limit]
        )
        events = list(qs)
        if not events:
            self.stdout.write("No events with null starts_at found.")
            return

        self.stdout.write(
            f"Backfilling {len(events)} events "
            f"({'DRY RUN — ' if dry_run else ''}source={source})...\n"
        )

        scraper = FacebookEventsScraper()
        proxy = scraper._resolve_proxy()
        using_free_proxy = scraper._is_free_proxy(proxy)

        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth

        updated = skipped = failed = 0

        def _make_page(pw, proxy):
            browser, context = scraper._browser_context(pw, proxy)
            page = context.new_page()
            Stealth().use_sync(page)
            scraper._block_heavy_resources(page)
            return browser, context, page

        with sync_playwright() as pw:
            browser, context, page = _make_page(pw, proxy)
            try:
                for i, event in enumerate(events, 1):
                    prefix = f"[{i}/{len(events)}] {event.name[:50]}"
                    detail = None

                    for attempt in range(_PAGE_RETRIES):
                        self.stdout.write(
                            f"  →  {prefix}: loading (attempt {attempt+1}/{_PAGE_RETRIES}) {event.url[:80]}"
                        )
                        try:
                            scraper._goto(page, event.url, retries=1)
                            _pause(*_PAUSE_BETWEEN)
                            self.stdout.write(f"     loaded, extracting date...")
                            page.evaluate(_DISMISS_MODAL_JS)
                            _pause(0.5, 1.0)
                            detail = page.evaluate(_EXTRACT_DETAIL_JS, event.name or "")
                            dbg = detail.get("debug", {})
                            first_long = dbg.get("descFirstLong") or ""
                            empty_page = dbg.get("descDirAutoCount", 1) == 0 and not first_long
                            if dbg.get("error") == "no title" or "Log in" in first_long or "Log In" in first_long or empty_page:
                                raise RuntimeError("ERR_PROXY_CONNECTION_FAILED: blocked/empty page")
                            break  # success
                        except Exception as exc:
                            exc_str = str(exc)
                            is_proxy_err = any(e in exc_str for e in (
                                "ERR_PROXY_CONNECTION_FAILED",
                                "ERR_TUNNEL_CONNECTION_FAILED",
                                "ERR_SOCKS_CONNECTION_FAILED",
                                "Timeout",
                            ))
                            if using_free_proxy and is_proxy_err and attempt < _PAGE_RETRIES - 1:
                                self.stdout.write(
                                    f"  ~  {prefix}: proxy fail (attempt {attempt+1}/{_PAGE_RETRIES}), rotating..."
                                )
                                new_proxy = scraper._rotate_free_proxy()
                                if new_proxy:
                                    proxy = new_proxy
                                    self.stdout.write(f"     new proxy: {proxy.get('server','?')}")
                                context.close()
                                browser.close()
                                browser, context, page = _make_page(pw, proxy)
                                _pause(3.0, 6.0)
                            else:
                                self.stdout.write(f"  !  {prefix}: {exc_str[:120]}")
                                failed += 1
                                detail = None
                                break

                    if detail is None:
                        _pause(*_PAUSE_BETWEEN)
                        continue

                    d = (detail.get("events") or [{}])[0]
                    raw = d.get("start_datetime")

                    if not raw:
                        self.stdout.write(f"  -  {prefix}: no date on page (debug={detail.get('debug')})")
                        skipped += 1
                        _pause(*_PAUSE_BETWEEN)
                        continue

                    starts_at, ends_at = _parse_fb_date(raw)
                    if starts_at is None:
                        self.stdout.write(
                            f"  ✗  {prefix}: parse failed (raw={raw!r})"
                        )
                        failed += 1
                        _pause(*_PAUSE_BETWEEN)
                        continue

                    if not dry_run:
                        Event.objects.filter(pk=event.pk).update(
                            starts_at=starts_at,
                            ends_at=ends_at,
                        )

                    ends_str = f" → {ends_at}" if ends_at else ""
                    self.stdout.write(
                        f"  ✓  {prefix}: {starts_at}{ends_str}"
                        + (" (dry run)" if dry_run else "")
                    )
                    updated += 1
                    _pause(*_PAUSE_BETWEEN)

            finally:
                context.close()
                browser.close()

        self.stdout.write(
            f"\nDone. Updated={updated}  Skipped(no date)={skipped}  Failed={failed}"
        )
