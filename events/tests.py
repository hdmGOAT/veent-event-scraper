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
