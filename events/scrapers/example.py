"""A reference scraper showing the shape of a real one.

Replace ``fetch`` with actual HTTP requests + parsing. The commented block
sketches the typical requests + BeautifulSoup pattern.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Iterable

from django.utils import timezone

from .base import BaseScraper, ScrapedEvent, ScrapedVenue


class ExampleScraper(BaseScraper):
    source = "example"

    def fetch(self) -> Iterable[ScrapedEvent]:
        # --- Real scrapers look roughly like this: ---
        # import requests
        # from bs4 import BeautifulSoup
        # resp = requests.get("https://example.com/events", timeout=30)
        # resp.raise_for_status()
        # soup = BeautifulSoup(resp.text, "lxml")
        # for el in soup.select(".event-card"):
        #     yield ScrapedEvent(
        #         name=el.select_one(".title").get_text(strip=True),
        #         external_id=el["data-id"],
        #         url=el.select_one("a")["href"],
        #         venue=ScrapedVenue(name=el.select_one(".venue").get_text(strip=True)),
        #     )

        # Demo data so the UI has something to show out of the box:
        venue = ScrapedVenue(
            name="The Demo Hall",
            address="123 Main St",
            city="Manila",
            country="Philippines",
            website="https://example.com",
        )
        now = timezone.now()
        for i in range(1, 4):
            yield ScrapedEvent(
                name=f"Sample Event {i}",
                description="Placeholder event created by the example scraper.",
                starts_at=now + timedelta(days=i),
                ends_at=now + timedelta(days=i, hours=2),
                url="https://example.com/events/sample",
                category="Demo",
                external_id=f"sample-{i}",
                source_url="https://example.com/events",
                venue=venue,
            )
