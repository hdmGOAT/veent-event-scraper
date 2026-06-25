"""Google Places API (New) venue scraper for Cagayan de Oro City.

Uses the Text Search endpoint (``places.googleapis.com/v1/places:searchText``)
with one query per event-relevant venue type. The New API returns full place
details (address, location, website, phone, Maps URI) directly in the search
response via a field mask, so no separate Place Details call is needed.

Coverage note: Text Search caps each query at ~60 results (3 pages of 20).
Running one query per type widens coverage but the dataset is **approximate,
not exhaustive**.

Billing note: each page request is a billable Text Search call. Keep the type
list small and prefer ``--dry-run`` while iterating.
"""
from __future__ import annotations

from typing import Iterable

import requests
from django.conf import settings

from .base import ScrapedVenue, save_venues

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Scalar amenity booleans returned by Places API (New). Mapping value is the
# human label surfaced in the UI. Only truthy flags are kept per venue.
SCALAR_AMENITIES = {
    "allowsDogs": "Pet-friendly",
    "goodForChildren": "Kid-friendly",
    "goodForGroups": "Good for groups",
    "goodForWatchingSports": "Good for watching sports",
    "restroom": "Restroom",
    "servesBreakfast": "Serves breakfast",
    "servesLunch": "Serves lunch",
    "servesDinner": "Serves dinner",
    "servesBrunch": "Serves brunch",
    "servesBeer": "Serves beer",
    "servesWine": "Serves wine",
    "servesCocktails": "Serves cocktails",
    "servesCoffee": "Serves coffee",
    "servesDessert": "Serves dessert",
    "servesVegetarianFood": "Vegetarian options",
    "outdoorSeating": "Outdoor seating",
    "liveMusic": "Live music",
    "menuForChildren": "Kids' menu",
    "reservable": "Reservable",
    "takeout": "Takeout",
    "delivery": "Delivery",
    "dineIn": "Dine-in",
    "curbsidePickup": "Curbside pickup",
}

# Nested amenity objects: {api_field: {sub_key: human label}}.
NESTED_AMENITIES = {
    "accessibilityOptions": {
        "wheelchairAccessibleParking": "Wheelchair-accessible parking",
        "wheelchairAccessibleEntrance": "Wheelchair-accessible entrance",
        "wheelchairAccessibleRestroom": "Wheelchair-accessible restroom",
        "wheelchairAccessibleSeating": "Wheelchair-accessible seating",
    },
    "parkingOptions": {
        "freeParkingLot": "Free parking lot",
        "paidParkingLot": "Paid parking lot",
        "freeStreetParking": "Free street parking",
        "paidStreetParking": "Paid street parking",
        "valetParking": "Valet parking",
        "freeGarageParking": "Free garage parking",
        "paidGarageParking": "Paid garage parking",
    },
    "paymentOptions": {
        "acceptsCreditCards": "Accepts credit cards",
        "acceptsDebitCards": "Accepts debit cards",
        "acceptsCashOnly": "Cash only",
        "acceptsNfc": "Accepts NFC payments",
    },
}

# Fields to request. Keeping the mask tight controls billing tier and payload.
# NOTE: the category/about/amenity fields below move requests into a higher
# Places API SKU tier (Enterprise / Enterprise + Atmosphere) than the basic
# location fields — i.e. each call is billed at a higher rate.
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.websiteUri",
        "places.googleMapsUri",
        # Category / classification
        "places.primaryType",
        "places.primaryTypeDisplayName",
        "places.types",
        # "About" / editorial summary
        "places.editorialSummary",
        # Ratings / price
        "places.rating",
        "places.userRatingCount",
        "places.priceLevel",
        # Amenity objects
        "places.accessibilityOptions",
        "places.parkingOptions",
        "places.paymentOptions",
    ]
    # Scalar amenity booleans (kept in sync with SCALAR_AMENITIES).
    + [f"places.{key}" for key in SCALAR_AMENITIES]
    + ["nextPageToken"]
)

# Event-relevant venue types, expressed as Text Search queries scoped to CDO.
CITY = "Cagayan de Oro City, Philippines"
VENUE_QUERIES = [
    "convention centers in {city}",
    "event venues in {city}",
    "theaters and performing arts venues in {city}",
    "auditoriums in {city}",
    "stadiums and sports arenas in {city}",
    "night clubs in {city}",
    "museums in {city}",
    "hotels with function halls in {city}",
]

MAX_PAGES = 3  # Text Search hard cap: 3 pages × 20 = 60 results per query.
REQUEST_TIMEOUT = 30


class GooglePlacesVenueScraper:
    """Collects event-relevant venues in Cagayan de Oro via Places API (New)."""

    source = "google_places"

    def __init__(self, api_key: str | None = None):
        # None → fall back to settings; an explicit "" stays empty (no key).
        self.api_key = settings.PLACES_API_KEY if api_key is None else api_key
        # Per-query failures collected here so one bad request doesn't abort the run.
        self.errors: list[tuple[str, str]] = []

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        }

    def _search(self, text_query: str) -> Iterable[dict]:
        """Yield raw place dicts for one query, following pagination."""
        page_token = None
        for _ in range(MAX_PAGES):
            body = {"textQuery": text_query, "regionCode": "PH"}
            if page_token:
                body["pageToken"] = page_token
            resp = requests.post(
                SEARCH_URL,
                headers=self._headers(),
                json=body,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            yield from data.get("places", [])
            page_token = data.get("nextPageToken")
            if not page_token:
                break

    @staticmethod
    def _normalize_amenities(place: dict) -> dict:
        """Flatten Places amenity fields into a {label: True} map.

        Keeps only truthy flags so the UI renders just the amenities the place
        actually has. Scalar booleans and nested option objects are merged into
        one flat dict keyed by human-readable label.
        """
        amenities: dict[str, bool] = {}
        for key, label in SCALAR_AMENITIES.items():
            if place.get(key) is True:
                amenities[label] = True
        for field_name, sub_map in NESTED_AMENITIES.items():
            obj = place.get(field_name) or {}
            for sub_key, label in sub_map.items():
                if obj.get(sub_key) is True:
                    amenities[label] = True
        return amenities

    @classmethod
    def _to_venue(cls, place: dict) -> ScrapedVenue:
        loc = place.get("location") or {}
        return ScrapedVenue(
            name=(place.get("displayName") or {}).get("text", "").strip(),
            address=place.get("formattedAddress", ""),
            city="Cagayan de Oro",
            country="Philippines",
            website=place.get("websiteUri", ""),
            latitude=loc.get("latitude"),
            longitude=loc.get("longitude"),
            source_url=place.get("googleMapsUri", ""),
            place_id=place.get("id", ""),
            primary_type=place.get("primaryType", ""),
            primary_type_display=(
                place.get("primaryTypeDisplayName") or {}
            ).get("text", ""),
            types=place.get("types") or [],
            about=(place.get("editorialSummary") or {}).get("text", ""),
            amenities=cls._normalize_amenities(place),
            rating=place.get("rating"),
            price_level=place.get("priceLevel", ""),
        )

    def fetch_venues(self) -> Iterable[ScrapedVenue]:
        """Yield deduplicated ScrapedVenue across all configured type queries."""
        if not self.api_key:
            raise RuntimeError(
                "PLACES_API_KEY is not set. Add it to your environment or .env."
            )
        seen: set[str] = set()
        for template in VENUE_QUERIES:
            query = template.format(city=CITY)
            try:
                # Materialize per query so a mid-pagination failure is isolated
                # to this query rather than aborting the whole run.
                places = list(self._search(query))
            except Exception as exc:  # one failing query must not kill the rest
                self.errors.append((query, str(exc)))
                continue
            for place in places:
                pid = place.get("id", "")
                # Same venue can surface under multiple type queries.
                if pid and pid in seen:
                    continue
                if pid:
                    seen.add(pid)
                venue = self._to_venue(place)
                if venue.name:
                    yield venue

    def run(self, **_kwargs) -> dict:
        return save_venues(self.source, list(self.fetch_venues()))
