"""Interval-based scheduler for scrapers and CRM pushes.

Scrapers run sequentially one at a time to avoid overloading the VM.
After all scrapers complete, the scheduler waits SCRAPER_INTERVAL before
the next round. A separate thread handles CRM pushes on its own timer.

Env vars
--------
    SCRAPER_KEYS=facebook_events,instagram_posts,luma
        Comma-separated scraper keys (see events/scrapers/__init__.py).
        Scrapers run in this order, one at a time.

    SCRAPER_INTERVAL=6h
        How long to wait between full scrape rounds.

    SCRAPER_INTERVAL_<KEY>=24h   (optional per-scraper override)
        Skips a key in a round if it ran less than this long ago.
        e.g. SCRAPER_INTERVAL_LUMA=24h  — luma only runs every 24h
        even though the round interval is 6h.

    PUSH_INTERVAL=1h
        How often to run `manage.py push_crm_leads`. Runs in a
        separate thread so it doesn't block the scrape round.

Interval format: 6h / 30m / 3600s / plain integer (seconds).

Run via the ``scheduler`` Docker Compose service — blocks indefinitely.
"""
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time

from django.core.management.base import BaseCommand

from events.notifications import notify_push_complete, notify_push_failed
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


def _wait_for_run(key: str, run_id: int, poll: int = 30) -> None:
    """Block until the scraper subprocess finishes (polls ScraperRun status)."""
    from events.models import ScraperRun
    while not _SHUTDOWN.is_set():
        status = ScraperRun.objects.filter(id=run_id).values_list("status", flat=True).first()
        if status not in (ScraperRun.Status.QUEUED, ScraperRun.Status.RUNNING):
            logger.info("[scheduler] scrape/%s finished (status=%s)", key, status)
            return
        _SHUTDOWN.wait(timeout=poll)


def _scrape_round(keys: list[str], default_interval: int, per_key_intervals: dict[str, int]) -> None:
    """Run all keys sequentially, one at a time, respecting per-key intervals."""
    last_run: dict[str, float] = {k: float("-inf") for k in keys}
    while not _SHUTDOWN.is_set():
        round_start = time.monotonic()
        for key in keys:
            if _SHUTDOWN.is_set():
                break
            min_interval = per_key_intervals.get(key, default_interval)
            since_last = time.monotonic() - last_run.get(key, 0)
            if since_last < min_interval:
                logger.info(
                    "[scheduler] scrape/%s skipped (ran %.0fs ago, interval=%ss)",
                    key, since_last, min_interval,
                )
                continue
            logger.info("[scheduler] triggering scrape: %s", key)
            try:
                run, already_active = trigger_scraper_run(key, triggered_by=None)
                if already_active:
                    logger.info("[scheduler] scrape/%s already active, skipping", key)
                else:
                    logger.info("[scheduler] scrape/%s started (run_id=%s) — waiting for completion", key, run.id)
                    _wait_for_run(key, run.id)
                    last_run[key] = time.monotonic()
            except Exception:
                logger.exception("[scheduler] scrape/%s failed to trigger", key)

        if _SHUTDOWN.is_set():
            break
        elapsed = time.monotonic() - round_start
        sleep = max(0, default_interval - elapsed)
        logger.info("[scheduler] round complete — next round in %.0fs", sleep)
        _SHUTDOWN.wait(timeout=sleep)


def _parse_push_totals(output: str) -> tuple[int, int, int]:
    m = re.search(r"Totals:.*?created=(\d+).*?skipped=(\d+).*?review=(\d+)", output)
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
                notify_push_failed(exit_code=result.returncode, error_output=output)
            else:
                pushed, skipped, review = _parse_push_totals(output)
                logger.info("[scheduler] push complete — pushed=%s skipped=%s review=%s", pushed, skipped, review)
                notify_push_complete(pushed=pushed, skipped=skipped, review=review)
        except Exception:
            logger.exception("[scheduler] push_crm_leads failed")
        _SHUTDOWN.wait(timeout=interval)


class Command(BaseCommand):
    help = (
        "Run scrapers sequentially and CRM pushes on schedules defined by env vars. "
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
                    "[scheduler] SCRAPER_INTERVAL=%r invalid — scrape jobs disabled",
                    default_interval_raw,
                )
                default_interval = None

            if default_interval is not None:
                keys = []
                per_key_intervals: dict[str, int] = {}
                for key in [k.strip() for k in keys_raw.split(",") if k.strip()]:
                    if key not in SCRAPERS:
                        logger.warning("[scheduler] unknown scraper key %r — skipping", key)
                        continue
                    keys.append(key)
                    override_raw = os.environ.get(f"SCRAPER_INTERVAL_{key.upper()}", "").strip()
                    if override_raw:
                        try:
                            per_key_intervals[key] = _parse_interval(override_raw)
                        except (ValueError, TypeError):
                            logger.warning(
                                "[scheduler] SCRAPER_INTERVAL_%s=%r invalid — using default",
                                key.upper(), override_raw,
                            )

                if keys:
                    logger.info(
                        "[scheduler] %d scrapers queued sequentially, round interval=%ss",
                        len(keys), default_interval,
                    )
                    threads.append(threading.Thread(
                        target=_scrape_round,
                        args=(keys, default_interval, per_key_intervals),
                        name="sched-scrape",
                        daemon=True,
                    ))
        elif keys_raw or default_interval_raw:
            logger.warning(
                "[scheduler] Both SCRAPER_KEYS and SCRAPER_INTERVAL must be set — scrape jobs disabled"
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
                    "[scheduler] PUSH_INTERVAL=%r invalid — push job disabled",
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
