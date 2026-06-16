"""Scrape event-relevant venues in Cagayan de Oro via Google Places (New).

Coverage is per-type Text Search, capped at ~60 results per type — the result
set is approximate, not exhaustive. Each page request is a billable Places call.
"""
from django.core.management.base import BaseCommand, CommandError

from events.scrapers.places import GooglePlacesVenueScraper


class Command(BaseCommand):
    help = "Scrape Cagayan de Oro venues from Google Places (New) into Venue rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and print venues without saving to the database.",
        )

    def handle(self, *args, **options):
        scraper = GooglePlacesVenueScraper()
        if not scraper.api_key:
            raise CommandError(
                "PLACES_API_KEY is not set. Add it to your environment or .env "
                "(e.g. a line `PLACES_API_KEY=your_key` in the project root .env)."
            )

        if options["dry_run"]:
            self.stdout.write("DRY RUN — fetching, not saving …")
            count = 0
            for venue in scraper.fetch_venues():
                count += 1
                coords = (
                    f"({venue.latitude}, {venue.longitude})"
                    if venue.latitude is not None
                    else "(no coords)"
                )
                self.stdout.write(f"  - {venue.name} {coords} — {venue.address}")
            self._report_errors(scraper)
            self.stdout.write(self.style.SUCCESS(f"Would save {count} venue(s)."))
            self.stdout.write(
                self.style.WARNING(
                    "Note: per-type Text Search caps at ~60 results/type — "
                    "this is approximate coverage, not every venue in the city."
                )
            )
            return

        self.stdout.write("Scraping Cagayan de Oro venues from Google Places …")
        try:
            result = scraper.run()
        except Exception as exc:
            raise CommandError(f"Scrape failed: {exc}") from exc
        self._report_errors(scraper)
        self.stdout.write(
            self.style.SUCCESS(
                f"google_places: {result['created']} created, "
                f"{result['updated']} updated"
            )
        )

    def _report_errors(self, scraper):
        if not scraper.errors:
            return
        self.stderr.write(
            self.style.WARNING(
                f"{len(scraper.errors)} query(ies) failed and were skipped:"
            )
        )
        for query, msg in scraper.errors:
            self.stderr.write(self.style.WARNING(f"  - {query}: {msg}"))
