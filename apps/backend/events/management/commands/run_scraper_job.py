"""Worker command that owns a single ScraperRun's lifecycle.

Launched by ``trigger_scraper_run`` (see events/runner.py) as a standalone OS
process so it can be killed — together with any children it spawns (e.g.
Playwright's chromium) — when an admin cancels the run. The parent stores this
process's pid on the ScraperRun row *before* this command begins its work, so the
command itself does not need to record the pid.
"""
import traceback

from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import ScraperRun
from events.runner import _map_result
from events.scrapers import SCRAPERS


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

        run.status = ScraperRun.Status.RUNNING
        run.started_at = timezone.now()
        run.save(update_fields=["status", "started_at", "updated_at"])

        try:
            result = SCRAPERS[key]().run()
        except Exception:
            tb = traceback.format_exc()
            run.status = ScraperRun.Status.FAILED
            run.finished_at = timezone.now()
            run.error_message = tb
            run.save(update_fields=[
                "status", "finished_at", "error_message", "updated_at",
            ])
            return

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
