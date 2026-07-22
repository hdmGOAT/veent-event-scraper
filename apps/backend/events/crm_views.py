"""CRM-facing API views.

This module exposes a dedicated ``/crm/`` API surface consumed by the Veent CRM
(SvelteKit). Unlike the ``/api/`` routes — which are protected by a Django
session cookie — these endpoints authenticate with a static ``X-API-Key`` header
validated against ``settings.CRM_API_KEY`` (see :func:`crm_api_required`).

The surface is additive only: it reuses existing models, ``runner`` functions,
and the ``_serialize_run`` helper from ``events.views``. No existing ``/api/``
behaviour is changed.
"""
import functools
import json
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Event, ScraperConfig, ScraperRun
from .runner import cancel_run, trigger_scraper_run
from .scrapers import SCRAPERS
from .scrapers.proxy_manager import get_proxy_enabled
from .views import _serialize_run

_ACTIVE_STATUSES = ["queued", "running"]


# ---------------------------------------------------------------------------
# Auth decorator
# ---------------------------------------------------------------------------
def crm_api_required(view_func):
    """Gate a view behind the static ``X-API-Key`` header.

    - 403 if ``settings.CRM_API_KEY`` is unset/empty (API not configured).
    - 401 if the ``X-API-Key`` header is missing or does not match.
    - Otherwise, delegates to ``view_func``.
    """
    @functools.wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        configured = getattr(settings, "CRM_API_KEY", "")
        if not configured:
            return JsonResponse({"error": "CRM API not configured"}, status=403)
        provided = request.headers.get("X-API-Key", "")
        if not provided or provided != configured:
            return JsonResponse({"error": "unauthorized"}, status=401)
        return view_func(request, *args, **kwargs)

    return _wrapped


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _scraper_aggregate(key, last_n=30):
    """Aggregate metrics over the most recent ``last_n`` runs for ``key``."""
    runs = list(
        ScraperRun.objects.filter(scraper_key=key)
        .order_by("-created_at")[:last_n]
    )
    total = len(runs)
    if total == 0:
        return {
            "success_rate": 0.0,
            "avg_duration_seconds": None,
            "avg_created": 0,
            "consecutive_failure_streak": 0,
        }

    success_count = sum(1 for r in runs if r.status == "success")

    durations = [
        r.duration_seconds for r in runs
        if r.started_at is not None and r.finished_at is not None
    ]
    avg_duration = (sum(durations) / len(durations)) if durations else None

    avg_created = sum(r.created_count for r in runs) / total

    streak = 0
    for r in runs:  # most-recent first
        if r.status == "failed":
            streak += 1
        else:
            break

    return {
        "success_rate": success_count / total,
        "avg_duration_seconds": avg_duration,
        "avg_created": avg_created,
        "consecutive_failure_streak": streak,
    }


def _seconds_since_last_success(key):
    row = (
        ScraperRun.objects.filter(scraper_key=key, status="success")
        .order_by("-finished_at")
        .values("finished_at")
        .first()
    )
    if row and row["finished_at"]:
        return int((timezone.now() - row["finished_at"]).total_seconds())
    return None


def _total_events_for_key(key):
    return Event.objects.filter(source=key).count()


def _last_run_summary(run):
    if run is None:
        return None
    return {
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_seconds": run.duration_seconds,
        "created_count": run.created_count,
        "updated_count": run.updated_count,
    }


def _read_settings():
    """Return the current scheduler config, preferring the DB row over env vars."""
    import os

    cfg = ScraperConfig.objects.first()
    if cfg is not None:
        return {
            "source": "db",
            "scraper_keys": cfg.scraper_keys,
            "scraper_interval": cfg.scraper_interval,
            "push_interval": cfg.push_interval,
            "scraper_timeout": cfg.scraper_timeout,
            "per_key_intervals": cfg.per_key_intervals or {},
            "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
            "updated_by": cfg.updated_by,
        }
    return {
        "source": "env",
        "scraper_keys": os.environ.get("SCRAPER_KEYS", "").strip(),
        "scraper_interval": os.environ.get("SCRAPER_INTERVAL", "").strip(),
        "push_interval": os.environ.get("PUSH_INTERVAL", "").strip(),
        "scraper_timeout": os.environ.get("SCRAPER_TIMEOUT", "").strip(),
        "per_key_intervals": {},
        "updated_at": None,
        "updated_by": None,
    }


def _parse_interval_seconds(value):
    """Parse a "6h" / "30m" / "3600s" / integer string into seconds, or None."""
    if not value:
        return None
    v = value.strip().lower()
    try:
        if v.endswith("h"):
            return int(v[:-1]) * 3600
        if v.endswith("m"):
            return int(v[:-1]) * 60
        if v.endswith("s"):
            return int(v[:-1])
        return int(v)
    except (ValueError, TypeError):
        return None


def _scraper_entry(key, latest_runs):
    """Build the per-scraper dict shared by the list and detail endpoints."""
    run = latest_runs.get(key)
    is_active = ScraperRun.objects.filter(
        scraper_key=key, status__in=_ACTIVE_STATUSES
    ).exists()
    return {
        "key": key,
        "is_active": is_active,
        "last_run": _last_run_summary(run),
        "aggregate": _scraper_aggregate(key),
        "seconds_since_last_success": _seconds_since_last_success(key),
        "total_events_created": _total_events_for_key(key),
    }


def _latest_runs_by_key():
    """Most recent ScraperRun per key in a single DISTINCT ON query."""
    return {
        run.scraper_key: run
        for run in ScraperRun.objects.order_by(
            "scraper_key", "-created_at"
        ).distinct("scraper_key")
    }


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
@csrf_exempt
@crm_api_required
def crm_scrapers_list(request):
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    latest_runs = _latest_runs_by_key()
    results = [_scraper_entry(key, latest_runs) for key in SCRAPERS]
    return JsonResponse(results, safe=False)


@csrf_exempt
@crm_api_required
def crm_scraper_detail(request, key):
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    if key not in SCRAPERS:
        return JsonResponse({"error": "Unknown scraper key"}, status=404)
    latest_runs = _latest_runs_by_key()
    entry = _scraper_entry(key, latest_runs)
    recent = ScraperRun.objects.filter(scraper_key=key).order_by("-created_at")[:20]
    entry["recent_runs"] = [_serialize_run(r, include_log=False) for r in recent]
    return JsonResponse(entry)


@csrf_exempt
@crm_api_required
@require_POST
def crm_scraper_trigger(request, key):
    if key not in SCRAPERS:
        return JsonResponse({"error": "Unknown scraper key"}, status=404)
    run, already_active = trigger_scraper_run(key, triggered_by=None)
    if already_active:
        return JsonResponse({"error": "Scraper already running"}, status=409)
    return JsonResponse({"id": run.id, "status": run.status}, status=200)


@csrf_exempt
@crm_api_required
@require_POST
def crm_scraper_cancel(request, key):
    if key not in SCRAPERS:
        return JsonResponse({"error": "Unknown scraper key"}, status=404)
    run = (
        ScraperRun.objects.filter(scraper_key=key, status__in=_ACTIVE_STATUSES)
        .order_by("-created_at")
        .first()
    )
    if run is None:
        return JsonResponse({"error": "No active run for this key"}, status=404)
    cancelled, signal = cancel_run(run.id)
    if signal == "not_found":
        return JsonResponse({"error": "Run not found"}, status=404)
    if signal == "not_active":
        return JsonResponse(
            {"error": "Run is not active", "run": _serialize_run(cancelled)},
            status=409,
        )
    return JsonResponse(_serialize_run(cancelled), status=200)


_SETTINGS_STR_FIELDS = (
    "scraper_keys",
    "scraper_interval",
    "push_interval",
    "scraper_timeout",
)


@csrf_exempt
@crm_api_required
def crm_settings(request):
    if request.method == "GET":
        return JsonResponse(_read_settings())

    if request.method == "PATCH":
        try:
            body = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        if not isinstance(body, dict):
            return JsonResponse({"error": "Body must be a JSON object"}, status=400)

        # updated_by is metadata, not a config field — pull it out before
        # validating the remaining keys.
        body.pop("updated_by", None)

        allowed = set(_SETTINGS_STR_FIELDS) | {"per_key_intervals"}
        unknown = set(body.keys()) - allowed
        if unknown:
            return JsonResponse(
                {"error": f"Unknown field(s): {', '.join(sorted(unknown))}"},
                status=400,
            )

        for field in _SETTINGS_STR_FIELDS:
            if field in body and not isinstance(body[field], str):
                return JsonResponse(
                    {"error": f"{field} must be a string"}, status=400
                )

        if "per_key_intervals" in body:
            pki = body["per_key_intervals"]
            if not isinstance(pki, dict):
                return JsonResponse(
                    {"error": "per_key_intervals must be an object"}, status=400
                )
            for k, v in pki.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    return JsonResponse(
                        {"error": "per_key_intervals keys and values must be strings"},
                        status=400,
                    )

        cfg, _created = ScraperConfig.objects.get_or_create(id=1)
        for field in _SETTINGS_STR_FIELDS:
            if field in body:
                setattr(cfg, field, body[field])
        if "per_key_intervals" in body:
            cfg.per_key_intervals = body["per_key_intervals"]
        cfg.updated_by = request.headers.get("X-Caller", "")
        cfg.save()

        return JsonResponse(_read_settings())

    return JsonResponse({"error": "Method not allowed"}, status=405)


@csrf_exempt
@crm_api_required
def crm_pipeline(request):
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    now = timezone.now()
    by_source = list(
        Event.objects.exclude(source="")
        .values("source")
        .annotate(
            total_future=Count("id", filter=Q(starts_at__gte=now)),
            pending_push=Count(
                "id",
                filter=Q(crm_pushed_at__isnull=True, starts_at__gte=now),
            ),
            uncategorized=Count(
                "id",
                filter=Q(agent_categories=[], starts_at__gte=now),
            ),
        )
        .order_by("-total_future")
    )

    # Top 10 categories by count from AI-assigned agent_categories.
    from collections import Counter

    buckets: Counter = Counter()
    for e in Event.objects.exclude(agent_categories=[]).only("agent_categories"):
        for label in e.agent_categories:
            if label:
                buckets[label] += 1
    ordered = sorted(buckets.items(), key=lambda item: (-item[1], item[0]))
    global_categories = [
        {"category": name, "count": count} for name, count in ordered[:10]
    ]

    return JsonResponse(
        {"by_source": by_source, "global_categories": global_categories}
    )


@csrf_exempt
@crm_api_required
def crm_health(request):
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    active_runs = list(
        ScraperRun.objects.filter(status__in=_ACTIVE_STATUSES)
        .values_list("scraper_key", flat=True)
    )

    settings_data = _read_settings()
    interval = _parse_interval_seconds(settings_data.get("scraper_interval"))
    if interval is None:
        scheduler_alive = None
    else:
        cutoff = timezone.now() - timedelta(seconds=interval * 2)
        recent_run_exists = ScraperRun.objects.filter(
            created_at__gte=cutoff
        ).exists()
        scheduler_alive = bool(recent_run_exists or active_runs)

    return JsonResponse(
        {
            "scheduler_alive": scheduler_alive,
            "active_runs": active_runs,
            "active_run_count": len(active_runs),
            "proxy_enabled": get_proxy_enabled(),
        }
    )
