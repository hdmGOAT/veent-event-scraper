from django.core.management.base import BaseCommand, CommandError

from events.scrapers import SCRAPERS


class Command(BaseCommand):
    help = "Run one or all registered event scrapers."

    def add_arguments(self, parser):
        parser.add_argument(
            "source",
            nargs="?",
            help="Scraper key to run. Omit to run all. Use --list to see keys.",
        )
        parser.add_argument(
            "--list", action="store_true", help="List available scrapers and exit."
        )

    def handle(self, *args, **options):
        if options["list"]:
            self.stdout.write("Available scrapers:")
            for key in sorted(SCRAPERS):
                self.stdout.write(f"  - {key}")
            return

        source = options["source"]
        if source:
            if source not in SCRAPERS:
                raise CommandError(
                    f"Unknown scraper '{source}'. "
                    f"Available: {', '.join(sorted(SCRAPERS)) or '(none)'}"
                )
            keys = [source]
        else:
            keys = sorted(SCRAPERS)

        if not keys:
            self.stdout.write(self.style.WARNING("No scrapers registered."))
            return

        for key in keys:
            self.stdout.write(f"Running scraper: {key} …")
            try:
                result = SCRAPERS[key]().run()
            except Exception as exc:  # keep one failing scraper from killing the rest
                self.stderr.write(self.style.ERROR(f"  {key} failed: {exc}"))
                continue
            self.stdout.write(
                self.style.SUCCESS(
                    f"  {key}: {result['created']} created, {result['updated']} updated"
                )
            )
