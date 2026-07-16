"""Tests for the Discord notifications module.

All network I/O is mocked — no real Discord calls are made. The key guarantees
under test:
  - No-op when DISCORD_WEBHOOK_URL is empty (no urlopen call).
  - A configured webhook triggers a correctly structured POST.
  - session_expired dispatch is selected from an error_message prefix by callers.
  - Exceptions inside the HTTP layer never propagate.
"""
import json
from unittest.mock import patch

from django.test import TestCase, override_settings

from events import notifications


def _join_threads():
    """Wait for any notification threads spawned by _fire/patch_run_all_progress.

    Threads are non-daemon (so subprocess workers wait for them), so we join
    all non-main threads rather than filtering by t.daemon.
    """
    import threading

    for t in threading.enumerate():
        if t is not threading.current_thread():
            t.join(timeout=2)


@override_settings(DISCORD_WEBHOOK_URL="")
class NotificationNoOpTests(TestCase):
    @patch("events.notifications.urllib.request.urlopen")
    def test_started_is_noop_when_unset(self, mock_urlopen):
        notifications.notify_scraper_event("started", scraper_key="test", run_id=1)
        _join_threads()
        mock_urlopen.assert_not_called()

    @patch("events.notifications.urllib.request.urlopen")
    def test_post_run_all_start_returns_none_when_unset(self, mock_urlopen):
        result = notifications.post_run_all_start(["a", "b"])
        self.assertIsNone(result)
        mock_urlopen.assert_not_called()

    @patch("events.notifications.urllib.request.urlopen")
    def test_patch_progress_is_noop_when_unset(self, mock_urlopen):
        notifications.patch_run_all_progress("123", [], {})
        _join_threads()
        mock_urlopen.assert_not_called()


@override_settings(DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/111/tok")
class NotificationPostTests(TestCase):
    @patch("events.notifications.urllib.request.urlopen")
    def test_success_posts_structured_json(self, mock_urlopen):
        notifications.notify_scraper_event(
            "success", scraper_key="allevents", run_id=5,
            created_count=24, updated_count=3, duration_s=12,
        )
        _join_threads()
        self.assertTrue(mock_urlopen.called)
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        self.assertIn("embeds", payload)
        embed = payload["embeds"][0]
        self.assertEqual(embed["color"], notifications._COLOR_GREEN)
        self.assertIn("allevents", embed["title"])

    @patch("events.notifications.urllib.request.urlopen")
    def test_session_expired_dispatch(self, mock_urlopen):
        notifications.notify_scraper_event(
            "session_expired", scraper_key="facebook_events", run_id=7,
            source="facebook",
        )
        _join_threads()
        self.assertTrue(mock_urlopen.called)
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        embed = payload["embeds"][0]
        self.assertEqual(embed["color"], notifications._COLOR_YELLOW)
        self.assertIn("facebook", embed["description"])

    @patch("events.notifications.urllib.request.urlopen")
    def test_failed_truncates_error_message(self, mock_urlopen):
        long_err = "x" * 1000
        notifications.notify_scraper_event(
            "failed", scraper_key="planout", run_id=9, error_message=long_err,
        )
        _join_threads()
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        embed = payload["embeds"][0]
        error_field = next(f for f in embed["fields"] if f["name"] == "Error")
        self.assertEqual(len(error_field["value"]), 500)

    @patch("events.notifications.urllib.request.urlopen", side_effect=OSError("boom"))
    def test_exception_does_not_propagate(self, mock_urlopen):
        # Should not raise even though the underlying urlopen throws.
        notifications.notify_scraper_event("started", scraper_key="x", run_id=1)
        _join_threads()
        self.assertTrue(mock_urlopen.called)

    def test_post_run_all_start_parses_message_id(self):
        class _FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({"id": "987654321"}).encode("utf-8")

        with patch(
            "events.notifications.urllib.request.urlopen", return_value=_FakeResp()
        ):
            result = notifications.post_run_all_start(["a", "b"])
        self.assertEqual(result, "987654321")


class _StubRun:
    """Minimal stand-in for a ScraperRun row in a 'running' state."""

    def __init__(self, scraper_key, extra_counts=None):
        self.status = "running"
        self.scraper_key = scraper_key
        self.extra_counts = extra_counts


class ScoreboardKeywordProgressTests(TestCase):
    def test_running_line_shows_keyword_progress(self):
        run = _StubRun("facebook_events", {"keyword_index": 3, "keyword_total": 8})
        embed = notifications._build_scoreboard_embed([run], {})
        self.assertIn("3/8 kw", embed["description"])
        self.assertNotIn("running…", embed["description"])

    def test_running_line_falls_back_when_no_keyword_data(self):
        run = _StubRun("facebook_posts", {})
        embed = notifications._build_scoreboard_embed([run], {})
        self.assertIn("running…", embed["description"])
        self.assertNotIn("kw", embed["description"])

    def test_running_line_falls_back_when_extra_counts_none(self):
        run = _StubRun("facebook_posts", None)
        embed = notifications._build_scoreboard_embed([run], {})
        self.assertIn("running…", embed["description"])


class FormatBytesTests(TestCase):
    def test_none_and_zero(self):
        self.assertEqual(notifications._format_bytes(None), "—")
        self.assertEqual(notifications._format_bytes(0), "—")

    def test_units(self):
        self.assertEqual(notifications._format_bytes(512), "512 B")
        self.assertEqual(notifications._format_bytes(2048), "2.0 KB")
        self.assertEqual(notifications._format_bytes(2 * 1024 ** 2), "2.0 MB")
        self.assertEqual(notifications._format_bytes(3 * 1024 ** 3), "3.00 GB")
