"""Scraper registry.

Each scraper subclasses ``BaseScraper`` and is registered here under a
unique key. The ``scrape`` management command looks scrapers up by key.
"""
from .allevents import AllEventsCDOScraper
from .facebook_events import FacebookEventsScraper
from .facebook_posts import FacebookPostsScraper
from .instagram_posts import InstagramPostsScraper
from .clickthecity import ClickTheCityScraper
from .allevents_api import AllEventsAPIScraper
from .allevents_ph import AllEventsPHScraper
from .allevents_ph_organizers import AllEventsPHOrganizersScraper
from .base import BaseScraper, ScrapedEvent, ScrapedOrganizer, ScrapedVenue
from .eventbee import EventbeeScraper
from .eventbookings import EventBookingsScraper
from .eventbrite import EventbriteScraper
from .sistic import SisticScraper
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
from .meetup import MeetupScraper
from .ticketspice import TicketSpiceScraper
from .eventalways import EventAlwaysScraper
from .tessera import TesseraScraper

# Scrapers excluded from run-all (still triggerable individually).
RUN_ALL_EXCLUDED = {"google_places"}

# key -> scraper class. Add new scrapers here.
SCRAPERS = {
    "facebook_events":  FacebookEventsScraper,
    "facebook_posts":   FacebookPostsScraper,
    "instagram_posts":  InstagramPostsScraper,
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
    "sistic": SisticScraper,
    "ticketspice": TicketSpiceScraper,
    "clickthecity": ClickTheCityScraper,
    "meetup": MeetupScraper,
    "eventalways": EventAlwaysScraper,
    "tessera": TesseraScraper,
}

__all__ = ["BaseScraper", "RUN_ALL_EXCLUDED", "SCRAPERS", "ScrapedEvent", "ScrapedOrganizer", "ScrapedVenue"]
