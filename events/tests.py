from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

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


class VenueVerificationTests(TestCase):
    """Manual admin approve/reject review of venues."""

    def test_new_venue_defaults_to_pending(self):
        venue = Venue.objects.create(name="Some Hall", slug="some-hall")
        self.assertEqual(venue.verification_status, Venue.VerificationStatus.PENDING)

    def test_scraped_venue_starts_pending(self):
        save_venues("google_places", [ScrapedVenue(name="Fresh Venue", place_id="vp-1")])
        row = Venue.objects.get(place_id="vp-1")
        self.assertEqual(row.verification_status, Venue.VerificationStatus.PENDING)

    def test_rescrape_preserves_verification_status(self):
        """A reviewer's decision must survive a re-scrape of the same venue.

        The upsert path writes only scraped fields, so verification_status set
        by an admin should not be reset to pending on the next scrape run.
        """
        source = "google_places"
        save_venues(source, [ScrapedVenue(name="Reviewed Venue", place_id="vp-keep")])
        row = Venue.objects.get(place_id="vp-keep")
        row.verification_status = Venue.VerificationStatus.VERIFIED
        row.save()

        # Re-scrape the same place with updated details.
        save_venues(source, [ScrapedVenue(
            name="Reviewed Venue", place_id="vp-keep",
            website="https://reviewed.example",
        )])

        row.refresh_from_db()
        self.assertEqual(row.website, "https://reviewed.example")  # scrape applied
        self.assertEqual(row.verification_status, Venue.VerificationStatus.VERIFIED)


class ReviewUITests(TestCase):
    """Staff-only custom venue review UI (dashboard / queue / status endpoint)."""

    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(
            username="staffer", password="pw12345", is_staff=True
        )
        self.dashboard_url = reverse("events:review_dashboard")

    def _venue(self, name, slug, status=Venue.VerificationStatus.PENDING, **kw):
        return Venue.objects.create(name=name, slug=slug, verification_status=status, **kw)

    def test_dashboard_requires_staff_login(self):
        # Anonymous → redirected to login.
        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

        # Authenticated but non-staff → still bounced.
        User = get_user_model()
        User.objects.create_user(username="plain", password="pw12345")
        self.client.login(username="plain", password="pw12345")
        self.assertEqual(self.client.get(self.dashboard_url).status_code, 302)

    def test_dashboard_shows_status_counts(self):
        self._venue("A", "a", Venue.VerificationStatus.PENDING)
        self._venue("B", "b", Venue.VerificationStatus.VERIFIED)
        self._venue("C", "c", Venue.VerificationStatus.REJECTED)
        self._venue("D", "d", Venue.VerificationStatus.VERIFIED)
        self.client.login(username="staffer", password="pw12345")
        resp = self.client.get(self.dashboard_url + "?status=all")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["stats"]["pending"], 1)
        self.assertEqual(resp.context["stats"]["verified"], 2)
        self.assertEqual(resp.context["stats"]["rejected"], 1)
        self.assertEqual(resp.context["stats"]["total"], 4)

    def test_queue_filters_by_status(self):
        self._venue("Pending One", "p1", Venue.VerificationStatus.PENDING)
        self._venue("Verified One", "v1", Venue.VerificationStatus.VERIFIED)
        self.client.login(username="staffer", password="pw12345")
        resp = self.client.get(self.dashboard_url + "?status=pending")
        names = [v.name for v in resp.context["venues"]]
        self.assertEqual(names, ["Pending One"])

    def test_set_status_updates_and_returns_partial(self):
        venue = self._venue("Target", "target", Venue.VerificationStatus.PENDING)
        self.client.login(username="staffer", password="pw12345")
        url = reverse("events:review_set_status", args=[venue.slug])
        resp = self.client.post(url, {"status": Venue.VerificationStatus.VERIFIED})
        self.assertEqual(resp.status_code, 200)
        venue.refresh_from_db()
        self.assertEqual(venue.verification_status, Venue.VerificationStatus.VERIFIED)
        self.assertContains(resp, "badge-verified")

    def test_set_status_rejects_invalid_value(self):
        venue = self._venue("Target", "target", Venue.VerificationStatus.PENDING)
        self.client.login(username="staffer", password="pw12345")
        url = reverse("events:review_set_status", args=[venue.slug])
        resp = self.client.post(url, {"status": "bogus"})
        self.assertEqual(resp.status_code, 400)
        venue.refresh_from_db()
        self.assertEqual(venue.verification_status, Venue.VerificationStatus.PENDING)

    def test_set_status_requires_post(self):
        venue = self._venue("Target", "target")
        self.client.login(username="staffer", password="pw12345")
        url = reverse("events:review_set_status", args=[venue.slug])
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_set_status_requires_staff(self):
        venue = self._venue("Target", "target", Venue.VerificationStatus.PENDING)
        url = reverse("events:review_set_status", args=[venue.slug])
        resp = self.client.post(url, {"status": Venue.VerificationStatus.VERIFIED})
        self.assertEqual(resp.status_code, 302)  # bounced to login
        venue.refresh_from_db()
        self.assertEqual(venue.verification_status, Venue.VerificationStatus.PENDING)
