"""Discord webhook notifications for scraper lifecycle events.

This module is the sole owner of Discord logic in the backend. It is fully
opt-in: when ``settings.DISCORD_WEBHOOK_URL`` is empty, every public function
returns immediately without any network I/O.

Design constraints (see discord-notifications plan):
  - No third-party packages: uses ``urllib.request`` from the stdlib.
  - Fire-and-forget: individual-run notifications and scoreboard patches run in
    a daemon thread so the caller (a scraper worker / web request) is never
    blocked and never sees an exception from Discord.
  - ``post_run_all_start`` is the one synchronous call — it needs the returned
    message ID before the batch can be tagged — but is bounded by a 5s timeout
    and returns ``None`` on any failure.

Public API:
  - ``notify_scraper_event(event_type, **kwargs) -> None``
  - ``post_run_all_start(scraper_keys) -> str | None``
  - ``patch_run_all_progress(message_id, runs, bandwidth_by_run) -> None``
"""
import json
import logging
import threading
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 5  # seconds — outbound Discord HTTP timeout

# Embed colors (decimal), matching the plan's Functional Requirements table.
_COLOR_BLUE = 3447003
_COLOR_GREEN = 5763719
_COLOR_RED = 15548997
_COLOR_YELLOW = 16776960

# Status emoji for the scoreboard grid.
_STATUS_EMOJI = {
    "queued": "⏳",          # hourglass
    "running": "\U0001f504",     # counterclockwise arrows
    "success": "✅",         # check mark
    "failed": "❌",          # cross mark
    "session_expired": "⚠️",  # warning sign
}


# --------------------------------------------------------------------------- #
# Low-level HTTP helpers
# --------------------------------------------------------------------------- #
def _webhook_url() -> str:
    """Return the configured webhook URL (may be empty)."""
    return getattr(settings, "DISCORD_WEBHOOK_URL", "") or ""


def _parse_webhook(url: str) -> tuple[str, str]:
    """Split a webhook URL into ``(webhook_id, webhook_token)``.

    URL form: ``https://discord.com/api/webhooks/{webhook_id}/{webhook_token}``.
    The last two path segments are the token and id respectively.
    """
    parts = url.rstrip("/").split("/")
    token = parts[-1]
    webhook_id = parts[-2]
    return webhook_id, token


def _post_embed(payload: dict) -> None:
    """POST a single-embed payload to the webhook. Never raises."""
    url = _webhook_url()
    if not url:
        return
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json", "User-Agent": "DiscordBot (veent-event-scraper, 1.0)"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 — fire-and-forget: log, never raise
        logger.warning("Discord notification failed: %s", exc)


def _fire(payload: dict) -> None:
    """Spawn a thread that POSTs ``payload``; returns immediately.

    Non-daemon so subprocess workers (run_scraper_job.py) wait for the POST to
    finish before the process exits. Bounded by _TIMEOUT so it never hangs.
    """
    thread = threading.Thread(target=_post_embed, args=(payload,))
    thread.start()


def _build_embed(title: str, description: str, color: int, fields=None) -> dict:
    """Construct a Discord embed dict."""
    embed = {"title": title, "color": color}
    if description:
        embed["description"] = description
    if fields:
        embed["fields"] = fields
    return embed


def _format_bytes(n) -> str:
    """Human-readable byte count. ``None``/``0`` render as an em-dash."""
    if not n:
        return "—"  # em dash
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


# --------------------------------------------------------------------------- #
# Individual-run event builders
# --------------------------------------------------------------------------- #
def _embed_started(kwargs: dict) -> dict:
    key = kwargs.get("scraper_key", "?")
    run_id = kwargs.get("run_id")
    return _build_embed(
        title=f"\U0001f680 Scraper started: {key}",
        description="",
        color=_COLOR_BLUE,
        fields=[{"name": "Run ID", "value": str(run_id), "inline": True}],
    )


def _embed_success(kwargs: dict) -> dict:
    key = kwargs.get("scraper_key", "?")
    run_id = kwargs.get("run_id")
    created = kwargs.get("created_count", 0)
    updated = kwargs.get("updated_count", 0)
    duration = kwargs.get("duration_s", 0) or 0
    return _build_embed(
        title=f"✅ Scraper succeeded: {key}",
        description="",
        color=_COLOR_GREEN,
        fields=[
            {"name": "Run ID", "value": str(run_id), "inline": True},
            {"name": "Created", "value": str(created), "inline": True},
            {"name": "Updated", "value": str(updated), "inline": True},
            {"name": "Duration", "value": f"{duration:.0f}s", "inline": True},
        ],
    )


def _embed_failed(kwargs: dict) -> dict:
    key = kwargs.get("scraper_key", "?")
    run_id = kwargs.get("run_id")
    error_message = kwargs.get("error_message") or ""
    fields = [{"name": "Run ID", "value": str(run_id), "inline": True}]
    if error_message:
        fields.append(
            {"name": "Error", "value": error_message[:500], "inline": False}
        )
    return _build_embed(
        title=f"❌ Scraper failed: {key}",
        description="",
        color=_COLOR_RED,
        fields=fields,
    )


def _embed_session_expired(kwargs: dict) -> dict:
    key = kwargs.get("scraper_key", "?")
    run_id = kwargs.get("run_id")
    source = kwargs.get("source", "?")
    return _build_embed(
        title=f"⚠️ Session expired: {key}",
        description=f"Authentication lost for source **{source}**. Re-login required.",
        color=_COLOR_YELLOW,
        fields=[
            {"name": "Run ID", "value": str(run_id), "inline": True},
            {"name": "Source", "value": str(source), "inline": True},
        ],
    )


def _embed_run_all_summary(kwargs: dict) -> dict:
    created = kwargs.get("created") or []
    skipped = kwargs.get("skipped") or []
    created_keys = ", ".join(c.get("key", "?") for c in created) or "—"
    skipped_keys = ", ".join(skipped) or "—"
    return _build_embed(
        title="\U0001f504 Run-All triggered",
        description="",
        color=_COLOR_BLUE,
        fields=[
            {"name": f"Triggered ({len(created)})", "value": created_keys, "inline": False},
            {"name": f"Skipped ({len(skipped)})", "value": skipped_keys, "inline": False},
        ],
    )


_EVENT_BUILDERS = {
    "started": _embed_started,
    "success": _embed_success,
    "failed": _embed_failed,
    "session_expired": _embed_session_expired,
    "run_all_summary": _embed_run_all_summary,
}


def notify_scraper_event(event_type: str, **kwargs) -> None:
    """Fire a Discord notification for a scraper lifecycle event.

    No-op when ``DISCORD_WEBHOOK_URL`` is unset. Never raises. Dispatches to the
    matching embed builder and posts in a daemon thread.
    """
    if not _webhook_url():
        return
    builder = _EVENT_BUILDERS.get(event_type)
    if builder is None:
        logger.warning("Unknown Discord event_type: %s", event_type)
        return
    try:
        embed = builder(kwargs)
    except Exception as exc:  # noqa: BLE001 — never let embed building break the caller
        logger.warning("Failed to build Discord embed for %s: %s", event_type, exc)
        return
    _fire({"embeds": [embed]})


# --------------------------------------------------------------------------- #
# Run-all live scoreboard (Phase 6/7)
# --------------------------------------------------------------------------- #
def _duration_str(run) -> str:
    """Format a run's duration as ``12s`` or ``1m 5s``; ``—`` if unfinished."""
    if not (run.started_at and run.finished_at):
        return "—"
    total = int((run.finished_at - run.started_at).total_seconds())
    if total < 60:
        return f"{total}s"
    return f"{total // 60}m {total % 60}s"


def _build_scoreboard_embed(runs: list, bandwidth_by_run: dict) -> dict:
    """Construct the run-all scoreboard embed from the batch's runs.

    Color: red if any run FAILED, green if all terminal and none failed, blue
    while any run is still QUEUED/RUNNING.
    """
    lines = []
    total_created = 0
    total_updated = 0
    total_bw = 0
    done = 0
    any_failed = False
    any_pending = False

    for run in runs:
        status = run.status
        emoji = _STATUS_EMOJI.get(status, "❓")
        key = run.scraper_key
        if status == "queued":
            any_pending = True
            lines.append(f"{emoji} {key:<16} queued")
        elif status == "running":
            any_pending = True
            ec = run.extra_counts or {}
            ki = ec.get("keyword_index")
            kt = ec.get("keyword_total")
            progress = f"{ki}/{kt} kw" if ki is not None and kt else "running…"
            lines.append(f"{emoji} {key:<16} {progress}")
        elif status == "failed":
            any_failed = True
            done += 1
            err = (run.error_message or "").splitlines()[0] if run.error_message else ""
            lines.append(f"{emoji} {key:<16} FAILED — {err[:60]}")
        else:
            # success or session_expired (both terminal / non-failed)
            done += 1
            created = run.created_count or 0
            updated = run.updated_count or 0
            total_created += created
            total_updated += updated
            bw = bandwidth_by_run.get(run.id) or 0
            total_bw += bw
            lines.append(
                f"{emoji} {key:<16} +{created}  upd {updated}   "
                f"{_duration_str(run)}   {_format_bytes(bw)}"
            )

    if any_failed:
        color = _COLOR_RED
    elif any_pending:
        color = _COLOR_BLUE
    else:
        color = _COLOR_GREEN

    body = "```\n" + "\n".join(lines) + "\n```" if lines else "```\n(no runs)\n```"
    footer = (
        f"Progress: {done}/{len(runs)}  •  Total created: {total_created}  "
        f"•  Updated: {total_updated}  "
        f"•  Bandwidth: {_format_bytes(total_bw)}"
    )

    return {
        "title": "\U0001f504 Run-All Scrape",
        "color": color,
        "description": body,
        "footer": {"text": footer},
    }


def _build_initial_scoreboard_embed(scraper_keys: list) -> dict:
    """Build the "all queued" embed posted before any scraper finishes."""
    emoji = _STATUS_EMOJI["queued"]
    lines = [f"{emoji} {key:<16} queued" for key in scraper_keys]
    body = "```\n" + "\n".join(lines) + "\n```" if lines else "```\n(no scrapers)\n```"
    footer = (
        f"Progress: 0/{len(scraper_keys)}  •  Total created: 0  "
        f"•  Updated: 0  •  Bandwidth: —"
    )
    return {
        "title": "\U0001f504 Run-All Scrape",
        "color": _COLOR_BLUE,
        "description": body,
        "footer": {"text": footer},
    }


def post_run_all_start(scraper_keys: list) -> str | None:
    """Synchronously POST the initial scoreboard embed and return its message ID.

    Returns ``None`` when the webhook is unset or the POST fails / times out.
    Uses ``?wait=true`` so Discord returns the created message object as JSON.
    """
    url = _webhook_url()
    if not url:
        return None
    try:
        embed = _build_initial_scoreboard_embed(scraper_keys)
        payload = json.dumps({"embeds": [embed]}).encode("utf-8")
        post_url = url.rstrip("/") + "?wait=true"
        req = urllib.request.Request(
            post_url, data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "DiscordBot (veent-event-scraper, 1.0)"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        message_id = body.get("id")
        return str(message_id) if message_id else None
    except Exception as exc:  # noqa: BLE001 — return None, never raise
        logger.warning("Discord run-all start POST failed: %s", exc)
        return None


def _patch_scoreboard(message_id: str, payload: dict) -> None:
    """PATCH the scoreboard message. Never raises."""
    url = _webhook_url()
    if not url:
        return
    try:
        webhook_id, token = _parse_webhook(url)
        edit_url = (
            f"https://discord.com/api/webhooks/{webhook_id}/{token}/messages/{message_id}"
        )
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            edit_url, data=data,
            headers={"Content-Type": "application/json", "User-Agent": "DiscordBot (veent-event-scraper, 1.0)"},
            method="PATCH",
        )
        urllib.request.urlopen(req, timeout=_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 — fire-and-forget: log, never raise
        logger.warning("Discord scoreboard PATCH failed: %s", exc)


def patch_run_all_progress(message_id: str, runs: list, bandwidth_by_run: dict) -> None:
    """Rebuild the scoreboard embed and PATCH it in a daemon thread. Never raises."""
    if not _webhook_url() or not message_id:
        return
    try:
        embed = _build_scoreboard_embed(runs, bandwidth_by_run)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to build scoreboard embed: %s", exc)
        return
    payload = {"embeds": [embed]}
    thread = threading.Thread(target=_patch_scoreboard, args=(message_id, payload))
    thread.start()
