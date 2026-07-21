"""Interval-based scheduler for scrapers and CRM pushes.

Scrape jobs
-----------
Controlled by three env vars:

    SCRAPER_KEYS=facebook_events,instagram_posts,luma
        Comma-separated list of scraper keys to run (see events/scrapers/__init__.py).

    SCRAPER_INTERVAL=6h
        Default interval applied to every key in SCRAPER_KEYS.

    SCRAPER_INTERVAL_<KEY>=24h   (optional, per-scraper override)
        Overrides SCRAPER_INTERVAL for a single scraper.
        e.g. SCRAPER_INTERVAL_LUMA=24h

Push jobs
---------
    PUSH_INTERVAL=1h
        How often to run `manage.py push_crm_leads`. Omit to disable.

Interval format: 6h  /  30m  /  3600s  /  plain integer (seconds).

Run via the ``scheduler`` Docker Compose service — blocks indefinitely.
"""
import logging
import os
import signal
import subprocess
import sys
import threading
import time

import django
from django.core.management.base import BaseCommand

from events.notifications import notify_push_complete
from events.runner import trigger_scraper_run
from events.scrapers import SCRAPERS

logger = logging.getLogger(__name__)

_SHUTDOWN = threading.Event()


def _parse_interval(value: str) -> int:
    v = value.strip().lower()
    if v.endswith("h"):
        return int(v[:-1]) * 3600
    if v.endswith("m"):
        return int(v[:-1]) * 60
    if v.endswith("s"):
        return int(v[:-1])
    return int(v)


def _scrape_loop(key: str, interval: int) -> None:
    logger.info("[scheduler] scrape/%s — every %ss", key, interval)
    while not _SHUTDOWN.is_set():
        logger.info("[scheduler] triggering scrape: %s", key)
        try:
            run, already_active = trigger_scraper_run(key, triggered_by=None)
            if already_active:
                logger.info("[scheduler] scrape/%s already active, skipping", key)
            else:
                logger.info("[scheduler] scrape/%s started (run_id=%s)", key, run.id)
        except Exception:
            logger.exception("[scheduler] scrape/%s failed to trigger", key)
        _SHUTDOWN.wait(timeout=interval)


def _parse_push_totals(output: str) -> tuple[int, int, int]:
    """Extract (created, skipped, review) from push_crm_leads stdout."""
    import re
    m = re.search(
        r"Totals:.*?created=(\d+).*?skipped=(\d+).*?review=(\d+)", output
    )
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return 0, 0, 0


def _push_loop(interval: int) -> None:
    from django.conf import settings
    manage_py = str(settings.BASE_DIR / "manage.py")
    logger.info("[scheduler] push — every %ss", interval)
    while not _SHUTDOWN.is_set():
        logger.info("[scheduler] running push_crm_leads")
        try:
            result = subprocess.run(
                [sys.executable, manage_py, "push_crm_leads"],
                cwd=str(settings.BASE_DIR),
                capture_output=True,
                text=True,
            )
            output = result.stdout + result.stderr
            if result.returncode != 0:
                logger.error("[scheduler] push_crm_leads exited with code %s\n%s", result.returncode, output)
            else:
                pushed, skipped, review = _parse_push_totals(output)
                logger.info("[scheduler] push complete — pushed=%s skipped=%s review=%s", pushed, skipped, review)
                notify_push_complete(pushed=pushed, skipped=skipped, review=review)
        except Exception:
            logger.exception("[scheduler] push_crm_leads failed")
        _SHUTDOWN.wait(timeout=interval)


class Command(BaseCommand):
    help = (
        "Run scrapers and CRM pushes on schedules defined by env vars. "
        "Blocks until the process is killed."
    )

    def handle(self, *args, **options):
        threads = []

        # ── Scrape jobs ───────────────────────────────────────────────────────
        keys_raw = os.environ.get("SCRAPER_KEYS", "").strip()
        default_interval_raw = os.environ.get("SCRAPER_INTERVAL", "").strip()

        if keys_raw and default_interval_raw:
            try:
                default_interval = _parse_interval(default_interval_raw)
            except (ValueError, TypeError):
                logger.error(
                    "[scheduler] SCRAPER_INTERVAL=%r is not a valid interval — scrape jobs disabled",
                    default_interval_raw,
                )
                default_interval = None

            if default_interval is not None:
                for key in [k.strip() for k in keys_raw.split(",") if k.strip()]:
                    if key not in SCRAPERS:
                        logger.warning(
                            "[scheduler] SCRAPER_KEYS: unknown scraper key %r — skipping", key
                        )
                        continue
                    override_raw = os.environ.get(f"SCRAPER_INTERVAL_{key.upper()}", "").strip()
                    if override_raw:
                        try:
                            interval = _parse_interval(override_raw)
                        except (ValueError, TypeError):
                            logger.warning(
                                "[scheduler] SCRAPER_INTERVAL_%s=%r invalid — using default %ss",
                                key.upper(), override_raw, default_interval,
                            )
                            interval = default_interval
                    else:
                        interval = default_interval

                    threads.append(threading.Thread(
                        target=_scrape_loop,
                        args=(key, interval),
                        name=f"sched-scrape-{key}",
                        daemon=True,
                    ))
        elif keys_raw or default_interval_raw:
            logger.warning(
                "[scheduler] Both SCRAPER_KEYS and SCRAPER_INTERVAL must be set to schedule scrapes — skipping"
            )

        # ── Push job ──────────────────────────────────────────────────────────
        push_interval_raw = os.environ.get("PUSH_INTERVAL", "").strip()
        if push_interval_raw:
            try:
                push_interval = _parse_interval(push_interval_raw)
                threads.append(threading.Thread(
                    target=_push_loop,
                    args=(push_interval,),
                    name="sched-push",
                    daemon=True,
                ))
            except (ValueError, TypeError):
                logger.error(
                    "[scheduler] PUSH_INTERVAL=%r is not a valid interval — push job disabled",
                    push_interval_raw,
                )

        if not threads:
            logger.warning(
                "[scheduler] nothing scheduled. Set SCRAPER_KEYS + SCRAPER_INTERVAL "
                "and/or PUSH_INTERVAL to activate."
            )
            _SHUTDOWN.wait()
            return

        def _handle_signal(signum, frame):
            logger.info("[scheduler] signal %s — shutting down", signum)
            _SHUTDOWN.set()

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        for t in threads:
            t.start()

        _SHUTDOWN.wait()
        logger.info("[scheduler] shutdown complete")
