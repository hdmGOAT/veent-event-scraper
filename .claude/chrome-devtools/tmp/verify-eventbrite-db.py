"""Verify Eventbrite events in DB match schema requirements."""
import os, sys, django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/../../../")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "apps.backend.config.settings")
django.setup()

from events.models import Event, Venue, Organizer

total = Event.objects.filter(source="eventbrite").count()
print(f"Total Eventbrite events: {total}")

# Field completeness
missing_url = Event.objects.filter(source="eventbrite", url="").count()
missing_img = Event.objects.filter(source="eventbrite", image_url="").count()
missing_start = Event.objects.filter(source="eventbrite", starts_at__isnull=True).count()
no_organizer = Event.objects.filter(source="eventbrite", organizer="").count()
no_org_ref = Event.objects.filter(source="eventbrite", organizer_ref__isnull=True).count()
no_venue = Event.objects.filter(source="eventbrite", venue__isnull=True).count()
has_price = Event.objects.filter(source="eventbrite").exclude(price="").count()
has_category = Event.objects.filter(source="eventbrite").exclude(category="").count()
tz_aware = Event.objects.filter(source="eventbrite", starts_at__isnull=False).count()

print(f"Missing url:         {missing_url}")
print(f"Missing image_url:   {missing_img}")
print(f"Missing starts_at:   {missing_start}")
print(f"Missing organizer:   {no_organizer}")
print(f"Missing organizer_ref: {no_org_ref}")
print(f"No venue (online/no addr): {no_venue}")
print(f"Events with price:   {has_price}/{total}")
print(f"Events with category:{has_category}/{total}")
print(f"Timezone-aware starts: {tz_aware}/{total - missing_start}")

orgs = Organizer.objects.filter(source="eventbrite").count()
venues = Venue.objects.filter(source="eventbrite").count()
print(f"\nOrganizers:          {orgs}")
print(f"Venues:              {venues}")

# Sample events
print("\n--- Sample events ---")
for ev in Event.objects.filter(source="eventbrite").order_by("starts_at")[:5]:
    print(f"  [{ev.price or 'no price'}] {ev.name[:50]} | {ev.starts_at} | cat={ev.category}")

# Price breakdown
free = Event.objects.filter(source="eventbrite", price="Free").count()
paid = Event.objects.filter(source="eventbrite").exclude(price__in=["", "Free"]).count()
no_price = Event.objects.filter(source="eventbrite", price="").count()
print(f"\nPrice breakdown: Free={free}, Paid={paid}, No price={no_price}")
