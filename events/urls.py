from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("", views.event_list, name="event_list"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("events/<slug:slug>/", views.event_detail, name="event_detail"),
    path("venues/", views.venue_list, name="venue_list"),
    path("venues/<slug:slug>/", views.venue_detail, name="venue_detail"),
    # Staff-only venue review UI
    path("review/", views.review_dashboard, name="review_dashboard"),
    path("review/venues/<slug:slug>/", views.review_venue_detail, name="review_venue_detail"),
    path("review/venues/<slug:slug>/status/", views.review_set_status, name="review_set_status"),
]
