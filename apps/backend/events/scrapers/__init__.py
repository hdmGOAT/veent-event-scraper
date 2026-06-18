"""Scraper registry.

Each scraper subclasses ``BaseScraper`` and is registered here under a
unique key. The ``scrape`` management command looks scrapers up by key.
"""
from .allevents import AllEventsCDOScraper
from .clickthecity import ClickTheCityScraper
from .allevents_api import AllEventsAPIScraper
from .allevents_ph import AllEventsPHScraper
from .allevents_ph_organizers import AllEventsPHOrganizersScraper
from .base import BaseScraper, ScrapedEvent, ScrapedOrganizer, ScrapedVenue
from .eventbee import EventbeeScraper
from .eventbookings import EventBookingsScraper
from .eventbrite import EventbriteScraper
from .eventsize import EventsizeScraper
from .happeningnext import HappeningNextCDOScraper
from .myruntime import MyRuntimeScraper
from .places import GooglePlacesVenueScraper
from .luma import LumaScraper
from .planout import PlanoutScraper
from .racemeister import RacemeisterPartnersScraper
from .racemeister_events import RacemeisterEventsScraper
from .ticket2me import Ticket2MeScraper
from .ticketmelon import TicketmelonScraper
from .ticketspice import TicketSpiceScraper

# key -> scraper class. Add new scrapers here.
SCRAPERS = {
    "google_places": GooglePlacesVenueScraper,
    "allevents_cdo": AllEventsCDOScraper,
    "allevents_in": AllEventsPHScraper,
    "allevents_in_organizers": AllEventsPHOrganizersScraper,
    "happeningnext_cdo": HappeningNextCDOScraper,
    "racemeister_partners": RacemeisterPartnersScraper,
    "racemeister_events": RacemeisterEventsScraper,
    "myruntime": MyRuntimeScraper,
    "ticket2me": Ticket2MeScraper,
    "planout": PlanoutScraper,
    "luma": LumaScraper,
    "eventbee": EventbeeScraper,
    "ticketmelon": TicketmelonScraper,
    "eventbrite": EventbriteScraper,
    "eventbookings": EventBookingsScraper,
    "eventsize": EventsizeScraper,
    "ticketspice": TicketSpiceScraper,
    "clickthecity": ClickTheCityScraper,
}

__all__ = ["BaseScraper", "ScrapedEvent", "ScrapedOrganizer", "ScrapedVenue", "SCRAPERS"]
