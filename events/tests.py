from unittest import mock

from django.test import TestCase

from events.models import Venue
from events.scrapers.base import ScrapedVenue, save_venues
from events.scrapers.places import GooglePlacesVenueScraper


def _fake_response(payload):
    resp = mock.Mock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


class SaveVenuesDedupTests(TestCase):
    def test_same_place_id_upserts_not_duplicates(self):
        source = "google_places"
        first = ScrapedVenue(
            name="Limketkai Center",
            city="Cagayan de Oro",
            place_id="ChIJ-test-123",
        )
        r1 = save_venues(source, [first])
        self.assertEqual(r1["created"], 1)
        self.assertEqual(r1["updated"], 0)

        # Same place_id, changed details → update, no new row.
        second = ScrapedVenue(
            name="Limketkai Center (Updated)",
            city="Cagayan de Oro",
            website="https://limketkai.example",
            place_id="ChIJ-test-123",
        )
        r2 = save_venues(source, [second])
        self.assertEqual(r2["created"], 0)
        self.assertEqual(r2["updated"], 1)

        self.assertEqual(Venue.objects.filter(source=source).count(), 1)
        venue = Venue.objects.get(place_id="ChIJ-test-123")
        self.assertEqual(venue.website, "https://limketkai.example")

    def test_distinct_place_ids_create_separate_rows(self):
        source = "google_places"
        venues = [
            ScrapedVenue(name="Venue A", place_id="id-a"),
            ScrapedVenue(name="Venue B", place_id="id-b"),
        ]
        result = save_venues(source, venues)
        self.assertEqual(result["created"], 2)
        self.assertEqual(Venue.objects.count(), 2)

    def test_unique_slugs_for_same_name(self):
        source = "google_places"
        venues = [
            ScrapedVenue(name="City Hall", place_id="id-1"),
            ScrapedVenue(name="City Hall", place_id="id-2"),
        ]
        save_venues(source, venues)
        slugs = set(Venue.objects.values_list("slug", flat=True))
        self.assertEqual(len(slugs), 2)


class GooglePlacesScraperTests(TestCase):
    SAMPLE_PLACE = {
        "id": "ChIJabc123",
        "displayName": {"text": "Limketkai Atrium"},
        "formattedAddress": "Lapasan, Cagayan de Oro, Misamis Oriental",
        "location": {"latitude": 8.4822, "longitude": 124.6566},
        "websiteUri": "https://limketkai.example",
        "googleMapsUri": "https://maps.google.com/?cid=123",
    }

    def test_parses_place_fields(self):
        scraper = GooglePlacesVenueScraper(api_key="test-key")
        venue = scraper._to_venue(self.SAMPLE_PLACE)
        self.assertEqual(venue.name, "Limketkai Atrium")
        self.assertEqual(venue.place_id, "ChIJabc123")
        self.assertEqual(venue.latitude, 8.4822)
        self.assertEqual(venue.longitude, 124.6566)
        self.assertEqual(venue.city, "Cagayan de Oro")
        self.assertEqual(venue.country, "Philippines")
        self.assertEqual(venue.website, "https://limketkai.example")
        self.assertEqual(venue.source_url, "https://maps.google.com/?cid=123")

    def test_missing_api_key_raises(self):
        scraper = GooglePlacesVenueScraper(api_key="")
        with self.assertRaises(RuntimeError):
            list(scraper.fetch_venues())

    @mock.patch("events.scrapers.places.requests.post")
    def test_fetch_dedups_across_queries(self, mock_post):
        # Every query/page returns the same single place, no next page.
        mock_post.return_value = _fake_response({"places": [self.SAMPLE_PLACE]})
        scraper = GooglePlacesVenueScraper(api_key="test-key")
        venues = list(scraper.fetch_venues())
        # Same place_id seen across all type queries → deduped to one.
        self.assertEqual(len(venues), 1)
        self.assertEqual(venues[0].place_id, "ChIJabc123")

    @mock.patch("events.scrapers.places.requests.post")
    def test_run_persists_venues(self, mock_post):
        mock_post.return_value = _fake_response({"places": [self.SAMPLE_PLACE]})
        scraper = GooglePlacesVenueScraper(api_key="test-key")
        result = scraper.run()
        self.assertEqual(result["created"], 1)
        self.assertEqual(Venue.objects.filter(source="google_places").count(), 1)


class VenueCategoryAndAmenityTests(TestCase):
    """Coverage for category / about / amenity capture added on top of the
    base Places scraper."""

    RICH_PLACE = {
        "id": "ChIJrich",
        "displayName": {"text": "Ultra Winds Mountain Resort"},
        "formattedAddress": "Kitanglad Range, Cagayan de Oro",
        "location": {"latitude": 8.48, "longitude": 124.65},
        "primaryType": "resort_hotel",
        "primaryTypeDisplayName": {"text": "Resort hotel"},
        "types": ["resort_hotel", "lodging", "point_of_interest"],
        "editorialSummary": {"text": "Laid-back resort with sweeping views."},
        "rating": 4.3,
        "priceLevel": "PRICE_LEVEL_MODERATE",
        "servesBreakfast": True,
        "goodForChildren": True,
        "allowsDogs": False,            # falsy → dropped
        "liveMusic": None,              # missing/None → dropped
        "accessibilityOptions": {
            "wheelchairAccessibleEntrance": True,
            "wheelchairAccessibleParking": False,
        },
        "parkingOptions": {"freeParkingLot": True},
        "paymentOptions": {},
    }

    def test_to_venue_extracts_category_about_types(self):
        v = GooglePlacesVenueScraper._to_venue(self.RICH_PLACE)
        self.assertEqual(v.primary_type, "resort_hotel")
        self.assertEqual(v.primary_type_display, "Resort hotel")
        self.assertEqual(v.types, ["resort_hotel", "lodging", "point_of_interest"])
        self.assertEqual(v.about, "Laid-back resort with sweeping views.")
        self.assertEqual(v.rating, 4.3)
        self.assertEqual(v.price_level, "PRICE_LEVEL_MODERATE")

    def test_normalize_amenities_keeps_only_truthy_and_flattens(self):
        amenities = GooglePlacesVenueScraper._normalize_amenities(self.RICH_PLACE)
        self.assertEqual(
            amenities,
            {
                "Serves breakfast": True,
                "Kid-friendly": True,
                "Wheelchair-accessible entrance": True,
                "Free parking lot": True,
            },
        )
        # Falsy / missing flags must not appear.
        self.assertNotIn("Pet-friendly", amenities)
        self.assertNotIn("Live music", amenities)
        self.assertNotIn("Wheelchair-accessible parking", amenities)

    def test_missing_optional_fields_degrade_to_empty(self):
        v = GooglePlacesVenueScraper._to_venue({"id": "x", "displayName": {"text": "Bare"}})
        self.assertEqual(v.primary_type_display, "")
        self.assertEqual(v.about, "")
        self.assertEqual(v.types, [])
        self.assertEqual(v.amenities, {})
        self.assertIsNone(v.rating)

    def test_upsert_persists_new_fields(self):
        v = GooglePlacesVenueScraper._to_venue(self.RICH_PLACE)
        save_venues("google_places", [v])
        row = Venue.objects.get(place_id="ChIJrich")
        self.assertEqual(row.primary_type_display, "Resort hotel")
        self.assertEqual(row.about, "Laid-back resort with sweeping views.")
        self.assertIn("Serves breakfast", row.amenities)
        self.assertEqual(row.types, ["resort_hotel", "lodging", "point_of_interest"])
