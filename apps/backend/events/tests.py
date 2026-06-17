from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from events.categories import normalize_category
from events.models import Event, Organizer, Venue
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


class ResolveOrganizerTests(TestCase):
    """Covers the FK resolution helper and the display-name property."""

    def _org(self, name, slug, website="", source="src"):
        from events.models import Organizer

        return Organizer.objects.create(
            name=name, slug=slug, website=website, source=source,
        )

    def test_resolves_by_url_with_normalization(self):
        from events.scrapers.base import _resolve_organizer

        org = self._org("Acme", "acme", website="https://Acme.Example.com/")
        # Different casing + trailing slash should still match.
        resolved = _resolve_organizer("http://acme.example.com", "")
        # Scheme differs (http vs https) → normalization keeps scheme, so this
        # should NOT match; the exact-host https URL should.
        self.assertIsNone(resolved)
        resolved2 = _resolve_organizer("https://acme.example.com/", "Unrelated")
        self.assertEqual(resolved2, org)

    def test_resolves_by_unambiguous_name(self):
        from events.scrapers.base import _resolve_organizer

        org = self._org("Unique Org", "unique-org")
        resolved = _resolve_organizer("", "unique org")  # case-insensitive
        self.assertEqual(resolved, org)

    def test_ambiguous_name_returns_none(self):
        from events.scrapers.base import _resolve_organizer

        self._org("Dup Org", "dup-org-1", source="a")
        self._org("Dup Org", "dup-org-2", source="b")
        resolved = _resolve_organizer("", "Dup Org")
        self.assertIsNone(resolved)

    def test_no_match_returns_none(self):
        from events.scrapers.base import _resolve_organizer

        self.assertIsNone(_resolve_organizer("", ""))
        self.assertIsNone(_resolve_organizer("https://nobody.example", "Nobody"))

    def test_save_events_links_organizer_ref(self):
        from events.models import Event
        from events.scrapers.base import ScrapedEvent, save_events

        org = self._org("Linkable", "linkable", website="https://linkable.example")
        save_events("link_src", [ScrapedEvent(
            name="Linked Event",
            organizer_url="https://linkable.example/",
            organizer="Linkable",
        )])
        ev = Event.objects.get(source="link_src")
        self.assertEqual(ev.organizer_ref, org)

    def test_save_events_never_creates_organizer(self):
        from events.models import Event, Organizer
        from events.scrapers.base import ScrapedEvent, save_events

        before = Organizer.objects.count()
        save_events("nolink_src", [ScrapedEvent(
            name="Orphan Event",
            organizer_url="https://unknown.example",
            organizer="Unknown Org",
        )])
        self.assertEqual(Organizer.objects.count(), before)
        ev = Event.objects.get(source="nolink_src")
        self.assertIsNone(ev.organizer_ref)

    def test_organizer_display_name_prefers_fk(self):
        from events.models import Event

        org = self._org("Real Org", "real-org")
        ev = Event.objects.create(
            name="Display Event", slug="display-event",
            organizer="Raw Name", organizer_ref=org,
        )
        self.assertEqual(ev.organizer_display_name, "Real Org")

    def test_organizer_display_name_falls_back_to_charfield(self):
        from events.models import Event

        ev = Event.objects.create(
            name="Fallback Event", slug="fallback-event",
            organizer="Raw Name Only",
        )
        self.assertEqual(ev.organizer_display_name, "Raw Name Only")


class OrganizerPublicViewTests(TestCase):
    def _organizer(self, name, slug, status, **kwargs):
        return Organizer.objects.create(name=name, slug=slug, status=status, **kwargs)

    def test_organizer_list_shows_all_but_rejected(self):
        self._organizer("Confirmed Org", "confirmed-org", Organizer.STATUS_CONFIRMED)
        self._organizer("Pending Org", "pending-org", Organizer.STATUS_PENDING)
        self._organizer("Rejected Org", "rejected-org", Organizer.STATUS_REJECTED)

        resp = self.client.get(reverse("events:organizer_list"))
        self.assertEqual(resp.status_code, 200)
        names = {o.name for o in resp.context["organizers"]}
        self.assertEqual(names, {"Confirmed Org", "Pending Org"})
        self.assertContains(resp, "Confirmed Org")
        self.assertContains(resp, "Pending Org")
        self.assertNotContains(resp, "Rejected Org")

    def test_organizer_list_search_filters_by_name_and_city(self):
        self._organizer(
            "Alpha Events", "alpha-events", Organizer.STATUS_CONFIRMED, city="Manila"
        )
        self._organizer(
            "Beta Group", "beta-group", Organizer.STATUS_CONFIRMED, city="Cebu"
        )

        by_name = self.client.get(reverse("events:organizer_list"), {"q": "Alpha"})
        self.assertEqual(
            [o.name for o in by_name.context["organizers"]], ["Alpha Events"]
        )

        by_city = self.client.get(reverse("events:organizer_list"), {"q": "cebu"})
        self.assertEqual(
            [o.name for o in by_city.context["organizers"]], ["Beta Group"]
        )

    def test_organizer_detail_returns_200_for_confirmed(self):
        org = self._organizer(
            "Contactable Org",
            "contactable-org",
            Organizer.STATUS_CONFIRMED,
            email="hello@example.com",
            phone="+63 900 000 0000",
        )
        resp = self.client.get(org.get_absolute_url())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Contactable Org")
        self.assertContains(resp, "hello@example.com")
        self.assertContains(resp, "+63 900 000 0000")

    def test_organizer_detail_lists_linked_events(self):
        # Events are tied to an organizer via the organizer_ref FK, not the
        # free-text organizer string.
        org = self._organizer("Race Co", "race-co", Organizer.STATUS_CONFIRMED)
        Event.objects.create(name="Marathon 2026", slug="marathon-2026", organizer_ref=org)
        Event.objects.create(name="Unrelated Gig", slug="unrelated-gig")

        resp = self.client.get(org.get_absolute_url())
        self.assertEqual(resp.status_code, 200)
        event_names = {e.name for e in resp.context["events"]}
        self.assertEqual(event_names, {"Marathon 2026"})
        self.assertContains(resp, "Marathon 2026")
        self.assertNotContains(resp, "Unrelated Gig")

    def test_organizer_detail_visible_for_pending_but_404_for_rejected_and_missing(self):
        pending = self._organizer("Pending Org", "pending-org", Organizer.STATUS_PENDING)
        rejected = self._organizer("Rejected Org", "rejected-org", Organizer.STATUS_REJECTED)

        self.assertEqual(self.client.get(pending.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(rejected.get_absolute_url()).status_code, 404)
        self.assertEqual(
            self.client.get(
                reverse("events:organizer_detail", args=["does-not-exist"])
            ).status_code,
            404,
        )

    def test_organizer_get_absolute_url(self):
        self.assertEqual(
            Organizer(slug="acme").get_absolute_url(), "/organizers/acme/"
        )

    def test_event_detail_links_to_public_organizer(self):
        org = self._organizer("Race Co", "race-co", Organizer.STATUS_CONFIRMED)
        ev = Event.objects.create(name="City Run", slug="city-run", organizer_ref=org)

        resp = self.client.get(ev.get_absolute_url())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, org.get_absolute_url())
        self.assertContains(resp, "Race Co")

    def test_event_detail_does_not_link_to_rejected_organizer(self):
        org = self._organizer("Hidden Co", "hidden-co", Organizer.STATUS_REJECTED)
        ev = Event.objects.create(
            name="Secret Run", slug="secret-run",
            organizer="Hidden Co", organizer_ref=org,
        )

        resp = self.client.get(ev.get_absolute_url())
        self.assertEqual(resp.status_code, 200)
        # No link to the rejected organizer's detail page (it would 404)...
        self.assertNotContains(resp, org.get_absolute_url())
        # ...but the free-text fallback name is still displayed.
        self.assertContains(resp, "Hidden Co")


class CategoryNormalizationTests(TestCase):
    def test_distance_list_maps_to_fun_run(self):
        self.assertEqual(normalize_category("10K, 5K, 3K"), "Fun Run / Road Race")

    def test_distance_list_km_suffix_maps_to_fun_run(self):
        self.assertEqual(normalize_category("21KM, 10KM, 5KM"), "Fun Run / Road Race")

    def test_single_distance_maps_to_fun_run(self):
        self.assertEqual(normalize_category("42K"), "Fun Run / Road Race")

    def test_wave_tier_names_map_to_fun_run(self):
        self.assertEqual(
            normalize_category("SUB1 Elite, SUB1 Competitor, Open Wave"),
            "Fun Run / Road Race",
        )

    def test_trail_keyword(self):
        self.assertEqual(normalize_category("trail run"), "Trail Run")

    def test_music_keyword(self):
        self.assertEqual(normalize_category("music"), "Music")

    def test_festival_keyword(self):
        self.assertEqual(normalize_category("festival"), "Festival")

    def test_workshop_keyword(self):
        self.assertEqual(normalize_category("Photography Workshop"), "Workshop / Training")

    def test_conference_keyword(self):
        self.assertEqual(normalize_category("Tech Conference"), "Conference / Seminar")

    def test_keyword_matching_is_whole_word_not_substring(self):
        # "art" must not match as a substring inside unrelated words such as
        # "party" or "smartphone" — those should fall back to title case.
        self.assertEqual(normalize_category("party"), "Party")
        self.assertEqual(normalize_category("Smartphone Expo"), "Smartphone Expo")
        # A genuine whole-word "art" still maps to Arts & Culture.
        self.assertEqual(normalize_category("Art Exhibit"), "Arts & Culture")

    def test_unknown_falls_back_to_title_case(self):
        self.assertEqual(
            normalize_category("Weird Unique Event 2026"),
            "Weird Unique Event 2026",
        )

    def test_empty_string_returns_empty(self):
        self.assertEqual(normalize_category(""), "")

    def test_api_top_n_and_other_rollup(self):
        # Distance lists / wave tiers all collapse into one "Fun Run / Road Race"
        # bucket; mapped keywords and clean fallbacks fill out the rest. With
        # more than 8 canonical buckets, the surplus rolls into "Other".
        raw_categories = [
            "10K, 5K, 3K",          # Fun Run / Road Race
            "SUB1 Elite, Open Wave",  # Fun Run / Road Race
            "trail run",             # Trail Run
            "music",                 # Music
            "festival",              # Festival
            "Photography Workshop",  # Workshop / Training
            "Tech Conference",       # Conference / Seminar
            "cycling",               # Cycling
            "swimming",              # Swimming
            "Charity Gala",          # Charity / Fundraiser
            "Alpha Unique",          # Alpha Unique (fallback)
            "Beta Unique",           # Beta Unique (fallback)
        ]
        for idx, cat in enumerate(raw_categories):
            Event.objects.create(
                name=f"Event {idx}",
                slug=f"event-{idx}",
                category=cat,
                source="test",
            )

        resp = self.client.get(reverse("events:api_events_by_category"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)
        # Top 8 + optional "Other" => at most 9 buckets.
        self.assertLessEqual(len(data), 9)
        # More than 8 canonical buckets exist, so "Other" must be present.
        categories = {entry["category"] for entry in data}
        self.assertIn("Other", categories)
        # Every entry has a positive count and the expected shape.
        for entry in data:
            self.assertIn("category", entry)
            self.assertIn("count", entry)
            self.assertGreater(entry["count"], 0)
