import json
import os

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Event, Organizer, Venue


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
# n8n automation webhook — triggered by n8n to run a scraper on demand.
# Secured by a shared secret in X-Scraper-Key header (set SCRAPER_WEBHOOK_SECRET).
# ---------------------------------------------------------------------------

_WEBHOOK_SECRET = os.environ.get("SCRAPER_WEBHOOK_SECRET", "")


@csrf_exempt
@require_POST
def scraper_webhook(request):
    """Run a single scraper source on demand, called by n8n."""
    key = request.headers.get("X-Scraper-Key", "")
    if not _WEBHOOK_SECRET or key != _WEBHOOK_SECRET:
        return JsonResponse({"error": "unauthorized"}, status=401)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    source = (data.get("source") or "").strip()
    if not source:
        return JsonResponse({"error": "source field is required"}, status=400)

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


# ---------------------------------------------------------------------------
# n8n AI ingest webhook — accepts pre-scraped event data from AI agents.
# Matches the same X-Scraper-Key auth as scraper_webhook.
# ---------------------------------------------------------------------------


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
