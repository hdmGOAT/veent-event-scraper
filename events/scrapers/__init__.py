"""Scraper registry.

Each scraper subclasses ``BaseScraper`` and is registered here under a
unique key. The ``scrape`` management command looks scrapers up by key.
"""
from .allevents import AllEventsCDOScraper
from .base import BaseScraper, ScrapedEvent, ScrapedVenue
from .happeningnext import HappeningNextCDOScraper
from .places import GooglePlacesVenueScraper

# key -> scraper class. Add new scrapers here.
SCRAPERS = {
    "google_places": GooglePlacesVenueScraper,
    "allevents_cdo": AllEventsCDOScraper,
    "happeningnext_cdo": HappeningNextCDOScraper,
}

__all__ = ["BaseScraper", "ScrapedEvent", "ScrapedVenue", "SCRAPERS"]
