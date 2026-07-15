"""Backfill post_date for structured scrapers that now expose a creation timestamp.

Runs the fetch() iterator for each of the four supported sources, then updates
only the post_date column on existing events where it is currently NULL.
No events are created; existing records are only patched.

Sources: eventbrite, clickthecity, planout, eventsize

Usage:
    python manage.py backfill_post_date
    python manage.py backfill_post_date --source eventbrite
    python manage.py backfill_post_date --dry-run
"""
import logging

from django.core.management.base import BaseCommand

from events.models import Event

logger = logging.getLogger(__name__)

_SOURCES = ["eventbrite", "clickthecity", "planout", "eventsize"]


def _scraper_for(source: str):
    if source == "eventbrite":
        from events.scrapers.eventbrite import EventbriteScraper
        return EventbriteScraper()
    if source == "clickthecity":
        from events.scrapers.clickthecity import ClickTheCityScraper
        return ClickTheCityScraper()
    if source == "planout":
        from events.scrapers.planout import PlanoutScraper
        return PlanoutScraper()
    if source == "eventsize":
        from events.scrapers.eventsize import EventsizeScraper
        return EventsizeScraper()
    raise ValueError(f"Unknown source: {source}")


class Command(BaseCommand):
    help = "Backfill post_date for eventbrite / clickthecity / planout / eventsize events."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            choices=_SOURCES,
            default=None,
            help="Single source to backfill. Omit to run all four.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without writing to the database.",
        )

    def handle(self, *args, **options):
        sources = [options["source"]] if options["source"] else _SOURCES
        dry_run = options["dry_run"]

        total_updated = total_skipped = total_no_date = 0

        for source in sources:
            self.stdout.write(f"\n{'─' * 60}")
            self.stdout.write(f"Source: {source}  [{'DRY RUN' if dry_run else 'live'}]")

            # Pre-index DB events missing post_date, keyed by external_id.
            null_qs = Event.objects.filter(
                source=source,
                post_date__isnull=True,
                external_id__isnull=False,
            ).exclude(external_id="")
            null_ids: dict[str, int] = {e.external_id: e.pk for e in null_qs.only("external_id")}

            if not null_ids:
                self.stdout.write(f"  No events missing post_date for {source}.")
                continue

            self.stdout.write(f"  {len(null_ids)} events missing post_date — fetching from API…")

            updated = skipped = no_date = 0
            try:
                scraper = _scraper_for(source)
                for se in scraper.fetch():
                    if not se.external_id or se.external_id not in null_ids:
                        continue
                    if se.post_date is None:
                        no_date += 1
                        continue
                    pk = null_ids[se.external_id]
                    if not dry_run:
                        Event.objects.filter(pk=pk).update(post_date=se.post_date)
                    self.stdout.write(
                        f"  {'[dry]' if dry_run else '✓'} {se.external_id[:40]}  "
                        f"post_date={se.post_date.date()}"
                    )
                    updated += 1
            except Exception as exc:
                self.stderr.write(f"  ERROR fetching {source}: {exc}")
                logger.exception("backfill_post_date: fetch failed for source=%s", source)

            self.stdout.write(
                f"  Done.  updated={updated}  no_date_in_api={no_date}  "
                f"(not_returned_by_api={len(null_ids) - updated - no_date})"
            )
            total_updated += updated
            total_skipped += skipped
            total_no_date += no_date

        self.stdout.write(
            f"\n{'─' * 60}\n"
            f"All done.  total_updated={total_updated}"
            + (" (dry run — nothing written)" if dry_run else "")
        )
