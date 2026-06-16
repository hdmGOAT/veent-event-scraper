"""Scraper registry.

Each scraper subclasses ``BaseScraper`` and is registered here under a
unique key. The ``scrape`` management command looks scrapers up by key.
"""
from .base import BaseScraper, ScrapedEvent, ScrapedVenue
from .example import ExampleScraper
from .places import GooglePlacesVenueScraper

# key -> scraper class. Add new scrapers here.
SCRAPERS = {
    "example": ExampleScraper,
    "google_places": GooglePlacesVenueScraper,
}

__all__ = ["BaseScraper", "ScrapedEvent", "ScrapedVenue", "SCRAPERS"]
