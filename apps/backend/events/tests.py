import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from datetime import timedelta

from django.utils import timezone

from django.core.management import call_command

from events import runner
from events import ai_categories
from events.categories import normalize_category
from events.models import Event, Organizer, ScraperRun, Venue
from events.runner import cancel_run, trigger_scraper_run
from events.scrapers.base import ScrapedVenue, save_venues
from events.scrapers.places import GooglePlacesVenueScraper


def _fake_cli(stdout):
    """Return a mock subprocess.run result with the given stdout."""
    completed = mock.Mock()
    completed.stdout = stdout
    completed.returncode = 0
    return completed


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


class ScraperRunModelTests(TestCase):
    def test_str_representation(self):
        run = ScraperRun.objects.create(scraper_key="myruntime")
        s = str(run)
        self.assertIn("myruntime", s)
        self.assertIn("queued", s)

    def test_default_status_is_queued(self):
        run = ScraperRun.objects.create(scraper_key="myruntime")
        self.assertEqual(run.status, ScraperRun.Status.QUEUED)

    def test_duration_seconds_none_when_no_started_at(self):
        run = ScraperRun.objects.create(scraper_key="myruntime")
        self.assertIsNone(run.duration_seconds)

    def test_duration_seconds_computed_when_both_set(self):
        start = timezone.now()
        run = ScraperRun.objects.create(
            scraper_key="myruntime",
            started_at=start,
            finished_at=start + timedelta(seconds=5),
        )
        self.assertAlmostEqual(run.duration_seconds, 5.0, places=2)

    def test_is_active_true_for_queued_and_running(self):
        run = ScraperRun.objects.create(scraper_key="myruntime")
        self.assertTrue(run.is_active)
        run.status = ScraperRun.Status.RUNNING
        self.assertTrue(run.is_active)

    def test_is_active_false_for_success_and_failed(self):
        run = ScraperRun.objects.create(scraper_key="myruntime")
        run.status = ScraperRun.Status.SUCCESS
        self.assertFalse(run.is_active)
        run.status = ScraperRun.Status.FAILED
        self.assertFalse(run.is_active)


class ScraperRunCancelledStatusTests(TestCase):
    """Model-level coverage for the new CANCELLED status and pid field."""

    def test_cancelled_is_valid_status(self):
        run = ScraperRun.objects.create(scraper_key="myruntime")
        run.status = ScraperRun.Status.CANCELLED
        run.save(update_fields=["status", "updated_at"])
        run.refresh_from_db()
        self.assertEqual(run.status, "cancelled")

    def test_is_active_false_for_cancelled(self):
        run = ScraperRun(scraper_key="myruntime", status=ScraperRun.Status.CANCELLED)
        self.assertFalse(run.is_active)

    def test_pid_field_defaults_to_null(self):
        run = ScraperRun.objects.create(scraper_key="myruntime")
        self.assertIsNone(run.pid)


class RunnerSubprocessTests(TransactionTestCase):
    """Subprocess-based trigger + cancel behaviour.

    TransactionTestCase (not TestCase): cancel_run uses select_for_update inside
    a transaction.atomic() block, which is incompatible with TestCase's
    test-wrapping transaction on Postgres. All trigger tests mock
    subprocess.Popen so no real worker process is ever spawned.
    """

    def test_trigger_creates_run_row_subprocess(self):
        with mock.patch("events.runner.subprocess.Popen") as mock_popen:
            mock_popen.return_value.pid = 12345
            trigger_scraper_run("myruntime")
        self.assertEqual(ScraperRun.objects.count(), 1)

    def test_trigger_stores_pid(self):
        with mock.patch("events.runner.subprocess.Popen") as mock_popen:
            mock_popen.return_value.pid = 12345
            run, _ = trigger_scraper_run("myruntime")
        run.refresh_from_db()
        self.assertEqual(run.pid, 12345)

    def test_trigger_returns_run_and_false_when_clear(self):
        with mock.patch("events.runner.subprocess.Popen") as mock_popen:
            mock_popen.return_value.pid = 12345
            run, already_active = trigger_scraper_run("myruntime")
        self.assertIsNotNone(run)
        self.assertFalse(already_active)

    def test_trigger_returns_none_true_when_already_active(self):
        ScraperRun.objects.create(
            scraper_key="myruntime", status=ScraperRun.Status.RUNNING
        )
        with mock.patch("events.runner.subprocess.Popen") as mock_popen:
            run, already_active = trigger_scraper_run("myruntime")
        self.assertIsNone(run)
        self.assertTrue(already_active)
        # No subprocess should be spawned when a run is already active.
        mock_popen.assert_not_called()

    @mock.patch("events.runner.os.getpgid", return_value=99999)
    @mock.patch("events.runner.os.killpg")
    def test_cancel_run_happy_path(self, mock_killpg, mock_getpgid):
        run = ScraperRun.objects.create(
            scraper_key="myruntime", status=ScraperRun.Status.RUNNING, pid=99999
        )
        result_run, signal = cancel_run(run.id)
        self.assertEqual(signal, "ok")
        self.assertEqual(result_run.status, ScraperRun.Status.CANCELLED)
        self.assertIsNotNone(result_run.finished_at)
        mock_killpg.assert_called_once()

    def test_cancel_run_not_found(self):
        run, signal = cancel_run(99999)
        self.assertIsNone(run)
        self.assertEqual(signal, "not_found")

    def test_cancel_run_not_active(self):
        run = ScraperRun.objects.create(
            scraper_key="myruntime", status=ScraperRun.Status.SUCCESS
        )
        result_run, signal = cancel_run(run.id)
        self.assertEqual(signal, "not_active")
        self.assertEqual(result_run.id, run.id)

    @mock.patch("events.runner.os.getpgid", return_value=99999)
    @mock.patch("events.runner.os.killpg", side_effect=ProcessLookupError)
    def test_cancel_run_process_already_gone(self, mock_killpg, mock_getpgid):
        run = ScraperRun.objects.create(
            scraper_key="myruntime", status=ScraperRun.Status.RUNNING, pid=99999
        )
        result_run, signal = cancel_run(run.id)
        # Process is gone but the row is still active → still mark it cancelled.
        self.assertEqual(signal, "ok")
        self.assertEqual(result_run.status, ScraperRun.Status.CANCELLED)

    @mock.patch("events.runner.os.getpgid", return_value=99999)
    @mock.patch("events.runner.os.killpg")
    def test_cancel_run_race_subprocess_wrote_success(self, mock_killpg, mock_getpgid):
        run = ScraperRun.objects.create(
            scraper_key="myruntime", status=ScraperRun.Status.RUNNING, pid=99999
        )

        # Simulate the worker winning the race: refresh_from_db flips the row to
        # SUCCESS, so cancel_run must NOT overwrite it with CANCELLED.
        original_refresh = ScraperRun.refresh_from_db

        def fake_refresh(self, *args, **kwargs):
            original_refresh(self, *args, **kwargs)
            self.status = ScraperRun.Status.SUCCESS

        with mock.patch.object(ScraperRun, "refresh_from_db", fake_refresh):
            result_run, signal = cancel_run(run.id)

        self.assertEqual(signal, "ok")
        self.assertEqual(result_run.status, ScraperRun.Status.SUCCESS)


class ScraperJobCommandTests(TestCase):
    """Covers the run_scraper_job management command (the subprocess worker)."""

    def test_run_scraper_job_happy_path(self):
        run = ScraperRun.objects.create(scraper_key="myruntime")
        fake_cls = mock.Mock()
        fake_cls.return_value.run.return_value = {
            "source": "myruntime", "created": 3, "updated": 1,
        }
        with mock.patch.dict(runner.SCRAPERS, {"myruntime": fake_cls}):
            call_command("run_scraper_job", run_id=run.id)
        run.refresh_from_db()
        self.assertEqual(run.status, ScraperRun.Status.SUCCESS)
        self.assertEqual(run.created_count, 3)
        self.assertEqual(run.updated_count, 1)
        self.assertIsNotNone(run.finished_at)

    def test_run_scraper_job_failure_path(self):
        run = ScraperRun.objects.create(scraper_key="myruntime")
        fake_cls = mock.Mock()
        fake_cls.return_value.run.side_effect = RuntimeError("boom")
        with mock.patch.dict(runner.SCRAPERS, {"myruntime": fake_cls}):
            call_command("run_scraper_job", run_id=run.id)
        run.refresh_from_db()
        self.assertEqual(run.status, ScraperRun.Status.FAILED)
        self.assertIn("RuntimeError", run.error_message)
        self.assertIsNotNone(run.finished_at)

    def test_run_scraper_job_extra_counts(self):
        run = ScraperRun.objects.create(scraper_key="myruntime")
        fake_cls = mock.Mock()
        fake_cls.return_value.run.return_value = {
            "source": "myruntime", "created": 2, "updated": 0,
            "organizers_created": 5, "organizers_updated": 1,
        }
        with mock.patch.dict(runner.SCRAPERS, {"myruntime": fake_cls}):
            call_command("run_scraper_job", run_id=run.id)
        run.refresh_from_db()
        self.assertEqual(
            run.extra_counts,
            {"organizers_created": 5, "organizers_updated": 1},
        )


class RunnerMappingTests(TestCase):
    """Covers the _map_result helper in runner.py."""

    def test_map_result_basic(self):
        created, updated, extra = runner._map_result(
            {"source": "x", "created": 3, "updated": 1}
        )
        self.assertEqual((created, updated, extra), (3, 1, {}))

    def test_map_result_extra_counts(self):
        created, updated, extra = runner._map_result(
            {
                "source": "myruntime", "created": 2, "updated": 0,
                "organizers_created": 5, "organizers_updated": 1,
            }
        )
        self.assertEqual((created, updated), (2, 0))
        self.assertEqual(extra, {"organizers_created": 5, "organizers_updated": 1})
        self.assertNotIn("source", extra)


class CancelEndpointTests(TestCase):
    """HTTP-level coverage for POST /api/scrapers/runs/<id>/cancel/."""

    def _finished_run(self):
        return ScraperRun.objects.create(
            scraper_key="myruntime", status=ScraperRun.Status.CANCELLED
        )

    @mock.patch("events.views.cancel_run")
    def test_cancel_happy_path_returns_200(self, mock_cancel):
        run = ScraperRun.objects.create(
            scraper_key="myruntime", status=ScraperRun.Status.CANCELLED
        )
        mock_cancel.return_value = (run, "ok")
        resp = self.client.post(f"/api/scrapers/runs/{run.id}/cancel/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("status", resp.json())

    @mock.patch("events.views.cancel_run")
    def test_cancel_not_found_returns_404(self, mock_cancel):
        mock_cancel.return_value = (None, "not_found")
        resp = self.client.post("/api/scrapers/runs/123/cancel/")
        self.assertEqual(resp.status_code, 404)

    @mock.patch("events.views.cancel_run")
    def test_cancel_not_active_returns_409(self, mock_cancel):
        run = self._finished_run()
        mock_cancel.return_value = (run, "not_active")
        resp = self.client.post(f"/api/scrapers/runs/{run.id}/cancel/")
        self.assertEqual(resp.status_code, 409)

    def test_cancel_requires_post(self):
        resp = self.client.get("/api/scrapers/runs/1/cancel/")
        self.assertEqual(resp.status_code, 405)

    @mock.patch("events.views.cancel_run")
    def test_cancel_is_public(self, mock_cancel):
        run = ScraperRun.objects.create(
            scraper_key="myruntime", status=ScraperRun.Status.CANCELLED
        )
        mock_cancel.return_value = (run, "ok")
        resp = self.client.post(f"/api/scrapers/runs/{run.id}/cancel/")
        self.assertEqual(resp.status_code, 200)


class RunEndpointTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(
            "staff", password="pw", is_staff=True
        )
        self.nonstaff = User.objects.create_user("plain", password="pw")
        self.client.force_login(self.staff)

    def test_trigger_returns_200_and_run_id(self):
        mock_run = mock.Mock(id=42, status="queued")
        with mock.patch(
            "events.views.trigger_scraper_run", return_value=(mock_run, False)
        ):
            resp = self.client.post("/api/scrapers/myruntime/run/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["id"], 42)
        self.assertEqual(body["status"], "queued")

    def test_trigger_returns_404_unknown_key(self):
        resp = self.client.post("/api/scrapers/badkey/run/")
        self.assertEqual(resp.status_code, 404)

    def test_trigger_returns_409_when_already_active(self):
        with mock.patch(
            "events.views.trigger_scraper_run", return_value=(None, True)
        ):
            resp = self.client.post("/api/scrapers/myruntime/run/")
        self.assertEqual(resp.status_code, 409)

    def test_trigger_is_public_for_any_user(self):
        # The trigger endpoint is unauthenticated — the SvelteKit frontend has
        # no Django session. Non-staff users (and anonymous) can trigger runs.
        self.client.force_login(self.nonstaff)
        mock_run = mock.Mock(id=99, status="queued")
        with mock.patch(
            "events.views.trigger_scraper_run", return_value=(mock_run, False)
        ):
            resp = self.client.post("/api/scrapers/myruntime/run/")
        self.assertEqual(resp.status_code, 200)

    def test_trigger_requires_post(self):
        resp = self.client.get("/api/scrapers/myruntime/run/")
        self.assertEqual(resp.status_code, 405)

    def test_runs_list_returns_recent_runs(self):
        # Use distinct statuses so only one row is "active" per key,
        # respecting the unique_active_scraper_run DB constraint.
        ScraperRun.objects.create(scraper_key="myruntime", status=ScraperRun.Status.QUEUED)
        ScraperRun.objects.create(scraper_key="myruntime", status=ScraperRun.Status.SUCCESS)
        ScraperRun.objects.create(scraper_key="racemeister_partners", status=ScraperRun.Status.FAILED)
        resp = self.client.get("/api/scrapers/runs/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 3)

    def test_active_runs_returns_only_active(self):
        ScraperRun.objects.create(
            scraper_key="myruntime", status=ScraperRun.Status.QUEUED
        )
        ScraperRun.objects.create(
            scraper_key="racemeister_partners", status=ScraperRun.Status.SUCCESS
        )
        resp = self.client.get("/api/scrapers/runs/active/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

    def test_run_detail_returns_correct_run(self):
        run = ScraperRun.objects.create(scraper_key="myruntime")
        resp = self.client.get(f"/api/scrapers/runs/{run.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], run.id)

    def test_run_detail_404_for_missing(self):
        resp = self.client.get("/api/scrapers/runs/99999/")
        self.assertEqual(resp.status_code, 404)

    def test_run_list_endpoints_are_public(self):
        # GET read endpoints are unauthenticated — the SvelteKit client has no
        # session cookie, mirroring the existing /api/scrapers/ convention.
        self.client.logout()
        for url in (
            "/api/scrapers/runs/",
            "/api/scrapers/runs/active/",
        ):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)

    def test_run_detail_endpoint_is_public(self):
        run = ScraperRun.objects.create(scraper_key="myruntime")
        self.client.logout()
        resp = self.client.get(f"/api/scrapers/runs/{run.id}/")
        self.assertEqual(resp.status_code, 200)

    def test_trigger_is_public_for_anonymous(self):
        # Anonymous users can trigger runs — the endpoint is intentionally
        # unauthenticated (internal-only admin tool; no real session bridge).
        self.client.logout()
        mock_run = mock.Mock(id=77, status="queued")
        with mock.patch(
            "events.views.trigger_scraper_run", return_value=(mock_run, False)
        ):
            resp = self.client.post("/api/scrapers/myruntime/run/")
        self.assertEqual(resp.status_code, 200)

    def test_run_all_triggers_all_scrapers(self):
        from events.scrapers import SCRAPERS as REAL_SCRAPERS

        mock_run = mock.Mock(id=1, status="queued")
        with mock.patch(
            "events.views.trigger_scraper_run", return_value=(mock_run, False)
        ) as mock_trigger:
            resp = self.client.post("/api/scrapers/run-all/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body["created"]), len(REAL_SCRAPERS))
        self.assertEqual(body["skipped"], [])
        self.assertEqual(mock_trigger.call_count, len(REAL_SCRAPERS))

    def test_run_all_skips_active_scrapers(self):
        # Restrict SCRAPERS to 2 keys so side_effect list matches exactly.
        from events import scrapers as scrapers_module
        fake_scrapers = {"key_a": mock.Mock(), "key_b": mock.Mock()}
        results = [(None, True), (mock.Mock(id=2, status="queued"), False)]
        with mock.patch.dict(scrapers_module.SCRAPERS, fake_scrapers, clear=True), \
             mock.patch("events.views.trigger_scraper_run", side_effect=results):
            resp = self.client.post("/api/scrapers/run-all/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body["created"]), 1)
        self.assertEqual(len(body["skipped"]), 1)

    def test_run_all_is_public(self):
        self.client.logout()
        mock_run = mock.Mock(id=3, status="queued")
        with mock.patch(
            "events.views.trigger_scraper_run", return_value=(mock_run, False)
        ):
            resp = self.client.post("/api/scrapers/run-all/")
        self.assertEqual(resp.status_code, 200)


class ApiScrapersLastRunTests(TestCase):
    """GET /api/scrapers/ must annotate each scraper with its latest ScraperRun."""

    def _payload_for(self, key):
        resp = self.client.get("/api/scrapers/")
        self.assertEqual(resp.status_code, 200)
        for row in resp.json():
            if row["key"] == key:
                return row
        self.fail(f"scraper key {key!r} not in /api/scrapers/ payload")

    def test_last_run_null_when_no_runs(self):
        # A registered scraper with no ScraperRun history reports last_run=None.
        row = self._payload_for("myruntime")
        self.assertIn("last_run", row)
        self.assertIsNone(row["last_run"])

    def test_last_run_reflects_latest_run(self):
        started = timezone.now() - timedelta(minutes=5)
        finished = timezone.now()
        ScraperRun.objects.create(
            scraper_key="myruntime",
            status=ScraperRun.Status.SUCCESS,
            started_at=started,
            finished_at=finished,
        )
        row = self._payload_for("myruntime")
        self.assertIsNotNone(row["last_run"])
        self.assertEqual(row["last_run"]["status"], ScraperRun.Status.SUCCESS)
        self.assertEqual(row["last_run"]["started_at"], started.isoformat())
        self.assertEqual(row["last_run"]["finished_at"], finished.isoformat())

    def test_last_run_picks_most_recent_per_key(self):
        # Older run first, then a newer one — the newer (latest) must win.
        ScraperRun.objects.create(
            scraper_key="myruntime",
            status=ScraperRun.Status.FAILED,
            started_at=timezone.now() - timedelta(hours=2),
            finished_at=timezone.now() - timedelta(hours=2),
        )
        latest = ScraperRun.objects.create(
            scraper_key="myruntime", status=ScraperRun.Status.RUNNING
        )
        row = self._payload_for("myruntime")
        self.assertEqual(row["last_run"]["status"], latest.status)

    def test_last_run_is_per_scraper_key(self):
        # A run for one key must not leak into another key's last_run.
        ScraperRun.objects.create(
            scraper_key="myruntime", status=ScraperRun.Status.SUCCESS
        )
        myruntime_row = self._payload_for("myruntime")
        racemeister_row = self._payload_for("racemeister_partners")
        self.assertIsNotNone(myruntime_row["last_run"])
        self.assertIsNone(racemeister_row["last_run"])


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


class AiCategoriesTests(TestCase):
    """Unit tests for the AI categorization service.

    All tests mock subprocess.run so no actual CLI is invoked.
    """

    def _make_event(self, name, category="", description=""):
        return Event.objects.create(
            name=name,
            slug=name.lower().replace(" ", "-"),
            category=category,
            description=description,
            source="test",
        )

    def test_batch_categorize_parses_valid_response(self):
        e1 = self._make_event("CDO Fun Run 5K", category="5K, 10K")
        e2 = self._make_event("Tech Summit 2026", category="")
        payload = json.dumps({
            str(e1.pk): ["Fun Run / Road Race"],
            str(e2.pk): ["Conference / Seminar"],
        })
        with mock.patch.object(
            ai_categories.subprocess, "run", return_value=_fake_cli(payload)
        ) as run:
            result = ai_categories.batch_categorize([e1, e2], cli_cmd="fake-claude")

        self.assertEqual(result[e1.pk], ["Fun Run / Road Race"])
        self.assertEqual(result[e2.pk], ["Conference / Seminar"])
        # The injected fake command was used.
        self.assertEqual(run.call_args.args[0][0], "fake-claude")

    def test_invalid_labels_fall_back_to_other(self):
        e1 = self._make_event("Mystery Event")
        payload = json.dumps({str(e1.pk): ["Not A Real Category"]})
        with mock.patch.object(
            ai_categories.subprocess, "run", return_value=_fake_cli(payload)
        ):
            result = ai_categories.batch_categorize([e1], cli_cmd="fake-claude")
        self.assertEqual(result[e1.pk], ["Other"])

    def test_missing_event_in_response_falls_back_to_other(self):
        e1 = self._make_event("Ghost Event")
        with mock.patch.object(
            ai_categories.subprocess, "run", return_value=_fake_cli("{}")
        ):
            result = ai_categories.batch_categorize([e1], cli_cmd="fake-claude")
        self.assertEqual(result[e1.pk], ["Other"])

    def test_malformed_json_falls_back_to_other(self):
        e1 = self._make_event("Garbled Event")
        with mock.patch.object(
            ai_categories.subprocess, "run", return_value=_fake_cli("not json at all")
        ):
            result = ai_categories.batch_categorize([e1], cli_cmd="fake-claude")
        self.assertEqual(result[e1.pk], ["Other"])

    def test_missing_cli_raises_helpful_error(self):
        e1 = self._make_event("Any Event")
        with mock.patch.object(
            ai_categories.subprocess, "run", side_effect=FileNotFoundError()
        ):
            with self.assertRaises(FileNotFoundError) as ctx:
                ai_categories.batch_categorize([e1], cli_cmd="missing-claude")
        self.assertIn("CLAUDE_CLI_CMD", str(ctx.exception))
        self.assertIn("missing-claude", str(ctx.exception))

    def test_categorize_events_by_ids_persists_labels(self):
        e1 = self._make_event("CDO Marathon", category="42K")
        e2 = self._make_event("Jazz Night")
        payload = json.dumps({
            str(e1.pk): ["Fun Run / Road Race"],
            str(e2.pk): ["Music & Concert"],
        })
        with mock.patch.object(
            ai_categories.subprocess, "run", return_value=_fake_cli(payload)
        ):
            count = ai_categories.categorize_events_by_ids([e1.pk, e2.pk])

        self.assertEqual(count, 2)
        e1.refresh_from_db()
        e2.refresh_from_db()
        self.assertEqual(e1.agent_categories, ["Fun Run / Road Race"])
        self.assertEqual(e2.agent_categories, ["Music & Concert"])

    def test_categorize_events_by_ids_empty_input(self):
        self.assertEqual(ai_categories.categorize_events_by_ids([]), 0)

    def test_batch_categorize_empty_input_no_subprocess(self):
        with mock.patch.object(ai_categories.subprocess, "run") as run:
            result = ai_categories.batch_categorize([], cli_cmd="fake-claude")
        self.assertEqual(result, {})
        run.assert_not_called()


class OrganizerExportTests(TestCase):
    def test_export_all(self):
        Organizer.objects.create(
            name="Alpha Events",
            slug="alpha-events",
            status=Organizer.STATUS_CONFIRMED,
        )
        Organizer.objects.create(
            name="Beta Productions",
            slug="beta-productions",
            status=Organizer.STATUS_PENDING,
        )

        response = self.client.get("/api/organizers/export/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("organizers.csv", response["Content-Disposition"])
        content = response.content.decode()
        self.assertIn("Alpha Events", content)
        self.assertIn("Beta Productions", content)

    def test_export_filtered_by_status(self):
        Organizer.objects.create(
            name="Confirmed Org",
            slug="confirmed-org",
            status=Organizer.STATUS_CONFIRMED,
        )
        Organizer.objects.create(
            name="Pending Org",
            slug="pending-org",
            status=Organizer.STATUS_PENDING,
        )

        response = self.client.get("/api/organizers/export/?status=confirmed")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Confirmed Org", content)
        self.assertNotIn("Pending Org", content)
