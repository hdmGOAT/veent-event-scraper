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

# Fields to request. Keeping the mask tight controls billing tier and payload.
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.websiteUri",
        "places.googleMapsUri",
        "nextPageToken",
    ]
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
    def _to_venue(place: dict) -> ScrapedVenue:
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

    def run(self) -> dict:
        return save_venues(self.source, list(self.fetch_venues()))
