"""AI-assisted event categorization via the Groq API.

Maps each event's raw/noisy category string (plus name and description) into the
canonical taxonomy below using a Groq-hosted LLM. Requires GROQ_API_KEY and
GROQ_CATEGORIZE_MODEL to be set (via env vars / Django settings).

Only ``categorize_events_by_ids`` writes to the DB (``Event.agent_categories``);
no scraper upsert path touches that field.
"""

from __future__ import annotations

import json
import os

import requests
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


def batch_categorize(events) -> dict[int, list[str]]:
    """Categorize up to ~20 events in a single Groq API call.

    Returns ``{event_id: [canonical_labels]}``. Invalid or missing labels fall
    back to ``["Other"]``. Returns all-Other on any API error (non-fatal).
    """
    events = list(events)
    if not events:
        return {}

    api_key = settings.GROQ_API_KEY
    model   = settings.GROQ_CATEGORIZE_MODEL

    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Add it to your .env file. "
            "Get a free key at https://console.groq.com"
        )

    prompt    = _build_prompt(events)
    event_ids = [event.pk for event in events]

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Groq API request failed: {exc}") from exc

    return _parse_response(content, event_ids)


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
