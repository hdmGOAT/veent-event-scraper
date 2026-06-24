from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Re-run Ollama LLM structuring on un-enriched facebook_posts Event rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=200,
            help="Max rows to process per run (default 200).",
        )
        parser.add_argument(
            "--dry-run", action="store_true", default=False,
            help="Log what would be updated without writing to DB.",
        )

    def handle(self, *args, **options):
        import re as _re
        from events.models import Event
        from events.scrapers.facebook_posts import _call_llm_structure, _parse_post_date

        limit = options["limit"]
        dry_run = options["dry_run"]

        qs = list(
            Event.objects.filter(source="facebook_posts", enriched_at__isnull=True)
            .order_by("-scraped_at")[:limit]
        )

        total = len(qs)
        self.stdout.write(
            f"Found {total} un-enriched facebook_posts rows (limit={limit}, dry_run={dry_run})"
        )

        updated = skipped = failed = 0

        for event in qs:
            try:
                raw_caption = event.raw_text or ""
                if not raw_caption:
                    # Fall back: strip "author: " prefix from name if raw_text is empty
                    raw_caption = _re.sub(r'^.+?:\s*', '', event.name or '')

                if len(raw_caption) < 20:
                    skipped += 1
                    continue

                author_name = event.organizer or ""
                timestamp = (
                    event.scraped_at.isoformat() if event.scraped_at
                    else event.post_date.isoformat() if event.post_date
                    else timezone.now().isoformat()
                )

                structured = _call_llm_structure(raw_caption, author_name, timestamp, [])

                if structured is None or structured.get("is_event") is False:
                    skipped += 1
                    continue

                updates = {"enriched_at": timezone.now()}

                if structured.get("title"):
                    updates["name"] = structured["title"][:300]

                if not event.description and structured.get("short_description"):
                    updates["description"] = structured["short_description"]

                if event.starts_at is None and structured.get("start_datetime"):
                    dt = _parse_post_date(structured["start_datetime"])
                    if dt:
                        updates["starts_at"] = dt

                if not event.organizer and structured.get("organizer_name"):
                    updates["organizer"] = structured["organizer_name"][:255]

                if dry_run:
                    self.stdout.write(
                        f"WOULD UPDATE id={event.pk} name={updates.get('name', event.name)!r}"
                    )
                else:
                    Event.objects.filter(pk=event.pk).update(**updates)
                    self.stdout.write(
                        f"UPDATED id={event.pk} name={updates.get('name', event.name)!r}"
                    )

                updated += 1

            except Exception as exc:
                self.stderr.write(f"ERROR id={event.pk}: {exc}")
                failed += 1

        self.stdout.write(
            f"\nDone: total={total} updated={updated} skipped={skipped} failed={failed}"
        )
