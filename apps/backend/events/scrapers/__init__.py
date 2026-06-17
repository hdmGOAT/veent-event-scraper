"""Scraper registry.

Each scraper subclasses ``BaseScraper`` and is registered here under a
unique key. The ``scrape`` management command looks scrapers up by key.
"""
from .allevents import AllEventsCDOScraper
from .base import BaseScraper, ScrapedEvent, ScrapedOrganizer, ScrapedVenue
from .eventbrite import EventbriteScraper
from .happeningnext import HappeningNextCDOScraper
from .myruntime import MyRuntimeScraper
from .places import GooglePlacesVenueScraper
from .luma import LumaScraper
from .planout import PlanoutScraper
from .racemeister import RacemeisterPartnersScraper
from .racemeister_events import RacemeisterEventsScraper
from .ticket2me import Ticket2MeScraper

# key -> scraper class. Add new scrapers here.
SCRAPERS = {
    "google_places": GooglePlacesVenueScraper,
    "allevents_cdo": AllEventsCDOScraper,
    "happeningnext_cdo": HappeningNextCDOScraper,
    "racemeister_partners": RacemeisterPartnersScraper,
    "racemeister_events": RacemeisterEventsScraper,
    "myruntime": MyRuntimeScraper,
    "ticket2me": Ticket2MeScraper,
    "planout": PlanoutScraper,
    "luma": LumaScraper,
    "eventbrite": EventbriteScraper,
}

__all__ = ["BaseScraper", "ScrapedEvent", "ScrapedOrganizer", "ScrapedVenue", "SCRAPERS"]
