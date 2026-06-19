from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("", views.event_list, name="event_list"),
    path("events/<slug:slug>/", views.event_detail, name="event_detail"),
    path("venues/", views.venue_list, name="venue_list"),
    path("venues/<slug:slug>/", views.venue_detail, name="venue_detail"),
    path("organizers/", views.organizer_list, name="organizer_list"),
    path("organizers/<slug:slug>/", views.organizer_detail, name="organizer_detail"),
    # Staff-only venue review UI
    path("review/", views.review_dashboard, name="review_dashboard"),
    path("review/venues/<slug:slug>/", views.review_venue_detail, name="review_venue_detail"),
    path("review/venues/<slug:slug>/status/", views.review_set_status, name="review_set_status"),
    # JSON API — consumed by the SvelteKit frontend
    path("api/stats/", views.api_stats, name="api_stats"),
    path("api/events/by-source/", views.api_events_by_source, name="api_events_by_source"),
    path("api/events/by-category/", views.api_events_by_category, name="api_events_by_category"),
    path("api/events/", views.api_events, name="api_events"),
    path("api/organizers/export/", views.api_organizers_export, name="api_organizers_export"),
    path("api/organizers/<slug:slug>/", views.api_organizer_detail, name="api_organizer_detail"),
    path("api/organizers/", views.api_organizers, name="api_organizers"),
    path("api/venues/types/", views.api_venue_types, name="api_venue_types"),
    path("api/venues/<slug:slug>/", views.api_venue_detail, name="api_venue_detail"),
    path("api/venues/", views.api_venues, name="api_venues"),
    path("api/settings/proxy/", views.api_proxy_setting, name="api_proxy_setting"),
    # Scraper run jobs — more-specific paths before the api/scrapers/ catch-all.
    path("api/scrapers/<str:key>/run/", views.api_scraper_trigger, name="api_scraper_trigger"),
    path("api/scrapers/dedup/", views.api_dedup_trigger, name="api_dedup_trigger"),
    path("api/scripts/<str:script_name>/run/", views.api_script_trigger, name="api_script_trigger"),
    path("api/scrapers/run-all/", views.api_scraper_run_all, name="api_scraper_run_all"),
    path("api/scrapers/runs/active/", views.api_scraper_runs_active, name="api_scraper_runs_active"),
    path("api/scrapers/runs/<int:run_id>/cancel/", views.api_scraper_run_cancel, name="api_scraper_run_cancel"),
    path("api/scrapers/runs/<int:run_id>/", views.api_scraper_run_detail, name="api_scraper_run_detail"),
    path("api/scrapers/runs/", views.api_scraper_runs, name="api_scraper_runs"),
    path("api/scrapers/", views.api_scrapers, name="api_scrapers"),
    # n8n automation webhooks
    path("webhooks/scrape/", views.scraper_webhook, name="scraper_webhook"),
    path("webhooks/ingest-events/", views.ingest_events_webhook, name="ingest_events_webhook"),
]
