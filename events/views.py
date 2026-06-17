from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
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
