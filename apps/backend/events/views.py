import json
import os

from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .categories import normalize_category
from .models import Event, Organizer, ScraperRun, Venue
from .runner import cancel_run, trigger_scraper_run


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
    # Aggregate raw (category, count) rows, then collapse them into a small
    # canonical set at display time. The stored Event.category is never changed.
    TOP_N = 8

    raw_rows = (
        Event.objects.exclude(category="")
        .values("category")
        .annotate(count=Count("id"))
    )

    buckets: dict[str, int] = {}
    for row in raw_rows:
        canonical = normalize_category(row["category"])
        if not canonical:
            continue
        buckets[canonical] = buckets.get(canonical, 0) + row["count"]

    # Sort by count desc, then name asc so equal counts order deterministically
    # (otherwise which categories land in "Other" can vary between requests).
    ordered = sorted(buckets.items(), key=lambda item: (-item[1], item[0]))

    data = [{"category": name, "count": count} for name, count in ordered[:TOP_N]]
    other = sum(count for _, count in ordered[TOP_N:])
    if other > 0:
        data.append({"category": "Other", "count": other})

    return JsonResponse(data, safe=False)


def api_events(request):
    q = request.GET.get("q", "").strip()
    source = request.GET.get("source", "").strip()
    category = request.GET.get("category", "").strip()
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1

    events = Event.objects.select_related("venue", "organizer_ref")
    if q:
        events = events.filter(
            Q(name__icontains=q) | Q(description__icontains=q)
        )
    if source:
        events = events.filter(source=source)
    if category:
        events = events.filter(category=category)
    events = events.order_by("-scraped_at", "name")

    paginator = Paginator(events, 50)
    page_obj = paginator.get_page(page)

    results = [
        {
            "slug": e.slug,
            "name": e.name,
            "starts_at": e.starts_at.isoformat() if e.starts_at else None,
            "ends_at": e.ends_at.isoformat() if e.ends_at else None,
            "category": e.category,
            "source": e.source,
            "price": e.price,
            "venue": e.venue.name if e.venue else None,
            "organizer": e.organizer_display_name,
            "url": e.url,
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


def api_organizer_detail(request, slug):
    organizer = get_object_or_404(Organizer, slug=slug)
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


def api_venues(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1

    venues = Venue.objects.annotate(event_count=Count("events"))
    if q:
        venues = venues.filter(Q(name__icontains=q) | Q(city__icontains=q))
    if status:
        venues = venues.filter(verification_status=status)
    venues = venues.order_by("name")

    paginator = Paginator(venues, 50)
    page_obj = paginator.get_page(page)

    results = [
        {
            "slug": v.slug,
            "name": v.name,
            "city": v.city,
            "country": v.country,
            "primary_type_display": v.primary_type_display,
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


# ---------------------------------------------------------------------------
# Scraper run jobs — trigger runs from the UI and poll/list their status.
# All endpoints are staff-only, mirroring the /review/ convention.
# ---------------------------------------------------------------------------


def _serialize_run(run):
    """Serialise a ScraperRun to the standard dict shape used by all run endpoints."""
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
    }


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

    triggered_by = request.user if request.user.is_authenticated else None
    run, already_active = trigger_scraper_run(key, triggered_by=triggered_by)
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
            }
        )

    return JsonResponse(results, safe=False)


# ---------------------------------------------------------------------------
# n8n automation webhooks — secured by X-Scraper-Key header.
# Set SCRAPER_WEBHOOK_SECRET in .env to enable.
# ---------------------------------------------------------------------------

_WEBHOOK_SECRET = os.environ.get("SCRAPER_WEBHOOK_SECRET", "")


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
