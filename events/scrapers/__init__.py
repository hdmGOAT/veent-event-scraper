"""Scraper registry.

Each scraper subclasses ``BaseScraper`` and is registered here under a
unique key. The ``scrape`` management command looks scrapers up by key.
"""
from .allevents import AllEventsCDOScraper
from .base import BaseScraper, ScrapedEvent, ScrapedOrganizer, ScrapedVenue
from .happeningnext import HappeningNextCDOScraper
from .places import GooglePlacesVenueScraper
from .racemeister import RacemeisterPartnersScraper

# key -> scraper class. Add new scrapers here.
SCRAPERS = {
    "google_places": GooglePlacesVenueScraper,
    "allevents_cdo": AllEventsCDOScraper,
    "happeningnext_cdo": HappeningNextCDOScraper,
    "racemeister_partners": RacemeisterPartnersScraper,
}

__all__ = ["BaseScraper", "ScrapedEvent", "ScrapedOrganizer", "ScrapedVenue", "SCRAPERS"]
