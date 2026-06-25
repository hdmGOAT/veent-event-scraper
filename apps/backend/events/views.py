import csv
import json
import logging
import os
import threading

from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

from .categories import normalize_category
from .models import Event, Organizer, ScraperRun, SearchQuery, TrackerNote, Venue
from .runner import AVAILABLE_LOCATIONS, cancel_run, trigger_scraper_run


def event_list(request):
    query = request.GET.get("q", "").strip()
    events = Event.objects.select_related("venue")
    if query:
        events = events.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(venue__name__icontains=query)
        )
    upcoming = events.filter(starts_at__gte=timezone.now())
    context = {
        "events": events,
        "upcoming_count": upcoming.count(),
        "total_count": events.count(),
        "query": query,
    }
    return render(request, "events/event_list.html", context)


def event_detail(request, slug):
    event = get_object_or_404(
        Event.objects.select_related("venue", "organizer_ref"), slug=slug
    )
    return render(request, "events/event_detail.html", {"event": event})


def venue_list(request):
    query = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()
    venues = Venue.objects.annotate(event_count=Count("events"))
    if query:
        venues = venues.filter(
            Q(name__icontains=query) | Q(city__icontains=query)
        )
    if category:
        venues = venues.filter(primary_type_display=category)
    # Order by category so the template can {% regroup %} into sections.
    venues = venues.order_by("primary_type_display", "name")
    # Distinct non-empty categories for the filter control (alphabetical).
    categories = (
        Venue.objects.exclude(primary_type_display="")
        .values_list("primary_type_display", flat=True)
        .distinct()
        .order_by("primary_type_display")
    )
    # Geocoded venues for the Leaflet map (skip rows without coordinates).
    map_venues = [
        {
            "name": v.name,
            "url": v.get_absolute_url(),
            "lat": v.latitude,
            "lng": v.longitude,
        }
        for v in venues
        if v.latitude is not None and v.longitude is not None
    ]
    return render(
        request,
        "events/venue_list.html",
        {
            "venues": venues,
            "query": query,
            "category": category,
            "categories": categories,
            "map_venues": map_venues,
        },
    )


def venue_detail(request, slug):
    venue = get_object_or_404(Venue, slug=slug)
    events = venue.events.all()
    return render(
        request, "events/venue_detail.html", {"venue": venue, "events": events}
    )


# ---------------------------------------------------------------------------
# Public organizer directory — read-only list/detail of organizers.
# Everything except status=rejected is publicly visible (pending + confirmed);
# rejected organizers are the only hidden state, managed via the admin /
# internal review workflows.
# ---------------------------------------------------------------------------


def organizer_list(request):
    query = request.GET.get("q", "").strip()
    organizers = Organizer.objects.exclude(status=Organizer.STATUS_REJECTED)
    if query:
        organizers = organizers.filter(
            Q(name__icontains=query) | Q(city__icontains=query)
        )
    return render(
        request,
        "events/organizer_list.html",
        {"organizers": organizers, "query": query},
    )


def organizer_detail(request, slug):
    # Exclude only rejected organizers so a rejected slug 404s exactly like a
    # nonexistent one — no leakage of a hidden organizer's existence. Pending
    # and confirmed organizers are both publicly reachable.
    organizer = get_object_or_404(
        Organizer.objects.exclude(status=Organizer.STATUS_REJECTED), slug=slug
    )
    # Events linked to this organizer via the normalized FK (Event.organizer_ref,
    # related_name="events"). select_related("venue") avoids an N+1 when the
    # template renders each event's venue.
    events = organizer.events.select_related("venue")
    return render(
        request,
        "events/organizer_detail.html",
        {"organizer": organizer, "events": events},
    )


# ---------------------------------------------------------------------------
# Venue review UI (staff-only) — a UX-friendly alternative to Django admin for
# moving venues through the manual verification workflow.
# ---------------------------------------------------------------------------


@staff_member_required
def review_dashboard(request):
    """Status summary + filterable queue of venues to review."""
    status = request.GET.get("status", Venue.VerificationStatus.PENDING).strip()
    query = request.GET.get("q", "").strip()

    stats = Venue.objects.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(verification_status=Venue.VerificationStatus.PENDING)),
        verified=Count("id", filter=Q(verification_status=Venue.VerificationStatus.VERIFIED)),
        rejected=Count("id", filter=Q(verification_status=Venue.VerificationStatus.REJECTED)),
    )

    venues = Venue.objects.annotate(event_count=Count("events"))
    valid_statuses = set(Venue.VerificationStatus.values)
    if status in valid_statuses:
        venues = venues.filter(verification_status=status)
    else:
        status = ""  # "all" — no status filter
    if query:
        venues = venues.filter(Q(name__icontains=query) | Q(city__icontains=query))
    # Surface venues with events first — they are the strongest review signal.
    venues = venues.order_by("-event_count", "name")

    return render(
        request,
        "events/review/dashboard.html",
        {
            "stats": stats,
            "venues": venues,
            "status": status,
            "query": query,
            "status_choices": Venue.VerificationStatus.choices,
        },
    )


@staff_member_required
def review_venue_detail(request, slug):
    """Per-venue context plus the status control."""
    venue = get_object_or_404(Venue.objects.annotate(event_count=Count("events")), slug=slug)
    events = venue.events.all()[:20]
    amenities = {k: v for k, v in (venue.amenities or {}).items() if v}
    return render(
        request,
        "events/review/venue_detail.html",
        {
            "venue": venue,
            "events": events,
            "amenities": amenities,
            "status_choices": Venue.VerificationStatus.choices,
        },
    )


@staff_member_required
@require_POST
def review_set_status(request, slug):
    """HTMX action: set a venue's verification status, return the status partial."""
    venue = get_object_or_404(Venue, slug=slug)
    status = request.POST.get("status", "").strip()
    if status not in Venue.VerificationStatus.values:
        return HttpResponseBadRequest("Invalid status.")
    venue.verification_status = status
    venue.save(update_fields=["verification_status", "updated_at"])
    return render(
        request,
        "events/review/_status_control.html",
        {"venue": venue, "status_choices": Venue.VerificationStatus.choices},
    )


# ---------------------------------------------------------------------------
# JSON API endpoints — consumed by the SvelteKit frontend dashboard.
# ---------------------------------------------------------------------------


def api_stats(request):
    total_events = Event.objects.count()
    total_venues = Venue.objects.count()
    verified_venues = Venue.objects.filter(
        verification_status=Venue.VerificationStatus.VERIFIED
    ).count()
    total_organizers = Organizer.objects.count()
    confirmed_organizers = Organizer.objects.filter(status="confirmed").count()
    pending_organizers = Organizer.objects.filter(status="pending").count()
    active_sources = (
        Event.objects.exclude(source="").values("source").distinct().count()
    )
    return JsonResponse(
        {
            "total_events": total_events,
            "total_venues": total_venues,
            "verified_venues": verified_venues,
            "total_organizers": total_organizers,
            "confirmed_organizers": confirmed_organizers,
            "pending_organizers": pending_organizers,
            "active_sources": active_sources,
        }
    )


def api_events_by_source(request):
    data = list(
        Event.objects.exclude(source="")
        .values("source")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    return JsonResponse(data, safe=False)


def api_events_by_category(request):
    # Prefer the AI-assigned agent_categories. Events not yet classified
    # (agent_categories == []) gracefully fall back to the rule-based
    # normalize_category() so the donut chart stays meaningful during backfill.
    # The stored Event.category is never changed.
    from collections import Counter

    TOP_N = 8
    buckets: Counter = Counter()

    # Events with agent_categories populated — unnest each event's list.
    for e in Event.objects.exclude(agent_categories=[]).only("agent_categories"):
        for label in e.agent_categories:
            if label:
                buckets[label] += 1

    # Fallback: events without agent_categories — use the rule-based normalizer.
    for row in (
        Event.objects.filter(agent_categories=[])
        .exclude(category="")
        .values("category")
        .annotate(count=Count("id"))
    ):
        canonical = normalize_category(row["category"])
        if canonical:
            buckets[canonical] += row["count"]

    # Sort by count desc, then name asc so equal counts order deterministically
    # (otherwise which categories land in "Other" can vary between requests).
    ordered = sorted(buckets.items(), key=lambda item: (-item[1], item[0]))

    data = [{"category": name, "count": count} for name, count in ordered[:TOP_N]]
    other = sum(count for _, count in ordered[TOP_N:])
    if other > 0:
        data.append({"category": "Other", "count": other})

    return JsonResponse(data, safe=False)


def api_agent_categories(request):
    """Return all distinct agent_categories values sorted alphabetically."""
    cats: set[str] = set()
    for row in Event.objects.exclude(agent_categories=[]).values_list("agent_categories", flat=True):
        for label in row:
            if label:
                cats.add(label)
    return JsonResponse(sorted(cats), safe=False)


def api_events(request):
    q = request.GET.get("q", "").strip()
    source = request.GET.get("source", "").strip()
    category = request.GET.get("category", "").strip()
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1
    upcoming = request.GET.get("upcoming", "").strip()
    ordering = request.GET.get("ordering", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    events = Event.objects.select_related("venue", "organizer_ref")
    if q:
        events = events.filter(
            Q(name__icontains=q) | Q(description__icontains=q)
        )
    if source:
        events = events.filter(source=source)
    if category:
        events = events.filter(agent_categories__contains=[category])
    if upcoming == "1":
        events = events.filter(starts_at__gte=timezone.now())
    if date_from:
        events = events.filter(starts_at__date__gte=date_from)
    if date_to:
        events = events.filter(starts_at__date__lte=date_to)

    _order_map = {
        "name": ["name"],
        "-name": ["-name"],
        "starts_at": ["starts_at", "name"],
        "-starts_at": ["-starts_at", "name"],
    }
    events = events.order_by(*_order_map.get(ordering, ["-scraped_at", "name"]))

    paginator = Paginator(events, 50)
    page_obj = paginator.get_page(page)

    results = [
        {
            "slug": e.slug,
            "name": e.name,
            "starts_at": e.starts_at.isoformat() if e.starts_at else None,
            "ends_at": e.ends_at.isoformat() if e.ends_at else None,
            "category": e.category,
            "agent_categories": e.agent_categories,
            "source": e.source,
            "price": e.price,
            "venue": e.venue.name if e.venue else None,
            "venue_slug": e.venue.slug if e.venue else None,
            "organizer": e.organizer_display_name,
            "organizer_slug": e.organizer_ref.slug if e.organizer_ref_id else None,
            "url": e.url,
            "image_url": e.image_url or "",
        }
        for e in page_obj
    ]

    return JsonResponse(
        {"results": results, "total": paginator.count, "pages": paginator.num_pages, "page": page}
    )


def api_organizers(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1

    organizers = Organizer.objects.all()
    if q:
        organizers = organizers.filter(
            Q(name__icontains=q) | Q(city__icontains=q) | Q(email__icontains=q)
        )
    if status:
        organizers = organizers.filter(status=status)
    organizers = organizers.order_by("name")

    paginator = Paginator(organizers, 50)
    page_obj = paginator.get_page(page)

    results = [
        {
            "slug": o.slug,
            "name": o.name,
            "status": o.status,
            "email": o.email,
            "phone": o.phone,
            "website": o.website,
            "city": o.city,
            "country": o.country,
            "facebook_url": o.facebook_url,
            "instagram_url": o.instagram_url,
            "description": o.description,
            "source": o.source,
            "scraped_at": o.scraped_at.isoformat() if o.scraped_at else None,
        }
        for o in page_obj
    ]

    return JsonResponse(
        {"results": results, "total": paginator.count, "pages": paginator.num_pages, "page": page}
    )


def api_organizers_export(request):
    """Export all organizers matching the current filters as a CSV download.

    Uses the same q + status filter logic as api_organizers but with no
    pagination — every matching row is written. Status is rendered with the
    human-readable display label, and datetimes use ISO 8601 strings.
    """
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    organizers = Organizer.objects.all()
    if q:
        organizers = organizers.filter(
            Q(name__icontains=q) | Q(city__icontains=q) | Q(email__icontains=q)
        )
    if status:
        organizers = organizers.filter(status=status)
    organizers = organizers.order_by("name")

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="organizers.csv"'

    writer = csv.writer(response)
    writer.writerow(
        [
            "Name",
            "Email",
            "Phone",
            "Website",
            "Address",
            "City",
            "Country",
            "Facebook",
            "Instagram",
            "Source",
        ]
    )
    for o in organizers:
        writer.writerow(
            [
                o.name,
                o.email,
                o.phone,
                o.website,
                o.address,
                o.city,
                o.country,
                o.facebook_url,
                o.instagram_url,
                o.source,
            ]
        )

    return response


@csrf_exempt
def api_organizer_detail(request, slug):
    import json as _json
    organizer = get_object_or_404(Organizer, slug=slug)

    if request.method == "PATCH":
        try:
            body = _json.loads(request.body)
        except ValueError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        new_status = body.get("status", "").strip()
        valid = {Organizer.STATUS_PENDING, Organizer.STATUS_CONFIRMED, Organizer.STATUS_REJECTED}
        if new_status not in valid:
            return JsonResponse({"error": "Invalid status"}, status=400)
        organizer.status = new_status
        organizer.save(update_fields=["status"])
        return JsonResponse({"slug": organizer.slug, "status": organizer.status})

    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    events = list(
        organizer.events.select_related("venue").order_by("-starts_at")[:50]
    )
    return JsonResponse(
        {
            "slug": organizer.slug,
            "name": organizer.name,
            "status": organizer.status,
            "email": organizer.email,
            "phone": organizer.phone,
            "website": organizer.website,
            "address": organizer.address,
            "city": organizer.city,
            "country": organizer.country,
            "facebook_url": organizer.facebook_url,
            "instagram_url": organizer.instagram_url,
            "description": organizer.description,
            "source": organizer.source,
            "source_url": organizer.source_url,
            "scraped_at": organizer.scraped_at.isoformat() if organizer.scraped_at else None,
            "events": [
                {
                    "slug": e.slug,
                    "name": e.name,
                    "starts_at": e.starts_at.isoformat() if e.starts_at else None,
                    "category": e.category,
                    "venue": e.venue.name if e.venue else None,
                }
                for e in events
            ],
        }
    )


def api_venue_detail(request, slug):
    venue = get_object_or_404(Venue, slug=slug)
    events = list(venue.events.select_related("organizer_ref").order_by("-starts_at")[:50])
    return JsonResponse(
        {
            "slug": venue.slug,
            "name": venue.name,
            "address": venue.address,
            "city": venue.city,
            "country": venue.country,
            "website": venue.website,
            "rating": venue.rating,
            "about": venue.about,
            "primary_type_display": venue.primary_type_display,
            "agents_primary_types": venue.agents_primary_types,
            "verification_status": venue.verification_status,
            "source": venue.source,
            "source_url": venue.source_url,
            "scraped_at": venue.scraped_at.isoformat() if venue.scraped_at else None,
            "events": [
                {
                    "slug": e.slug,
                    "name": e.name,
                    "starts_at": e.starts_at.isoformat() if e.starts_at else None,
                    "category": e.category,
                    "organizer": e.organizer_display_name,
                }
                for e in events
            ],
        }
    )


def api_venue_types(request):
    types = list(
        Venue.objects.exclude(primary_type_display="")
        .values_list("primary_type_display", flat=True)
        .distinct()
        .order_by("primary_type_display")
    )
    return JsonResponse(types, safe=False)


def api_venues(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1
    venue_type = request.GET.get("type", "").strip()
    ordering = request.GET.get("ordering", "").strip()

    venues = Venue.objects.annotate(event_count=Count("events"))
    if q:
        venues = venues.filter(Q(name__icontains=q) | Q(city__icontains=q))
    if status:
        venues = venues.filter(verification_status=status)
    if venue_type:
        venues = venues.filter(primary_type_display=venue_type)

    _order_map = {
        "name": ["name"],
        "-name": ["-name"],
        "city": ["city", "name"],
        "-city": ["-city", "name"],
        "rating": ["rating", "name"],
        "-rating": ["-rating", "name"],
        "event_count": ["event_count", "name"],
        "-event_count": ["-event_count", "name"],
    }
    venues = venues.order_by(*_order_map.get(ordering, ["name"]))

    paginator = Paginator(venues, 50)
    page_obj = paginator.get_page(page)

    results = [
        {
            "slug": v.slug,
            "name": v.name,
            "city": v.city,
            "country": v.country,
            "primary_type_display": v.primary_type_display,
            "agents_primary_types": v.agents_primary_types,
            "rating": v.rating,
            "verification_status": v.verification_status,
            "event_count": v.event_count,
            "source": v.source,
        }
        for v in page_obj
    ]

    return JsonResponse(
        {"results": results, "total": paginator.count, "pages": paginator.num_pages, "page": page}
    )


def api_venues_map(request):
    pins = (
        Venue.objects.filter(latitude__isnull=False, longitude__isnull=False)
        .annotate(event_count=Count("events"))
        .values(
            "slug", "name", "address", "city", "country",
            "primary_type_display", "agents_primary_types",
            "rating", "latitude", "longitude",
            "verification_status", "website", "event_count",
        )
    )
    return JsonResponse(list(pins), safe=False)


# ---------------------------------------------------------------------------
# Scraper run jobs — trigger runs from the UI and poll/list their status.
# All endpoints are staff-only, mirroring the /review/ convention.
# ---------------------------------------------------------------------------


def _serialize_run(run):
    """Serialise a ScraperRun to the standard dict shape used by all run endpoints."""
    include_log = run.status in ('queued', 'running') or (
        run.finished_at is not None
        and (timezone.now() - run.finished_at).total_seconds() < 300
    )
    return {
        "id": run.id,
        "scraper_key": run.scraper_key,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "created_count": run.created_count,
        "updated_count": run.updated_count,
        "extra_counts": run.extra_counts,
        "error_message": run.error_message or None,
        "triggered_by": run.triggered_by.username if run.triggered_by_id else None,
        "created_at": run.created_at.isoformat(),
        "duration_seconds": run.duration_seconds,
        "log_output": run.log_output if include_log else None,
    }


@csrf_exempt
def api_proxy_setting(request):
    """GET current proxy-enabled state; POST to toggle it.

    GET  → {"enabled": bool}
    POST → {"enabled": bool}  (body)  → {"enabled": bool}
    """
    from .scrapers.proxy_manager import get_proxy_enabled, set_proxy_enabled

    if request.method == "GET":
        return JsonResponse({"enabled": get_proxy_enabled()})

    if request.method == "POST":
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        if "enabled" not in body:
            return JsonResponse({"error": "Missing 'enabled' field"}, status=400)
        if not isinstance(body["enabled"], bool):
            return JsonResponse({"error": "'enabled' must be a JSON boolean"}, status=400)
        set_proxy_enabled(body["enabled"])
        return JsonResponse({"enabled": get_proxy_enabled()})

    return JsonResponse({"error": "Method not allowed"}, status=405)


@csrf_exempt
@require_POST
def api_scraper_trigger(request, key):
    # SECURITY NOTE: This endpoint is unauthenticated intentionally. The
    # SvelteKit frontend has no Django session (the "Admin User" in the sidebar
    # is static UI, not a real session), and the Vite proxy makes all /api/*
    # calls same-origin in dev, so there is no CSRF surface from a browser
    # cross-site attack on this internal-only tool. @csrf_exempt is consistent
    # with all other JSON API endpoints in this file. Re-evaluate when real
    # auth is added (Phase 2 roadmap).
    from .scrapers import SCRAPERS

    if key not in SCRAPERS:
        return JsonResponse({"error": "Unknown scraper key"}, status=404)

    body = {}
    if request.body and "application/json" in request.content_type:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON"}, status=400)
    query_ids = body.get("query_ids")
    if query_ids is not None and not (
        isinstance(query_ids, list) and all(isinstance(i, int) for i in query_ids)
    ):
        return JsonResponse(
            {"error": "query_ids must be a list of integers"}, status=400
        )
    if isinstance(query_ids, list) and len(query_ids) == 0:
        return JsonResponse({"error": "query_ids must not be empty"}, status=400)

    locations = body.get("locations")
    if locations is not None:
        if not isinstance(locations, list) or not all(isinstance(l, str) for l in locations):
            return JsonResponse({"error": "locations must be a list of strings"}, status=400)
        if len(locations) == 0:
            return JsonResponse({"error": "locations must not be empty"}, status=400)
        unknown = [l for l in locations if l not in AVAILABLE_LOCATIONS]
        if unknown:
            return JsonResponse({"error": f"Unknown location: '{unknown[0]}'"}, status=400)

    scraper_cls = SCRAPERS[key]
    if (query_ids or locations) and not getattr(scraper_cls, "supports_keywords", False):
        return JsonResponse(
            {"error": f"Scraper '{key}' does not support keyword/location targeting"},
            status=400,
        )

    triggered_by = request.user if request.user.is_authenticated else None
    run, already_active = trigger_scraper_run(
        key, triggered_by=triggered_by, query_ids=query_ids, locations=locations
    )
    if already_active:
        return JsonResponse({"error": "Scraper already running"}, status=409)

    return JsonResponse({"id": run.id, "status": run.status}, status=200)


@csrf_exempt
@require_POST
def api_scraper_run_all(request):
    # SECURITY NOTE: Same posture as api_scraper_trigger above — unauthenticated
    # intentionally for the same reasons. Revisit when real auth is added.
    from .scrapers import SCRAPERS

    triggered_by = request.user if request.user.is_authenticated else None
    created = []
    skipped = []
    for key in SCRAPERS:
        run, already_active = trigger_scraper_run(key, triggered_by=triggered_by)
        if already_active:
            skipped.append(key)
        else:
            created.append({"key": key, "id": run.id, "status": run.status})

    return JsonResponse({"created": created, "skipped": skipped}, status=200)


@csrf_exempt
@require_POST
def api_dedup_trigger(request):
    # SECURITY NOTE: Intentionally unauthenticated — same posture as
    # api_scraper_trigger. This is an internal admin tool; revisit when real
    # auth is added to the frontend.
    import subprocess
    import sys
    from pathlib import Path

    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    python = sys.executable

    entity = request.POST.get("entity") or "all"  # default: all
    if entity not in ("events", "venues", "organizers", "all"):
        return JsonResponse({"error": "Invalid entity"}, status=400)

    if not _DEDUP_LOCK.acquire(blocking=False):
        return JsonResponse({"error": "Dedup already running"}, status=409)

    try:
        result = subprocess.run(
            [python, str(scripts_dir / "deduplicate.py"), "--entity", entity],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(scripts_dir.parent),  # apps/backend
        )
        stdout = result.stdout.strip()
        if result.returncode != 0:
            logger.error("dedup script failed (entity=%s): %s", entity, result.stderr.strip())
            return JsonResponse({"error": "Dedup operation failed"}, status=500)
        return JsonResponse({"output": stdout, "entity": entity})
    except subprocess.TimeoutExpired:
        return JsonResponse({"error": "Dedup timed out after 120s"}, status=504)
    except Exception as exc:  # noqa: BLE001
        logger.exception("dedup trigger error (entity=%s): %s", entity, exc)
        return JsonResponse({"error": "An error occurred"}, status=500)
    finally:
        _DEDUP_LOCK.release()


_ALLOWED_SCRIPTS = {
    "categorize-events": "categorize-neon-events.py",
    "classify-venues": "classify-neon-venues.py",
}


@csrf_exempt
@require_POST
def api_script_trigger(request, script_name: str):
    """Fire-and-forget trigger for long-running AI scripts in scripts/.

    Returns immediately with {"started": true, "pid": <pid>}. The script runs
    in a detached OS process — check server logs for output.

    SECURITY NOTE: Intentionally unauthenticated — same posture as
    api_scraper_trigger. This is an internal admin tool; revisit when real
    auth is added to the frontend.
    """
    import subprocess
    import sys
    from pathlib import Path

    if script_name not in _ALLOWED_SCRIPTS:
        return JsonResponse({"error": f"Unknown script: {script_name}"}, status=400)

    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    python = sys.executable
    script_file = scripts_dir / _ALLOWED_SCRIPTS[script_name]

    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        process = subprocess.Popen(
            [python, str(script_file)],
            cwd=str(scripts_dir.parent),
            start_new_session=True,
            env=env,
        )
        return JsonResponse({"started": True, "script": script_name, "pid": process.pid})
    except Exception as exc:  # noqa: BLE001
        logger.exception("script trigger error (script=%s): %s", script_name, exc)
        return JsonResponse({"error": "Failed to start script"}, status=500)


def api_scraper_runs(request):
    try:
        limit = max(1, min(int(request.GET.get("limit", 50)), 200))
    except ValueError:
        limit = 50
    runs = (
        ScraperRun.objects.select_related("triggered_by")
        .order_by("-created_at")[:limit]
    )
    return JsonResponse([_serialize_run(r) for r in runs], safe=False)


def api_scraper_runs_active(request):
    runs = ScraperRun.objects.filter(
        status__in=[ScraperRun.Status.QUEUED, ScraperRun.Status.RUNNING]
    ).select_related("triggered_by")
    return JsonResponse([_serialize_run(r) for r in runs], safe=False)


def api_scraper_run_detail(request, run_id):
    run = get_object_or_404(
        ScraperRun.objects.select_related("triggered_by"), id=run_id
    )
    return JsonResponse(_serialize_run(run))


@csrf_exempt
@require_POST
def api_scraper_run_cancel(request, run_id):
    # SECURITY NOTE: same posture as api_scraper_trigger — unauthenticated
    # intentionally (no Django session from SvelteKit). Re-evaluate when real
    # auth is added.
    run, signal = cancel_run(run_id)
    if signal == "not_found":
        return JsonResponse({"error": "Run not found"}, status=404)
    if signal == "not_active":
        return JsonResponse(
            {"error": "Run is not active", "run": _serialize_run(run)}, status=409
        )
    return JsonResponse(_serialize_run(run), status=200)


def api_scrapers(request):
    from .scrapers import SCRAPERS

    event_last = {
        row["source"]: row["last"]
        for row in Event.objects.values("source").annotate(last=Max("scraped_at"))
        if row["source"]
    }
    org_last = {
        row["source"]: row["last"]
        for row in Organizer.objects.values("source").annotate(last=Max("scraped_at"))
        if row["source"]
    }

    # Latest ScraperRun per key in a single query. Postgres DISTINCT ON
    # (scraper_key) with a matching order_by returns the most recent run for
    # each key, avoiding an N+1 across SCRAPERS.
    latest_runs = {
        run.scraper_key: run
        for run in ScraperRun.objects.order_by(
            "scraper_key", "-created_at"
        ).distinct("scraper_key")
    }

    results = []
    for key in SCRAPERS:
        e_ts = event_last.get(key)
        o_ts = org_last.get(key)
        if e_ts and o_ts:
            last_scraped = max(e_ts, o_ts)
        else:
            last_scraped = e_ts or o_ts

        run = latest_runs.get(key)
        last_run = (
            {
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            }
            if run
            else None
        )

        results.append(
            {
                "key": key,
                "last_scraped": last_scraped.isoformat() if last_scraped else None,
                "last_run": last_run,
                "supports_keywords": getattr(
                    SCRAPERS[key], "supports_keywords", False
                ),
            }
        )

    return JsonResponse(results, safe=False)


# ---------------------------------------------------------------------------
# Search Queries API — CRUD for the SearchQuery table used by the
# facebook_events scraper (and any future query-driven scrapers).
# ---------------------------------------------------------------------------


def _serialize_search_query(sq) -> dict:
    return {
        "id": sq.id,
        "query": sq.query,
        "source": sq.source,
        "is_active": sq.is_active,
        "last_run_at": sq.last_run_at.isoformat() if sq.last_run_at else None,
        "events_found_count": sq.events_found_count,
        "created_at": sq.created_at.isoformat(),
        "updated_at": sq.updated_at.isoformat(),
    }


@csrf_exempt
def api_search_queries(request):
    """GET list / POST create search queries."""
    if request.method == "GET":
        source = request.GET.get("source", "").strip()
        qs = SearchQuery.objects.all()
        if source:
            qs = qs.filter(source=source)
        return JsonResponse([_serialize_search_query(sq) for sq in qs], safe=False)

    if request.method == "POST":
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        query = (data.get("query") or "").strip()
        source = (data.get("source") or "").strip()
        if not query:
            return JsonResponse({"error": "query is required"}, status=400)

        sq, created = SearchQuery.objects.get_or_create(
            query=query,
            defaults={"is_active": data.get("is_active", True), "source": source},
        )
        if not created:
            return JsonResponse({"error": "Query already exists"}, status=409)

        return JsonResponse(_serialize_search_query(sq), status=201)

    return JsonResponse({"error": "Method not allowed"}, status=405)


@csrf_exempt
@require_POST
def api_search_query_run(request, pk):
    """Trigger a single SearchQuery through its scraper.

    Creates a ScraperRun with key ``"{source}:q:{pk}"`` so it can be tracked,
    cancelled, and polled by the same run-history UI used for full scraper runs.
    Returns 409 if a run for this query is already active.
    """
    sq = get_object_or_404(SearchQuery, pk=pk)
    triggered_by = request.user if request.user.is_authenticated else None
    # Rows created without a source default to the only query-capable scraper
    # today (facebook_events). When other scrapers opt in, they will set source
    # on creation or a richer lookup will be added.
    scraper_key = sq.source or "facebook_events"
    run, already_active = trigger_scraper_run(
        scraper_key, triggered_by=triggered_by, query_id=sq.pk
    )
    if already_active:
        return JsonResponse({"error": "This query is already running"}, status=409)
    return JsonResponse({"id": run.id, "status": run.status, "scraper_key": run.scraper_key})


@csrf_exempt
def api_search_query_detail(request, pk):
    """PATCH update / DELETE a single search query."""
    sq = get_object_or_404(SearchQuery, pk=pk)

    if request.method == "PATCH":
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        changed = []
        if "query" in data:
            sq.query = (data["query"] or "").strip()
            changed.append("query")
        if "is_active" in data:
            sq.is_active = bool(data["is_active"])
            changed.append("is_active")
        if "source" in data:
            sq.source = (data["source"] or "").strip()
            changed.append("source")

        if changed:
            sq.save(update_fields=[*changed, "updated_at"])

        return JsonResponse(_serialize_search_query(sq))

    if request.method == "DELETE":
        sq.delete()
        return JsonResponse({"deleted": True})

    return JsonResponse({"error": "Method not allowed"}, status=405)


# ---------------------------------------------------------------------------
# n8n automation webhooks — secured by X-Scraper-Key header.
# Set SCRAPER_WEBHOOK_SECRET in .env to enable.
# ---------------------------------------------------------------------------

_WEBHOOK_SECRET = os.environ.get("SCRAPER_WEBHOOK_SECRET", "")
# Process-local lock — prevents concurrent dedup runs within one worker but
# does NOT protect across multiple gunicorn workers. Acceptable for this
# internal single-worker dev/staging setup; upgrade to a DB advisory lock or
# Redis lock if moving to multi-worker production.
_DEDUP_LOCK = threading.Lock()


@csrf_exempt
@require_POST
def scraper_webhook(request):
    """Run a single registered scraper source on demand, called by n8n."""
    key = request.headers.get("X-Scraper-Key", "")
    if not _WEBHOOK_SECRET or key != _WEBHOOK_SECRET:
        return JsonResponse({"error": "unauthorized"}, status=401)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    source = (data.get("source") or "").strip()
    if not source:
        return JsonResponse({"error": "source is required"}, status=400)

    from events.scrapers import SCRAPERS  # noqa: PLC0415

    if source not in SCRAPERS:
        return JsonResponse(
            {"error": f"unknown source: {source}", "available": sorted(SCRAPERS)},
            status=400,
        )

    try:
        result = SCRAPERS[source]().run()
        return JsonResponse({"success": True, **result})
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"success": False, "source": source, "error": str(exc)}, status=500)


@csrf_exempt
@require_POST
def ingest_events_webhook(request):
    """Accept AI-extracted event arrays from n8n and persist via save_events."""
    key = request.headers.get("X-Scraper-Key", "")
    if not _WEBHOOK_SECRET or key != _WEBHOOK_SECRET:
        return JsonResponse({"error": "unauthorized"}, status=401)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    source = (data.get("source") or "").strip()
    if not source:
        return JsonResponse({"error": "source is required"}, status=400)

    events_data = data.get("events") or []
    if not isinstance(events_data, list):
        return JsonResponse({"error": "events must be an array"}, status=400)

    from datetime import datetime

    from events.scrapers.base import ScrapedEvent, ScrapedVenue, save_events  # noqa: PLC0415

    scraped_events = []
    for ev in events_data:
        if not isinstance(ev, dict):
            continue

        starts_at = ends_at = None
        for key_dt, attr in (("starts_at", "starts_at"), ("ends_at", "ends_at")):
            raw = (ev.get(key_dt) or "").strip()
            if raw:
                try:
                    dt = datetime.fromisoformat(raw)
                    if attr == "starts_at":
                        starts_at = timezone.make_aware(dt) if dt.tzinfo is None else dt
                    else:
                        ends_at = timezone.make_aware(dt) if dt.tzinfo is None else dt
                except (ValueError, TypeError):
                    pass

        venue = None
        location = (ev.get("location") or "").strip()
        if location:
            venue = ScrapedVenue(name=location)

        event_url = (ev.get("url") or "").strip()
        scraped_events.append(
            ScrapedEvent(
                name=(ev.get("name") or "").strip(),
                description=(ev.get("description") or "").strip(),
                url=event_url,
                price=(ev.get("price") or "").strip(),
                organizer=(ev.get("organizer") or "").strip(),
                starts_at=starts_at,
                ends_at=ends_at,
                source_url=event_url,
                external_id=(ev.get("external_id") or event_url).strip(),
                venue=venue,
            )
        )

    result = save_events(source, scraped_events)
    return JsonResponse({"success": True, **result})


# ---------------------------------------------------------------------------
# Tracker notes — lightweight note attached to one event or organizer.
# ---------------------------------------------------------------------------

def _serialize_note(note):
    return {
        "id": note.id,
        "content": note.content,
        "updated_at": note.updated_at.isoformat(),
        "event_slug": note.event.slug if note.event_id else None,
        "organizer_slug": note.organizer.slug if note.organizer_id else None,
    }


@csrf_exempt
def api_tracker_notes(request):
    if request.method == "GET":
        notes = TrackerNote.objects.select_related("event", "organizer").all()
        return JsonResponse([_serialize_note(n) for n in notes], safe=False)

    if request.method == "POST":
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        entity_type = (data.get("entity_type") or "").strip()
        entity_slug = (data.get("entity_slug") or "").strip()
        content = (data.get("content") or "").strip()

        if entity_type not in ("event", "organizer") or not entity_slug:
            return JsonResponse({"error": "entity_type and entity_slug required"}, status=400)

        if entity_type == "event":
            entity = get_object_or_404(Event, slug=entity_slug)
            note, created = TrackerNote.objects.update_or_create(
                event=entity,
                defaults={"content": content, "organizer": None},
            )
        else:
            entity = get_object_or_404(Organizer, slug=entity_slug)
            note, created = TrackerNote.objects.update_or_create(
                organizer=entity,
                defaults={"content": content, "event": None},
            )

        note.refresh_from_db()
        return JsonResponse(_serialize_note(note), status=201 if created else 200)

    return JsonResponse({"error": "Method not allowed"}, status=405)


@csrf_exempt
def api_tracker_note_detail(request, pk):
    note = get_object_or_404(TrackerNote.objects.select_related("event", "organizer"), pk=pk)

    if request.method == "PATCH":
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        note.content = (data.get("content") or "").strip()
        note.save(update_fields=["content", "updated_at"])
        return JsonResponse(_serialize_note(note))

    if request.method == "DELETE":
        note.delete()
        return JsonResponse({}, status=204)

    return JsonResponse({"error": "Method not allowed"}, status=405)
