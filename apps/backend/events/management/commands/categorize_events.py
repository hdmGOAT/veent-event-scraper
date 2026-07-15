"""Management command: AI-classify events into canonical agent_categories.

Examples:
    manage.py categorize_events                  # uncategorized only (default)
    manage.py categorize_events --all            # re-classify everything
    manage.py categorize_events --source planout # only one scraper source
    manage.py categorize_events --limit 5 --dry-run
    manage.py categorize_events --delay 0        # no throttle (careful)
"""

import time

from django.core.management.base import BaseCommand

from events.ai_categories import batch_categorize
from events.models import Event


class Command(BaseCommand):
    help = "Classify events into canonical agent_categories using the Groq API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            dest="reclassify_all",
            help="Re-classify every matching event, even if already categorized.",
        )
        parser.add_argument(
            "--source",
            help="Restrict to events from this scraper source key.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of events to classify.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be classified without writing to the DB.",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=2.0,
            metavar="SECONDS",
            help="Seconds to wait between batches to stay under Groq TPM limit (default: 2).",
        )

    def handle(self, *args, **options):
        batch_size = 20
        qs = Event.objects.all()

        if options.get("source"):
            qs = qs.filter(source=options["source"])

        if not options.get("reclassify_all"):
            qs = qs.filter(agent_categories=[])

        qs = qs.order_by("pk")

        if options.get("limit"):
            qs = qs[: options["limit"]]

        events = list(qs)
        total = len(events)

        if total == 0:
            self.stdout.write(self.style.WARNING("No matching events to classify."))
            return

        total_batches = (total + batch_size - 1) // batch_size

        if options.get("dry_run"):
            self.stdout.write(
                f"[dry-run] Would classify {total} event(s) in {total_batches} batch(es). No writes."
            )
            return

        delay = options["delay"]
        self.stdout.write(
            f"Classifying {total} event(s) in {total_batches} batch(es) "
            f"(inter-batch delay: {delay}s)..."
        )

        classified = 0
        skipped = 0

        for batch_num, start in enumerate(range(0, total, batch_size), 1):
            batch = events[start: start + batch_size]
            self.stdout.write(
                f"  Batch {batch_num}/{total_batches} ({len(batch)} events)...",
                ending=" ",
            )
            self.stdout.flush()

            labels_by_id = batch_categorize(batch)

            if not labels_by_id:
                self.stdout.write(self.style.WARNING("skipped (rate-limited, re-run to retry)"))
                skipped += len(batch)
            else:
                to_update = []
                for event in batch:
                    labels = labels_by_id.get(event.pk)
                    if labels is None:
                        continue
                    event.agent_categories = labels
                    to_update.append(event)

                if to_update:
                    Event.objects.bulk_update(to_update, ["agent_categories"])
                    classified += len(to_update)

                self.stdout.write(self.style.SUCCESS(f"done ({len(to_update)} classified, {classified} total)"))

            if batch_num < total_batches and delay > 0:
                time.sleep(delay)

        self.stdout.write("")
        summary = f"Finished. classified={classified} skipped={skipped} total={total}"
        if skipped:
            summary += " — re-run without --all to retry skipped batches"
        self.stdout.write(self.style.SUCCESS(summary))
