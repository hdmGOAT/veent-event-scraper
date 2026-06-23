import inspect

from django.core.management.base import BaseCommand, CommandError

from events.scrapers import SCRAPERS


def _positive_int(value):
    ivalue = int(value)
    if ivalue <= 0:
        raise ValueError
    return ivalue


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
        parser.add_argument(
            "--query-id", type=_positive_int, default=None, metavar="ID",
            help="Run only the SearchQuery with this ID (facebook_events only).",
        )
        parser.add_argument(
            "--max-events", type=_positive_int, default=None, metavar="N",
            help="Stop after processing N events per query (useful for quick tests).",
        )

    def handle(self, *args, **options):
        if options["list"]:
            self.stdout.write("Available scrapers:")
            for key in sorted(SCRAPERS):
                self.stdout.write(f"  - {key}")
            return

        source = options["source"]
        if not source and (options.get("query_id") is not None or options.get("max_events") is not None):
            raise CommandError(
                "--query-id and --max-events require a specific source to be specified."
            )
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
            run_kwargs = {}
            if options["query_id"] is not None:
                run_kwargs["query_id"] = options["query_id"]
            if options["max_events"] is not None:
                run_kwargs["max_events"] = options["max_events"]
            try:
                scraper = SCRAPERS[key]()
                accepted = inspect.signature(scraper.run).parameters
                filtered_kwargs = {k: v for k, v in run_kwargs.items() if k in accepted}
                result = scraper.run(**filtered_kwargs)
            except Exception as exc:  # keep one failing scraper from killing the rest
                self.stderr.write(self.style.ERROR(f"  {key} failed: {exc}"))
                continue
            self.stdout.write(
                self.style.SUCCESS(
                    f"  {key}: {result['created']} created, {result['updated']} updated"
                )
            )
