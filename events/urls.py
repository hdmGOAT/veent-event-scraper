from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("", views.event_list, name="event_list"),
    path("events/<slug:slug>/", views.event_detail, name="event_detail"),
    path("venues/", views.venue_list, name="venue_list"),
    path("venues/<slug:slug>/", views.venue_detail, name="venue_detail"),
]
