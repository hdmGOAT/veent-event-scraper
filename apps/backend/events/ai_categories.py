"""AI-assisted event categorization via the local Claude CLI.

Maps each event's raw/noisy category string (plus name and description) into the
canonical taxonomy below by shelling out to the local Claude Code CLI. No API key
is required — it uses the developer's Claude Code subscription.

Two settings control the subprocess (both read from env vars):
- ``CLAUDE_CLI_CMD`` (default: ``"claude"``) — the CLI binary name/path.
- ``CLAUDE_CONFIG_DIR`` (default: ``""``) — if set, passed as the
  ``CLAUDE_CONFIG_DIR`` env var to the subprocess so non-default Claude
  accounts (e.g. ``claude-ojt`` which is an alias for
  ``CLAUDE_CONFIG_DIR=~/.claude-account-ojt claude``) work correctly.

Only ``categorize_events_by_ids`` writes to the DB (``Event.agent_categories``);
no scraper upsert path touches that field.
"""

from __future__ import annotations

import json
import os
import subprocess

from django.conf import settings

# The only valid values for Event.agent_categories items.
CANONICAL_CATEGORIES = [
    "Fun Run / Road Race",
    "Trail Run",
    "Triathlon / Duathlon",
    "Cycling",
    "Swimming",
    "Sports & Fitness",
    "Music & Concert",
    "Festival",
    "Conference / Seminar",
    "Workshop / Training",
    "Food & Dining",
    "Arts & Culture",
    "Theater & Performing Arts",
    "Charity / Fundraiser",
    "Other",
]

_CANONICAL_SET = set(CANONICAL_CATEGORIES)

_SYSTEM_PROMPT = (
    "You are a strict event classifier. Return ONLY valid JSON, no markdown, no "
    "explanation. Each event must map to 1-2 labels chosen exclusively from this "
    "list: " + json.dumps(CANONICAL_CATEGORIES)
)


def _build_prompt(events) -> str:
    """Build a single CLI prompt for a batch of events."""
    lines = [
        _SYSTEM_PROMPT,
        "",
        "Classify each of the following events. Use the event name, raw category, "
        "and description to decide. If the raw category is empty, classify from the "
        "name and description alone.",
        "",
        "Return ONLY a JSON object mapping each event id (as a string key) to an "
        'array of 1-2 canonical labels. Example: '
        '{"1": ["Fun Run / Road Race"], "2": ["Sports & Fitness", "Festival"]}',
        "",
        "Events:",
    ]
    for event in events:
        description = (event.description or "")[:200]
        lines.append(
            json.dumps(
                {
                    "id": event.pk,
                    "name": event.name or "",
                    "category": event.category or "",
                    "description": description,
                }
            )
        )
    return "\n".join(lines)


def _validate_labels(raw_labels) -> list[str]:
    """Keep only canonical labels; fall back to ['Other'] if none survive."""
    if not isinstance(raw_labels, list):
        return ["Other"]
    valid = [label for label in raw_labels if label in _CANONICAL_SET]
    return valid or ["Other"]


def _parse_response(stdout: str, event_ids: list[int]) -> dict[int, list[str]]:
    """Parse the CLI JSON response into {event_id: [labels]}.

    Any event missing from (or malformed in) the response falls back to ['Other'].
    """
    result: dict[int, list[str]] = {}
    try:
        parsed = json.loads(stdout.strip())
    except (json.JSONDecodeError, AttributeError):
        parsed = {}

    mapping = parsed if isinstance(parsed, dict) else {}
    for event_id in event_ids:
        raw_labels = mapping.get(str(event_id))
        result[event_id] = _validate_labels(raw_labels)
    return result


def batch_categorize(events, cli_cmd: str | None = None) -> dict[int, list[str]]:
    """Categorize up to ~20 events in a single Claude CLI call.

    Returns ``{event_id: [canonical_labels]}``. Invalid or missing labels fall
    back to ``["Other"]``. Raises ``FileNotFoundError`` (with a helpful message)
    when the CLI command is not found on PATH.
    """
    events = list(events)
    if not events:
        return {}

    if cli_cmd is None:
        cli_cmd = settings.CLAUDE_CLI_CMD

    prompt = _build_prompt(events)
    event_ids = [event.pk for event in events]

    # Build subprocess env: inherit current env, optionally inject CLAUDE_CONFIG_DIR.
    # This allows non-default Claude accounts that are normally accessed via a shell
    # alias (e.g. `claude-ojt` = `CLAUDE_CONFIG_DIR=~/.claude-account-ojt claude`)
    # to work without needing a real binary alias on PATH.
    sub_env = os.environ.copy()
    config_dir = getattr(settings, "CLAUDE_CONFIG_DIR", "")
    if config_dir:
        sub_env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(config_dir)

    try:
        completed = subprocess.run(
            [cli_cmd, "--model", "claude-haiku-4-5-20251001", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=60,
            env=sub_env,
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Claude CLI command '{cli_cmd}' not found on PATH. Set the "
            f"CLAUDE_CLI_CMD setting (env var CLAUDE_CLI_CMD) to the correct "
            f"binary name for this machine (e.g. 'claude'). If you use a named "
            f"account alias, set CLAUDE_CONFIG_DIR to the config directory path "
            f"(e.g. ~/.claude-account-ojt) and keep CLAUDE_CLI_CMD=claude."
        ) from exc

    return _parse_response(completed.stdout, event_ids)


def categorize_events_by_ids(ids, batch_size: int = 20, skip_classified: bool = True) -> int:
    """Classify the given events and persist results to ``agent_categories``.

    Queries Neon first to find which events are already classified, then only
    calls Claude for the uncategorized ones — avoids spending tokens on events
    that already have labels. Pass ``skip_classified=False`` to force
    re-classification of everything (e.g. ``--all`` flag).

    Only this function writes to ``agent_categories``.
    """
    from events.models import Event

    ids = list(ids)
    if not ids:
        return 0

    qs = Event.objects.filter(pk__in=ids)
    if skip_classified:
        qs = qs.filter(agent_categories=[])

    events = list(qs)
    if not events:
        return 0

    classified = 0
    for start in range(0, len(events), batch_size):
        batch = events[start : start + batch_size]
        labels_by_id = batch_categorize(batch)
        to_update = []
        for event in batch:
            labels = labels_by_id.get(event.pk)
            if labels is None:
                continue
            event.agent_categories = labels
            to_update.append(event)
        if to_update:
            Event.objects.bulk_update(to_update, ["agent_categories"])
            classified += len(to_update)

    return classified
