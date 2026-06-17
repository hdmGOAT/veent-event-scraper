"""Management command: AI-classify events into canonical agent_categories.

Examples:
    manage.py categorize_events                  # uncategorized only (default)
    manage.py categorize_events --all            # re-classify everything
    manage.py categorize_events --source planout # only one scraper source
    manage.py categorize_events --limit 5 --dry-run
"""

from django.core.management.base import BaseCommand

from events.ai_categories import categorize_events_by_ids
from events.models import Event


class Command(BaseCommand):
    help = "Classify events into canonical agent_categories using the Claude CLI."

    def add_arguments(self, parser):
        parser.add_argument(
            "--uncategorized",
            action="store_true",
            help="Only classify events with empty agent_categories (default behavior).",
        )
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

    def handle(self, *args, **options):
        batch_size = 20
        qs = Event.objects.all()

        if options.get("source"):
            qs = qs.filter(source=options["source"])

        # Default to uncategorized (empty agent_categories) unless --all is passed.
        if not options.get("reclassify_all"):
            qs = qs.filter(agent_categories=[])

        qs = qs.order_by("pk")

        if options.get("limit"):
            qs = qs[: options["limit"]]

        ids = list(qs.values_list("pk", flat=True))
        total = len(ids)

        if total == 0:
            self.stdout.write(self.style.WARNING("No matching events to classify."))
            return

        if options.get("dry_run"):
            self.stdout.write(
                f"[dry-run] Would classify {total} event(s) "
                f"in {(total + batch_size - 1) // batch_size} batch(es). No writes."
            )
            return

        num_batches = (total + batch_size - 1) // batch_size
        classified = 0
        for i, start in enumerate(range(0, total, batch_size), start=1):
            batch_ids = ids[start : start + batch_size]
            self.stdout.write(f"  batch {i}/{num_batches} ({len(batch_ids)} events) …")
            classified += categorize_events_by_ids(
                batch_ids,
                batch_size=batch_size,
                skip_classified=not options.get("reclassify_all"),
            )

        self.stdout.write(
            self.style.SUCCESS(f"Classified {classified}/{total} event(s).")
        )
