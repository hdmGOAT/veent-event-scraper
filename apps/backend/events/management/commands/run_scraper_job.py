"""Worker command that owns a single ScraperRun's lifecycle.

Launched by ``trigger_scraper_run`` (see events/runner.py) as a standalone OS
process so it can be killed — together with any children it spawns (e.g.
Playwright's chromium) — when an admin cancels the run. The parent stores this
process's pid on the ScraperRun row *before* this command begins its work, so the
command itself does not need to record the pid.
"""
import logging
import threading
import traceback
from collections import deque

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import F, Sum, Value
from django.db.models.functions import Concat
from django.utils import timezone

from events.models import BandwidthLog, ScraperRun
from events.notifications import notify_scraper_event, patch_run_all_progress
from events.runner import _map_result
from events.scrapers import SCRAPERS

_FLUSH_INTERVAL = 2.0    # seconds between DB log flushes
_MAX_TOTAL_LINES = 2000  # hard cap to prevent unbounded log growth


class _DBLogHandler(logging.Handler):
    """Buffer log records and periodically flush them to ScraperRun.log_output.

    Uses a background daemon timer so the scraper process is not slowed down by
    DB writes on every log call. The final flush is always synchronous (via
    stop()) before the run's terminal status is written, ensuring the frontend
    sees complete logs in the same poll tick as the status change.
    """

    def __init__(self, run_id: int):
        super().__init__()
        self._run_id = run_id
        self._buffer: deque[str] = deque()
        self._lock = threading.Lock()
        self._total_flushed = 0
        self._timer = None
        self._stopped = False
        self._schedule()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            line = record.getMessage()
        with self._lock:
            self._buffer.append(line)

    def _schedule(self) -> None:
        if self._stopped:
            return
        self._timer = threading.Timer(_FLUSH_INTERVAL, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def _tick(self) -> None:
        self._flush()
        self._schedule()

    def _flush(self) -> None:
        with self._lock:
            if not self._buffer:
                return
            remaining = _MAX_TOTAL_LINES - self._total_flushed
            if remaining <= 0:
                self._buffer.clear()
                return
            lines = list(self._buffer)[:remaining]
            self._buffer.clear()
            self._total_flushed += len(lines)

        chunk = '\n'.join(lines) + '\n'
        try:
            ScraperRun.objects.filter(pk=self._run_id).update(
                log_output=Concat(F("log_output"), Value(chunk))
            )
        except Exception:
            traceback.print_exc()  # surface flush errors to stderr without crashing

    def stop(self) -> None:
        """Cancel the timer and do one final synchronous flush."""
        self._stopped = True
        if self._timer is not None:
            self._timer.cancel()
        self._flush()


class Command(BaseCommand):
    help = "Execute a single queued ScraperRun by id (internal worker; not for manual use)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--run-id", type=int, required=True,
            help="The ScraperRun.pk to execute.",
        )
        parser.add_argument(
            "--query-id", type=int, default=None,
            help="When set, only this SearchQuery.pk is processed (single-query run).",
        )
        parser.add_argument(
            "--query-ids", type=str, default=None,
            help="Comma-separated SearchQuery PKs to restrict this run.",
        )
        parser.add_argument(
            "--locations", type=str, default=None,
            help="Comma-separated location suffixes to append to each search query.",
        )

    def _patch_batch_scoreboard(self, run) -> None:
        """Rebuild and PATCH the shared run-all scoreboard for this batch."""
        all_runs = list(
            ScraperRun.objects.filter(discord_message_id=run.discord_message_id)
        )
        run_ids = [r.id for r in all_runs]
        totals = (
            BandwidthLog.objects.filter(scraper_run_id__in=run_ids)
            .values("scraper_run_id")
            .annotate(total=Sum("bytes_transferred"))
        )
        bw_by_run = {r.id: 0 for r in all_runs}
        for row in totals:
            bw_by_run[row["scraper_run_id"]] = row["total"] or 0
        patch_run_all_progress(run.discord_message_id, all_runs, bw_by_run)

    def _notify_terminal(self, run, event_type: str, **kwargs) -> None:
        """Notify Discord for a terminal-status run.

        Batch runs (discord_message_id set): always patch the scoreboard.
        Errors/failures in a batch also fire an individual embed so they stand
        out in the channel. Non-batch runs get only individual embeds.

        Never raises — notification failures must not affect the worker exit.
        """
        try:
            run.refresh_from_db(fields=["discord_message_id"])
            if run.discord_message_id:
                self._patch_batch_scoreboard(run)
                if event_type in ("failed", "session_expired"):
                    notify_scraper_event(event_type, scraper_key=run.scraper_key,
                                         run_id=run.id, **kwargs)
            else:
                notify_scraper_event(event_type, scraper_key=run.scraper_key,
                                     run_id=run.id, **kwargs)
        except Exception:  # noqa: BLE001 — notifications never break the worker
            traceback.print_exc()

    def handle(self, *args, **options):
        # This worker is a dedicated OS subprocess — no actual async code runs here.
        # Playwright's sync API leaves a stopped (not running) event loop in the thread,
        # which trips Django's async-context guard when ORM calls are made afterwards.
        # The env var is Django's official escape hatch for this pattern.
        import os as _os
        _os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

        run_id = options["run_id"]
        query_id = options.get("query_id")
        raw_ids = options.get("query_ids")
        query_ids = [int(x) for x in raw_ids.split(",") if x.strip()] if raw_ids else None
        raw_locs = options.get("locations")
        locations = [x.strip() for x in raw_locs.split(",") if x.strip()] if raw_locs else None
        try:
            run = ScraperRun.objects.get(id=run_id)
        except ScraperRun.DoesNotExist:
            # The row may have been deleted in a race. Nothing to do — exit cleanly.
            self.stderr.write(f"ScraperRun {run_id} not found; nothing to run.")
            return

        # The scraper_key may be "facebook_events:q:5" for single-query runs;
        # extract the base key that maps to SCRAPERS.
        raw_key = run.scraper_key
        key = raw_key.split(":q:")[0] if ":q:" in raw_key else raw_key
        if key not in SCRAPERS:
            run.status = ScraperRun.Status.FAILED
            run.finished_at = timezone.now()
            run.error_message = f"Unknown key: {key}"
            run.save(update_fields=[
                "status", "finished_at", "error_message", "updated_at",
            ])
            self._notify_terminal(run, "failed", error_message=run.error_message)
            return

        # Conditional update: only transition QUEUED → RUNNING. If the run was
        # cancelled between queuing and now, update() returns 0 and we bail out
        # rather than overwriting the terminal CANCELLED status.
        updated = ScraperRun.objects.filter(
            id=run.id, status=ScraperRun.Status.QUEUED
        ).update(status=ScraperRun.Status.RUNNING, started_at=timezone.now())
        if not updated:
            return  # Already cancelled — exit without doing any work.
        run.refresh_from_db()

        # views.py writes discord_message_id after post_run_all_start() returns,
        # which can be a few seconds after subprocesses have already started.
        # Wait up to 10s for it to appear before deciding this is a solo run.
        if not run.discord_message_id:
            import time
            for _ in range(10):
                time.sleep(1)
                run.refresh_from_db(fields=["discord_message_id"])
                if run.discord_message_id:
                    break

        if run.discord_message_id:
            self._patch_batch_scoreboard(run)  # show this scraper as "running" in scoreboard
        else:
            notify_scraper_event("started", scraper_key=run.scraper_key, run_id=run.id)

        def flush_progress(data: dict) -> None:
            """Write incremental progress keys into extra_counts without clobbering other keys."""
            try:
                run.refresh_from_db(fields=["extra_counts", "discord_message_id"])
                merged = {**run.extra_counts, **data}
                ScraperRun.objects.filter(pk=run.pk).update(extra_counts=merged)
                run.extra_counts = merged  # keep in-memory copy in sync
                if "keyword_index" in data and run.discord_message_id:
                    self._patch_batch_scoreboard(run)
            except Exception:
                traceback.print_exc()

        # Attach the DB log handler so all Python logging from this process
        # (including scrapers, HTTP libraries, Playwright, etc.) flows into
        # ScraperRun.log_output and becomes visible in the UI.
        handler = _DBLogHandler(run_id)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter('%(levelname)s %(name)s: %(message)s'))
        root_logger = logging.getLogger()
        # Lower the root logger level so INFO/DEBUG records propagate to our handler.
        # Safe here because this is a dedicated worker subprocess with no request handling.
        original_level = root_logger.level
        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(handler)
        # The 'events' logger has propagate=False in settings.LOGGING so its records
        # never reach the root logger. Attach the handler directly so scraper logs
        # (events.scrapers.*) appear in the UI log terminal.
        events_logger = logging.getLogger("events")
        events_logger.addHandler(handler)

        try:
            scraper = SCRAPERS[key]()
            result = (
                scraper.run(query_ids=query_ids, locations=locations, on_progress=flush_progress)
                if query_ids
                else (
                    scraper.run(query_id=query_id, locations=locations, on_progress=flush_progress)
                    if query_id
                    else scraper.run(on_progress=flush_progress)
                )
            )
        except Exception as exc:
            tb = traceback.format_exc()
            handler.stop()
            root_logger.removeHandler(handler)
            events_logger.removeHandler(handler)
            root_logger.setLevel(original_level)
            run.status = ScraperRun.Status.FAILED
            run.finished_at = timezone.now()
            run.error_message = tb
            run.save(update_fields=[
                "status", "finished_at", "error_message", "updated_at",
            ])
            exc_str = str(exc)
            if exc_str.startswith("session_expired:"):
                # error_message form: "session_expired:<source> — <reason>"
                source = exc_str.split(":", 1)[1].split(" ", 1)[0].strip()
                self._notify_terminal(run, "session_expired", source=source)
            else:
                self._notify_terminal(run, "failed", error_message=tb)
            return

        # Final flush before status transition — frontend sees complete logs
        # in the same poll tick as the SUCCESS status.
        handler.stop()
        root_logger.removeHandler(handler)
        events_logger.removeHandler(handler)
        root_logger.setLevel(original_level)

        created, updated, extra_counts = _map_result(result)

        total_bytes = result.get("total_bytes", 0)
        if total_bytes:
            from events.scrapers.facebook_events import log_bandwidth
            from events.scrapers.social_proxy import social_proxy_configured
            from events.models import BandwidthLog
            _used_free = result.get("using_free_proxy")
            if _used_free is not None:
                proxy_type = BandwidthLog.PROXY_FREE if _used_free else BandwidthLog.PROXY_DATAIMPULSE
                try:
                    log_bandwidth(source=key, bytes_transferred=total_bytes, proxy_type=proxy_type, scraper_run=run)
                except Exception:
                    pass  # never block a successful run for logging

        run.status = ScraperRun.Status.SUCCESS
        run.finished_at = timezone.now()
        run.created_count = created
        run.updated_count = updated
        run.extra_counts = extra_counts
        run.save(update_fields=[
            "status", "finished_at", "created_count",
            "updated_count", "extra_counts", "updated_at",
        ])

        duration_s = (
            (run.finished_at - run.started_at).total_seconds()
            if run.started_at else 0
        )
        self._notify_terminal(
            run, "success",
            created_count=created, updated_count=updated, duration_s=duration_s,
        )
