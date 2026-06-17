import sys, os
sys.path.insert(0, r"E:\OJT\Veent Apps Inc\SCRAPING\veent-event-scraper\apps\backend")
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
import django; django.setup()
from events.models import Event
evts = Event.objects.filter(source="ticketmelon").select_related("venue").order_by("starts_at")
for e in evts:
    v = e.venue.name if e.venue else "no venue"
    dt = e.starts_at.strftime("%Y-%m-%d") if e.starts_at else "?"
    print(f"  {dt} | {e.name[:55]} | {v[:28]}")
print(f"Total: {evts.count()}")
