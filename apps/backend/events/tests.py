import json
import sys
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from datetime import timedelta

from django.utils import timezone

from django.core.management import call_command

from events import runner
from events import ai_categories
from events.categories import normalize_category
from events.models import Event, Organizer, ScraperRun, SearchQuery, Venue
from events.runner import cancel_run, trigger_scraper_run
from events.scrapers.base import ScrapedVenue, save_venues
from events.scrapers.places import GooglePlacesVenueScraper


def _fake_response(payload):
    resp = mock.Mock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _fake_groq_response(content: str):
    """Return a mock requests.post result shaped like a Groq API response."""
    return _fake_response({
        "choices": [{"message": {"content": content}}]
    })


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


@override_settings(GROQ_API_KEY="test-key", GROQ_CATEGORIZE_MODEL="llama-test")
class AiCategoriesTests(TestCase):
    """Unit tests for the AI categorization service.

    All tests mock requests.post so no actual Groq API call is made.
    GROQ_API_KEY is overridden at class level so the key-check passes in CI.
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
        content = json.dumps({
            str(e1.pk): ["Fun Run / Road Race"],
            str(e2.pk): ["Conference / Seminar"],
        })
        with mock.patch("events.ai_categories.requests.post", return_value=_fake_groq_response(content)):
            result = ai_categories.batch_categorize([e1, e2])

        self.assertEqual(result[e1.pk], ["Fun Run / Road Race"])
        self.assertEqual(result[e2.pk], ["Conference / Seminar"])

    def test_invalid_labels_fall_back_to_other(self):
        e1 = self._make_event("Mystery Event")
        content = json.dumps({str(e1.pk): ["Not A Real Category"]})
        with mock.patch("events.ai_categories.requests.post", return_value=_fake_groq_response(content)):
            result = ai_categories.batch_categorize([e1])
        self.assertEqual(result[e1.pk], ["Other"])

    def test_missing_event_in_response_falls_back_to_other(self):
        e1 = self._make_event("Ghost Event")
        with mock.patch("events.ai_categories.requests.post", return_value=_fake_groq_response("{}")):
            result = ai_categories.batch_categorize([e1])
        self.assertEqual(result[e1.pk], ["Other"])

    def test_malformed_json_falls_back_to_other(self):
        e1 = self._make_event("Garbled Event")
        with mock.patch("events.ai_categories.requests.post", return_value=_fake_groq_response("not json at all")):
            result = ai_categories.batch_categorize([e1])
        self.assertEqual(result[e1.pk], ["Other"])

    def test_missing_api_key_raises_helpful_error(self):
        e1 = self._make_event("Any Event")
        with self.settings(GROQ_API_KEY=""):
            with self.assertRaises(RuntimeError) as ctx:
                ai_categories.batch_categorize([e1])
        self.assertIn("GROQ_API_KEY", str(ctx.exception))

    def test_api_request_failure_raises_runtime_error(self):
        import requests as req_lib
        e1 = self._make_event("Any Event")
        with mock.patch("events.ai_categories.requests.post", side_effect=req_lib.exceptions.RequestException("timeout")):
            with self.assertRaises(RuntimeError) as ctx:
                ai_categories.batch_categorize([e1])
        self.assertIn("Groq API request failed", str(ctx.exception))

    def test_categorize_events_by_ids_persists_labels(self):
        e1 = self._make_event("CDO Marathon", category="42K")
        e2 = self._make_event("Jazz Night")
        content = json.dumps({
            str(e1.pk): ["Fun Run / Road Race"],
            str(e2.pk): ["Music & Concert"],
        })
        with mock.patch("events.ai_categories.requests.post", return_value=_fake_groq_response(content)):
            count = ai_categories.categorize_events_by_ids([e1.pk, e2.pk])

        self.assertEqual(count, 2)
        e1.refresh_from_db()
        e2.refresh_from_db()
        self.assertEqual(e1.agent_categories, ["Fun Run / Road Race"])
        self.assertEqual(e2.agent_categories, ["Music & Concert"])

    def test_categorize_events_by_ids_empty_input(self):
        self.assertEqual(ai_categories.categorize_events_by_ids([]), 0)

    def test_batch_categorize_empty_input_no_api_call(self):
        with mock.patch("events.ai_categories.requests.post") as mock_post:
            result = ai_categories.batch_categorize([])
        self.assertEqual(result, {})
        mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# Deduplication tests
# ---------------------------------------------------------------------------

import pathlib  # noqa: E402

_scripts_dir = pathlib.Path(__file__).resolve().parent.parent / "scripts"
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

import dedup as dedup_utils  # noqa: E402


def _dict_cursor():
    """A RealDictCursor over Django's current (test-transaction) connection.

    ``dedup.py`` expects ``cursor.fetchall()`` to yield mapping rows
    (``row["id"]``), which Django's default cursor does not provide. Sharing the
    underlying psycopg2 connection keeps reads/writes inside the same test
    transaction so they roll back automatically.
    """
    import psycopg2.extras
    from django.db import connection

    connection.ensure_connection()
    return connection.connection.cursor(
        cursor_factory=psycopg2.extras.RealDictCursor
    )


class NormalizationTests(TestCase):
    """Pure normalization helpers from scripts/dedup.py — no DB needed."""

    def test_normalize_name_empty_string(self):
        self.assertEqual(dedup_utils.normalize_name(""), "")

    def test_normalize_name_none(self):
        self.assertEqual(dedup_utils.normalize_name(None), "")

    def test_normalize_name_accents(self):
        self.assertEqual(
            dedup_utils.normalize_name("Café Évènement"), "cafe evenement"
        )

    def test_normalize_name_punctuation(self):
        self.assertEqual(dedup_utils.normalize_name("Hello, World!"), "hello world")

    def test_normalize_name_extra_whitespace(self):
        self.assertEqual(dedup_utils.normalize_name("  foo   bar  "), "foo bar")

    def test_normalize_url_empty(self):
        self.assertEqual(dedup_utils.normalize_url(""), "")
        self.assertEqual(dedup_utils.normalize_url(None), "")

    def test_normalize_url_strips_protocol(self):
        self.assertEqual(
            dedup_utils.normalize_url("https://example.com/"),
            dedup_utils.normalize_url("http://example.com/"),
        )

    def test_normalize_url_strips_trailing_slash(self):
        self.assertEqual(
            dedup_utils.normalize_url("https://example.com/page/"),
            dedup_utils.normalize_url("https://example.com/page"),
        )

    def test_normalize_url_strips_utm_params(self):
        self.assertEqual(
            dedup_utils.normalize_url("https://example.com/?utm_source=fb&id=1"),
            dedup_utils.normalize_url("https://example.com/?id=1"),
        )

    def test_normalize_url_sorts_query_params(self):
        self.assertEqual(
            dedup_utils.normalize_url("https://x.com/?b=2&a=1"),
            dedup_utils.normalize_url("https://x.com/?a=1&b=2"),
        )

    def test_normalize_date_datetime(self):
        dt = timezone.now()
        self.assertEqual(dedup_utils.normalize_date(dt), dt.astimezone(__import__("datetime").timezone.utc).date())

    def test_normalize_date_none(self):
        self.assertIsNone(dedup_utils.normalize_date(None))

    def test_normalize_city_strips_whitespace(self):
        self.assertEqual(dedup_utils.normalize_city("  Cagayan De Oro  "), "cagayan de oro")


class FindDuplicatesTests(TestCase):
    """Duplicate finders run against the test DB via a RealDictCursor."""

    def test_find_venue_duplicates_by_website(self):
        a = Venue.objects.create(name="Venue One", slug="v-one",
                                 website="https://Same.example.com/")
        b = Venue.objects.create(name="Venue Two", slug="v-two",
                                 website="http://same.example.com")
        with _dict_cursor() as cur:
            groups = dedup_utils.find_venue_duplicates(cur)
        flat = {pk for g in groups for pk in g}
        self.assertIn(a.pk, flat)
        self.assertIn(b.pk, flat)
        self.assertEqual(len(groups), 1)

    def test_find_venue_duplicates_by_name_city(self):
        a = Venue.objects.create(name="City Hall", slug="ch-1", city="CDO")
        b = Venue.objects.create(name="city hall", slug="ch-2", city="cdo")
        with _dict_cursor() as cur:
            groups = dedup_utils.find_venue_duplicates(cur)
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]), {a.pk, b.pk})

    def test_find_venue_duplicates_no_duplicates(self):
        Venue.objects.create(name="Alpha", slug="alpha", city="A")
        Venue.objects.create(name="Beta", slug="beta", city="B")
        with _dict_cursor() as cur:
            groups = dedup_utils.find_venue_duplicates(cur)
        self.assertEqual(groups, [])

    def test_find_organizer_duplicates_by_website(self):
        a = Organizer.objects.create(name="Org A", slug="oa",
                                     website="https://org.example/")
        b = Organizer.objects.create(name="Org B", slug="ob",
                                     website="http://org.example")
        with _dict_cursor() as cur:
            groups = dedup_utils.find_organizer_duplicates(cur)
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]), {a.pk, b.pk})

    def test_find_organizer_duplicates_by_name(self):
        a = Organizer.objects.create(name="Repeat Org", slug="ro-1")
        b = Organizer.objects.create(name="repeat org", slug="ro-2")
        with _dict_cursor() as cur:
            groups = dedup_utils.find_organizer_duplicates(cur)
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]), {a.pk, b.pk})

    def test_find_event_duplicates_by_url(self):
        a = Event.objects.create(name="Run A", slug="run-a",
                                 url="https://ev.example/run/")
        b = Event.objects.create(name="Run B", slug="run-b",
                                 url="http://ev.example/run")
        with _dict_cursor() as cur:
            groups = dedup_utils.find_event_duplicates(cur)
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]), {a.pk, b.pk})

    def test_find_event_duplicates_by_name_date_city(self):
        venue = Venue.objects.create(name="Hall", slug="hall", city="CDO")
        when = timezone.now()
        a = Event.objects.create(name="Gala Night", slug="gala-1",
                                 starts_at=when, venue=venue)
        b = Event.objects.create(name="gala night", slug="gala-2",
                                 starts_at=when, venue=venue)
        with _dict_cursor() as cur:
            groups = dedup_utils.find_event_duplicates(cur)
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]), {a.pk, b.pk})

    def test_find_duplicates_winner_is_first(self):
        # Rich row has more non-null fields → should be the winner (first pk).
        rich = Venue.objects.create(
            name="Dup Venue", slug="dup-1", city="CDO",
            address="123 Street", country="PH", website="https://dup.example/",
            about="A rich description.",
        )
        sparse = Venue.objects.create(
            name="dup venue", slug="dup-2", city="cdo",
        )
        with _dict_cursor() as cur:
            groups = dedup_utils.find_venue_duplicates(cur)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][0], rich.pk)
        self.assertIn(sparse.pk, groups[0][1:])


class MergeTests(TestCase):
    """Merge functions run against the test DB via a RealDictCursor."""

    def test_merge_venues_remaps_fk(self):
        winner = Venue.objects.create(name="W", slug="w", city="CDO")
        loser = Venue.objects.create(name="L", slug="l", city="CDO")
        ev = Event.objects.create(name="E", slug="e", venue=loser)
        with _dict_cursor() as cur:
            dedup_utils.merge_venues(cur, winner.pk, [loser.pk])
        ev.refresh_from_db()
        self.assertEqual(ev.venue_id, winner.pk)
        self.assertFalse(Venue.objects.filter(pk=loser.pk).exists())

    def test_merge_organizers_remaps_fk(self):
        winner = Organizer.objects.create(name="W", slug="ow")
        loser = Organizer.objects.create(name="L", slug="ol")
        ev = Event.objects.create(name="E2", slug="e2", organizer_ref=loser)
        with _dict_cursor() as cur:
            dedup_utils.merge_organizers(cur, winner.pk, [loser.pk])
        ev.refresh_from_db()
        self.assertEqual(ev.organizer_ref_id, winner.pk)
        self.assertFalse(Organizer.objects.filter(pk=loser.pk).exists())

    def test_merge_events_hard_deletes_loser(self):
        winner = Event.objects.create(name="W", slug="ew")
        loser = Event.objects.create(name="L", slug="el")
        before = Event.objects.count()
        with _dict_cursor() as cur:
            dedup_utils.merge_events(cur, winner.pk, [loser.pk])
        self.assertEqual(Event.objects.count(), before - 1)
        self.assertFalse(Event.objects.filter(pk=loser.pk).exists())

    def test_merge_fills_missing_fields(self):
        winner = Venue.objects.create(name="W", slug="fw", city="CDO")
        loser = Venue.objects.create(name="L", slug="fl", city="CDO",
                                     about="From loser.")
        with _dict_cursor() as cur:
            dedup_utils.merge_venues(cur, winner.pk, [loser.pk])
        winner.refresh_from_db()
        self.assertEqual(winner.about, "From loser.")

    def test_merge_does_not_overwrite_existing_fields(self):
        winner = Venue.objects.create(name="W", slug="ow2", city="CDO",
                                      about="Winner about.")
        loser = Venue.objects.create(name="L", slug="ol2", city="CDO",
                                     about="Loser about.")
        with _dict_cursor() as cur:
            dedup_utils.merge_venues(cur, winner.pk, [loser.pk])
        winner.refresh_from_db()
        self.assertEqual(winner.about, "Winner about.")

    def test_merge_protected_fields_not_overwritten_venue(self):
        winner = Venue.objects.create(
            name="W", slug="pw", city="CDO",
            verification_status=Venue.VerificationStatus.VERIFIED,
        )
        loser = Venue.objects.create(
            name="L", slug="pl", city="CDO",
            verification_status=Venue.VerificationStatus.REJECTED,
        )
        with _dict_cursor() as cur:
            dedup_utils.merge_venues(cur, winner.pk, [loser.pk])
        winner.refresh_from_db()
        self.assertEqual(
            winner.verification_status, Venue.VerificationStatus.VERIFIED
        )

    def test_merge_protected_fields_not_overwritten_event(self):
        winner = Event.objects.create(name="W", slug="aw",
                                      agent_categories=["Music & Concert"])
        loser = Event.objects.create(name="L", slug="al",
                                     agent_categories=["Sports & Fitness"])
        with _dict_cursor() as cur:
            dedup_utils.merge_events(cur, winner.pk, [loser.pk])
        winner.refresh_from_db()
        self.assertEqual(winner.agent_categories, ["Music & Concert"])

    def test_merge_protected_fields_not_overwritten_organizer(self):
        winner = Organizer.objects.create(name="W", slug="sw",
                                          status=Organizer.STATUS_CONFIRMED)
        loser = Organizer.objects.create(name="L", slug="sl",
                                         status=Organizer.STATUS_PENDING)
        with _dict_cursor() as cur:
            dedup_utils.merge_organizers(cur, winner.pk, [loser.pk])
        winner.refresh_from_db()
        self.assertEqual(winner.status, Organizer.STATUS_CONFIRMED)

    def test_merge_slug_preserved(self):
        winner = Venue.objects.create(name="W", slug="keep-slug", city="CDO")
        loser = Venue.objects.create(name="L", slug="lose-slug", city="CDO")
        with _dict_cursor() as cur:
            dedup_utils.merge_venues(cur, winner.pk, [loser.pk])
        winner.refresh_from_db()
        self.assertEqual(winner.slug, "keep-slug")


class DedupCommandTests(TestCase):
    """Exercises the inline _dedup_after_save hook from scrapers/base.py."""

    def test_dedup_after_save_venues_merges_by_name_city(self):
        from events.scrapers.base import _dedup_after_save

        a = Venue.objects.create(name="Town Hall", slug="th-1", city="CDO")
        b = Venue.objects.create(name="town hall", slug="th-2", city="cdo")
        _dedup_after_save("venues", [a.pk, b.pk])
        self.assertEqual(Venue.objects.filter(pk__in=[a.pk, b.pk]).count(), 1)

    def test_dedup_after_save_venues_keeps_distinct_place_ids(self):
        from events.scrapers.base import _dedup_after_save

        a = Venue.objects.create(name="Mall", slug="m-1", city="CDO",
                                 place_id="pid-a")
        b = Venue.objects.create(name="mall", slug="m-2", city="cdo",
                                 place_id="pid-b")
        _dedup_after_save("venues", [a.pk, b.pk])
        # Distinct stable place_ids must not be merged.
        self.assertEqual(Venue.objects.filter(pk__in=[a.pk, b.pk]).count(), 2)

    def test_dedup_after_save_events_merges_by_url(self):
        from events.scrapers.base import _dedup_after_save

        a = Event.objects.create(name="Run A", slug="dr-a",
                                 url="https://x.example/run/")
        b = Event.objects.create(name="Run B", slug="dr-b",
                                 url="http://x.example/run")
        _dedup_after_save("events", [a.pk, b.pk])
        self.assertEqual(Event.objects.filter(pk__in=[a.pk, b.pk]).count(), 1)

    def test_dedup_after_save_organizers_merges_by_name(self):
        from events.scrapers.base import _dedup_after_save

        a = Organizer.objects.create(name="Same Org", slug="so-1")
        b = Organizer.objects.create(name="same org", slug="so-2")
        _dedup_after_save("organizers", [a.pk, b.pk])
        self.assertEqual(Organizer.objects.filter(pk__in=[a.pk, b.pk]).count(), 1)

    def test_dedup_after_save_empty_ids_noop(self):
        from events.scrapers.base import _dedup_after_save

        # No ids → no error, no DB change.
        before = Venue.objects.count()
        _dedup_after_save("venues", [])
        self.assertEqual(Venue.objects.count(), before)

    def test_dedup_after_save_never_raises(self):
        from events.scrapers.base import _dedup_after_save

        # Unknown entity is silently ignored (no dispatch), never raises.
        _dedup_after_save("nonexistent", [1, 2, 3])
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

class DeduplicateOrganizersCommandTests(TestCase):
    """Tests for the ``deduplicate_organizers`` management command."""

    _counter = 0

    @classmethod
    def _make_organizer(cls, **kwargs):
        """Create and save an Organizer with a unique slug and sane defaults."""
        cls._counter += 1
        defaults = {
            "name": f"Organizer {cls._counter}",
            "slug": f"organizer-{cls._counter}",
            "source": "source_a",
            "status": Organizer.STATUS_PENDING,
        }
        defaults.update(kwargs)
        return Organizer.objects.create(**defaults)

    def _make_event(self, organizer, **kwargs):
        DeduplicateOrganizersCommandTests._counter += 1
        c = DeduplicateOrganizersCommandTests._counter
        defaults = {
            "name": f"Event {c}",
            "slug": f"event-{c}",
            "organizer_ref": organizer,
        }
        defaults.update(kwargs)
        return Event.objects.create(**defaults)

    # -- Normalization ------------------------------------------------------ #

    def test_normalize_url_strips_www_and_trailing_slash(self):
        from events.management.commands.deduplicate_organizers import _normalize_url
        self.assertEqual(
            _normalize_url("https://WWW.Example.com/page/"),
            "https://example.com/page",
        )

    def test_normalize_url_blank_returns_empty(self):
        from events.management.commands.deduplicate_organizers import _normalize_url
        self.assertEqual(_normalize_url(""), "")
        self.assertEqual(_normalize_url(None), "")

    def test_normalize_email_lowercases(self):
        from events.management.commands.deduplicate_organizers import _normalize_email
        self.assertEqual(_normalize_email("  Admin@Example.COM  "), "admin@example.com")

    def test_normalize_phone_strips_country_code(self):
        from events.management.commands.deduplicate_organizers import _normalize_phone
        self.assertEqual(_normalize_phone("+639171234567"), "9171234567")

    def test_normalize_phone_too_short_returns_empty(self):
        from events.management.commands.deduplicate_organizers import _normalize_phone
        self.assertEqual(_normalize_phone("123"), "")

    # -- Cluster detection -------------------------------------------------- #

    def test_exact_website_match_across_sources_detected(self):
        from events.management.commands.deduplicate_organizers import (
            find_exact_match_clusters,
        )
        self._make_organizer(source="eventbrite", website="https://acme.ph")
        self._make_organizer(source="planout", website="https://acme.ph")
        clusters = find_exact_match_clusters(None)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 2)

    def test_same_source_not_clustered(self):
        from events.management.commands.deduplicate_organizers import (
            find_exact_match_clusters,
        )
        self._make_organizer(source="eventbrite", website="https://acme.ph")
        self._make_organizer(source="eventbrite", website="https://acme.ph")
        self.assertEqual(find_exact_match_clusters(None), [])

    def test_email_match_across_sources_detected(self):
        from events.management.commands.deduplicate_organizers import (
            find_exact_match_clusters,
        )
        self._make_organizer(source="eventbrite", email="hi@acme.ph")
        self._make_organizer(source="planout", email="HI@acme.ph")
        clusters = find_exact_match_clusters(None)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 2)

    def test_phone_match_across_sources_detected(self):
        from events.management.commands.deduplicate_organizers import (
            find_exact_match_clusters,
        )
        self._make_organizer(source="eventbrite", phone="+639171234567")
        self._make_organizer(source="planout", phone="09171234567")
        clusters = find_exact_match_clusters(None)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 2)

    def test_blank_field_not_used_as_match_key(self):
        from events.management.commands.deduplicate_organizers import (
            find_exact_match_clusters,
        )
        self._make_organizer(source="eventbrite", website="")
        self._make_organizer(source="planout", website="")
        self.assertEqual(find_exact_match_clusters(None), [])

    def test_source_filter_excludes_irrelevant_clusters(self):
        from events.management.commands.deduplicate_organizers import (
            find_exact_match_clusters,
        )
        # Cluster 1: A (eventbrite) + B (planout) share website.
        self._make_organizer(source="eventbrite", website="https://a-b.ph")
        self._make_organizer(source="planout", website="https://a-b.ph")
        # Cluster 2: C (facebook) + D (planout) share email.
        self._make_organizer(source="facebook", email="cd@x.ph")
        self._make_organizer(source="planout", email="cd@x.ph")
        clusters = find_exact_match_clusters(source_filter="eventbrite")
        self.assertEqual(len(clusters), 1)
        sources = {o.source for o in clusters[0]}
        self.assertEqual(sources, {"eventbrite", "planout"})

    # -- Winner selection --------------------------------------------------- #

    def test_winner_is_confirmed_over_pending(self):
        from events.management.commands.deduplicate_organizers import (
            find_exact_match_clusters, select_winner,
        )
        self._make_organizer(
            source="eventbrite", website="https://w.ph",
            status=Organizer.STATUS_PENDING,
        )
        confirmed = self._make_organizer(
            source="planout", website="https://w.ph",
            status=Organizer.STATUS_CONFIRMED,
        )
        cluster = find_exact_match_clusters(None)[0]
        winner, _losers = select_winner(cluster)
        self.assertEqual(winner.pk, confirmed.pk)

    def test_winner_is_higher_event_count(self):
        from events.management.commands.deduplicate_organizers import (
            find_exact_match_clusters, select_winner,
        )
        low = self._make_organizer(source="eventbrite", website="https://c.ph")
        high = self._make_organizer(source="planout", website="https://c.ph")
        self._make_event(high)
        self._make_event(high)
        self._make_event(high)
        cluster = find_exact_match_clusters(None)[0]
        winner, losers = select_winner(cluster)
        self.assertEqual(winner.pk, high.pk)
        self.assertEqual([loser.pk for loser in losers], [low.pk])

    def test_winner_is_more_complete(self):
        from events.management.commands.deduplicate_organizers import (
            find_exact_match_clusters, select_winner,
        )
        sparse = self._make_organizer(source="eventbrite", website="https://m.ph")
        full = self._make_organizer(
            source="planout", website="https://m.ph", email="hi@m.ph",
        )
        cluster = find_exact_match_clusters(None)[0]
        winner, _losers = select_winner(cluster)
        self.assertEqual(winner.pk, full.pk)

    def test_winner_is_lower_pk_on_tie(self):
        from events.management.commands.deduplicate_organizers import (
            find_exact_match_clusters, select_winner,
        )
        first = self._make_organizer(source="eventbrite", website="https://t.ph")
        second = self._make_organizer(source="planout", website="https://t.ph")
        cluster = find_exact_match_clusters(None)[0]
        winner, _losers = select_winner(cluster)
        self.assertEqual(winner.pk, min(first.pk, second.pk))

    # -- Merge mechanics ---------------------------------------------------- #

    def test_dry_run_makes_no_db_changes(self):
        winner = self._make_organizer(source="eventbrite", website="https://d.ph")
        loser = self._make_organizer(source="planout", website="https://d.ph")
        event = self._make_event(loser)
        out = StringIO()
        call_command("deduplicate_organizers", "--dry-run", stdout=out)
        event.refresh_from_db()
        self.assertEqual(event.organizer_ref_id, loser.pk)
        self.assertTrue(Organizer.objects.filter(pk=winner.pk).exists())
        self.assertTrue(Organizer.objects.filter(pk=loser.pk).exists())

    def test_execute_repoints_events_and_deletes_loser(self):
        winner = self._make_organizer(
            source="eventbrite", website="https://e.ph",
            status=Organizer.STATUS_CONFIRMED,
        )
        loser = self._make_organizer(source="planout", website="https://e.ph")
        event = self._make_event(loser)
        out = StringIO()
        call_command("deduplicate_organizers", "--execute", stdout=out)
        event.refresh_from_db()
        self.assertEqual(event.organizer_ref_id, winner.pk)
        self.assertFalse(Organizer.objects.filter(pk=loser.pk).exists())

    def test_execute_multiple_clusters_all_merged(self):
        # Cluster A (3 organizers).
        self._make_organizer(source="s1", website="https://ca.ph")
        self._make_organizer(source="s2", website="https://ca.ph")
        self._make_organizer(source="s3", website="https://ca.ph")
        # Cluster B (3 organizers).
        self._make_organizer(source="s1", email="cb@x.ph")
        self._make_organizer(source="s2", email="cb@x.ph")
        self._make_organizer(source="s3", email="cb@x.ph")
        out = StringIO()
        call_command("deduplicate_organizers", "--execute", stdout=out)
        self.assertEqual(Organizer.objects.count(), 2)

    def test_winner_scraped_at_updated_when_null(self):
        recent = timezone.now()
        winner = self._make_organizer(
            source="eventbrite", website="https://sn.ph",
            status=Organizer.STATUS_CONFIRMED, scraped_at=None,
        )
        self._make_organizer(
            source="planout", website="https://sn.ph", scraped_at=recent,
        )
        out = StringIO()
        call_command("deduplicate_organizers", "--execute", stdout=out)
        winner.refresh_from_db()
        self.assertEqual(winner.scraped_at, recent)

    def test_winner_scraped_at_not_overwritten_when_set(self):
        own = timezone.now() - timedelta(days=5)
        loser_time = timezone.now()
        winner = self._make_organizer(
            source="eventbrite", website="https://so.ph",
            status=Organizer.STATUS_CONFIRMED, scraped_at=own,
        )
        self._make_organizer(
            source="planout", website="https://so.ph", scraped_at=loser_time,
        )
        out = StringIO()
        call_command("deduplicate_organizers", "--execute", stdout=out)
        winner.refresh_from_db()
        self.assertEqual(winner.scraped_at, own)

    def test_limit_caps_clusters_processed(self):
        for i in range(3):
            self._make_organizer(source="s1", website=f"https://lim{i}.ph")
            self._make_organizer(source="s2", website=f"https://lim{i}.ph")
        out = StringIO()
        call_command("deduplicate_organizers", "--execute", "--limit", "1", stdout=out)
        # Only one cluster merged: 6 - 1 deleted = 5 remain.
        self.assertEqual(Organizer.objects.count(), 5)

    def test_mutual_exclusion_raises_command_error(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command("deduplicate_organizers", dry_run=True, execute=True)

    # -- Fuzzy pass --------------------------------------------------------- #

    def test_fuzzy_cluster_not_auto_merged(self):
        a = self._make_organizer(source="eventbrite", name="Awesome Events PH")
        b = self._make_organizer(source="planout", name="Awesome Events PHL")
        out = StringIO()
        call_command("deduplicate_organizers", "--execute", stdout=out)
        self.assertTrue(Organizer.objects.filter(pk=a.pk).exists())
        self.assertTrue(Organizer.objects.filter(pk=b.pk).exists())

    def test_fuzzy_output_csv_created(self):
        import csv as _csv
        import os
        import tempfile
        self._make_organizer(source="eventbrite", name="Awesome Events PH")
        self._make_organizer(source="planout", name="Awesome Events PHL")
        path = os.path.join(tempfile.mkdtemp(), "test_fuzzy.csv")
        out = StringIO()
        call_command("deduplicate_organizers", "--fuzzy-output", path, stdout=out)
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as handle:
            rows = list(_csv.reader(handle))
        self.assertEqual(
            rows[0],
            [
                "cluster_id", "pk", "name", "source", "status",
                "website", "email", "similarity_to_cluster_representative",
            ],
        )
        names = {row[2] for row in rows[1:]}
        self.assertIn("Awesome Events PH", names)
        self.assertIn("Awesome Events PHL", names)


class SearchQueryDecoupledSourceTests(TestCase):
    """POST /api/search-queries/ no longer requires a source (decoupled keywords)."""

    def test_create_without_source_succeeds(self):
        resp = self.client.post(
            "/api/search-queries/",
            data=json.dumps({"query": "test keyword"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["query"], "test keyword")
        self.assertEqual(body["source"], "")

    def test_create_missing_query_returns_400(self):
        resp = self.client.post(
            "/api/search-queries/",
            data=json.dumps({"source": "facebook_events"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_duplicate_query_returns_409(self):
        first = self.client.post(
            "/api/search-queries/",
            data=json.dumps({"query": "dup keyword"}),
            content_type="application/json",
        )
        self.assertEqual(first.status_code, 201)
        second = self.client.post(
            "/api/search-queries/",
            data=json.dumps({"query": "dup keyword"}),
            content_type="application/json",
        )
        self.assertEqual(second.status_code, 409)

    def test_unique_query_constraint_ignores_source(self):
        SearchQuery.objects.create(query="kw", source="facebook_events")
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            SearchQuery.objects.create(query="kw", source="other_source")


class ScraperTriggerQueryIdsTests(TestCase):
    """POST /api/scrapers/<key>/run/ accepts an optional query_ids list."""

    def test_run_with_query_ids_creates_plain_keyed_run(self):
        mock_run = mock.Mock(id=7, status="queued")
        with mock.patch(
            "events.views.trigger_scraper_run", return_value=(mock_run, False)
        ) as mock_trigger:
            resp = self.client.post(
                "/api/scrapers/facebook_events/run/",
                data=json.dumps({"query_ids": [1, 2]}),
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 200)
        _, kwargs = mock_trigger.call_args
        self.assertEqual(kwargs["query_ids"], [1, 2])

    def test_run_with_query_ids_real_run_uses_plain_scraper_key(self):
        fake_cls = mock.Mock()
        fake_cls.return_value.run.return_value = {
            "source": "facebook_events", "created": 0, "updated": 0,
        }
        with mock.patch.dict(runner.SCRAPERS, {"facebook_events": fake_cls}):
            resp = self.client.post(
                "/api/scrapers/facebook_events/run/",
                data=json.dumps({"query_ids": [1, 2]}),
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 200)
        run = ScraperRun.objects.get(id=resp.json()["id"])
        self.assertEqual(run.scraper_key, "facebook_events")

    def test_run_with_bad_query_ids_returns_400(self):
        resp = self.client.post(
            "/api/scrapers/facebook_events/run/",
            data=json.dumps({"query_ids": "bad"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_run_with_invalid_json_returns_400(self):
        resp = self.client.post(
            "/api/scrapers/facebook_events/run/",
            data="not-json{{{",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_run_with_keywords_on_unsupported_scraper_returns_400(self):
        resp = self.client.post(
            "/api/scrapers/google_places/run/",
            data=json.dumps({"query_ids": [1, 2]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)


class ScrapersSupportsKeywordsTests(TestCase):
    """GET /api/scrapers/ exposes supports_keywords per scraper."""

    def test_facebook_events_supports_keywords_true(self):
        resp = self.client.get("/api/scrapers/")
        self.assertEqual(resp.status_code, 200)
        by_key = {s["key"]: s for s in resp.json()}
        self.assertTrue(by_key["facebook_events"]["supports_keywords"])
        self.assertFalse(by_key["google_places"]["supports_keywords"])
