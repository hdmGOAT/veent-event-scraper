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
from django.utils import timezone

from events.models import ScraperRun
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
            with connection.cursor() as cur:
                cur.execute(
                    'UPDATE events_scraperrun SET log_output = log_output || %s WHERE id = %s',
                    [chunk, self._run_id],
                )
        except Exception:
            pass  # Don't let log flush errors crash the scraper

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

    def handle(self, *args, **options):
        run_id = options["run_id"]
        try:
            run = ScraperRun.objects.get(id=run_id)
        except ScraperRun.DoesNotExist:
            # The row may have been deleted in a race. Nothing to do — exit cleanly.
            self.stderr.write(f"ScraperRun {run_id} not found; nothing to run.")
            return

        key = run.scraper_key
        if key not in SCRAPERS:
            run.status = ScraperRun.Status.FAILED
            run.finished_at = timezone.now()
            run.error_message = f"Unknown key: {key}"
            run.save(update_fields=[
                "status", "finished_at", "error_message", "updated_at",
            ])
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

        try:
            result = SCRAPERS[key]().run()
        except Exception:
            tb = traceback.format_exc()
            handler.stop()
            root_logger.removeHandler(handler)
            root_logger.setLevel(original_level)
            run.status = ScraperRun.Status.FAILED
            run.finished_at = timezone.now()
            run.error_message = tb
            run.save(update_fields=[
                "status", "finished_at", "error_message", "updated_at",
            ])
            return

        # Final flush before status transition — frontend sees complete logs
        # in the same poll tick as the SUCCESS status.
        handler.stop()
        root_logger.removeHandler(handler)
        root_logger.setLevel(original_level)

        created, updated, extra_counts = _map_result(result)
        run.status = ScraperRun.Status.SUCCESS
        run.finished_at = timezone.now()
        run.created_count = created
        run.updated_count = updated
        run.extra_counts = extra_counts
        run.save(update_fields=[
            "status", "finished_at", "created_count",
            "updated_count", "extra_counts", "updated_at",
        ])
