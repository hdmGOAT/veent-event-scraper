from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q
from django.db.models.functions import TruncMinute
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Event, Organizer, Venue

# Human-friendly labels for scraper source keys, used across the dashboard.
SOURCE_LABELS = {
    "google_places": "Google Places",
    "allevents_cdo": "AllEvents CDO",
    "happeningnext_cdo": "HappeningNext CDO",
    "racemeister_partners": "Racemeister",
    "racemeister_events": "Racemeister",
    "myruntime": "MyRuntime",
}

# Donut slice colors, reused in order for the "Events by Category" chart.
CATEGORY_COLORS = ["#5ec8e0", "#9b8cff", "#4fd1a5", "#e6a04f", "#e878b0", "#6c8cff", "#f06d6d"]


def _source_label(key):
    """Prettify a scraper source key for display."""
    if not key:
        return "Unknown"
    return SOURCE_LABELS.get(key, key.replace("_", " ").title())


def dashboard(request):
    """Platform overview: live KPIs, source/category breakdowns, recent activity.

    All metrics here are derived from the current database. A few panels in the
    design (System Health services, per-job durations) have no backing telemetry
    yet, so the template renders those as static illustrative values.
    """
    today = timezone.localdate()
    total_events = Event.objects.count()
    new_today = Event.objects.filter(scraped_at__date=today).count()

    # Active sources = distinct non-empty source keys present in events.
    active_sources = Event.objects.exclude(source="").values("source").distinct().count()

    # Duplicate approximation: no cross-source dedup engine exists yet, so we
    # surface exact-name overlap (records sharing a name beyond the first).
    distinct_names = Event.objects.values("name").distinct().count()
    duplicates = max(total_events - distinct_names, 0)
    dup_groups = (
        Event.objects.values("name").annotate(n=Count("id")).filter(n__gt=1).count()
    )

    # Events by source (top 5) → bar chart.
    source_rows = list(
        Event.objects.exclude(source="")
        .values("source")
        .annotate(n=Count("id"))
        .order_by("-n")[:5]
    )
    max_source = max((r["n"] for r in source_rows), default=0)
    by_source = [
        {
            "label": _source_label(r["source"]),
            "count": r["n"],
            "height": round(r["n"] / max_source * 100) if max_source else 0,
        }
        for r in source_rows
    ]

    # Events by category (top 5) → donut segments with cumulative offsets.
    cat_rows = list(
        Event.objects.exclude(category="")
        .values("category")
        .annotate(n=Count("id"))
        .order_by("-n")[:5]
    )
    cat_total = sum(r["n"] for r in cat_rows) or 1
    by_category = []
    cumulative = 0.0
    for i, r in enumerate(cat_rows):
        pct = round(r["n"] / cat_total * 100, 1)
        by_category.append(
            {
                "label": r["category"],
                "count": r["n"],
                "pct": pct,
                "gap": round(100 - pct, 1),
                "color": CATEGORY_COLORS[i % len(CATEGORY_COLORS)],
                "offset": round(25 - cumulative, 1),
            }
        )
        cumulative += pct

    # Recent scraping activity — batches grouped by source + minute scraped.
    recent = list(
        Event.objects.exclude(scraped_at__isnull=True)
        .annotate(minute=TruncMinute("scraped_at"))
        .values("source", "minute")
        .annotate(n=Count("id"))
        .order_by("-minute")[:6]
    )
    recent_activity = [
        {
            "time": timezone.localtime(r["minute"]).strftime("%H:%M:%S"),
            "source": _source_label(r["source"]),
            "count": r["n"],
        }
        for r in recent
    ]

    context = {
        "total_events": total_events,
        "total_events_display": f"{total_events:,}",
        "new_today": new_today,
        "active_sources": active_sources,
        "duplicates": duplicates,
        "duplicates_display": f"{duplicates:,}",
        "dup_groups": dup_groups,
        "by_source": by_source,
        "by_category": by_category,
        "recent_activity": recent_activity,
        "venue_total": Venue.objects.count(),
        "organizer_total": Organizer.objects.count(),
        "now": timezone.localtime(),
    }
    return render(request, "events/dashboard.html", context)


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
    event = get_object_or_404(Event.objects.select_related("venue"), slug=slug)
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
