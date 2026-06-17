"""Full DB audit — event counts, field coverage, and schema gaps per scraper."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"E:\OJT\Veent Apps Inc\SCRAPING\veent-event-scraper\apps\backend")
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
import django; django.setup()

from events.models import Event, Venue, Organizer
from django.db.models import Count, Q

FIELDS = [
    "name", "description", "starts_at", "ends_at",
    "url", "image_url", "price", "category",
    "organizer", "organizer_url", "external_id", "venue",
]

def pct(n, total):
    return f"{n}/{total} ({100*n//total if total else 0}%)"

print("=" * 70)
print("EVENTS BY SOURCE")
print("=" * 70)
sources = Event.objects.values("source").annotate(total=Count("id")).order_by("-total")
grand = Event.objects.count()
print(f"Total events in DB: {grand}\n")

for row in sources:
    src = row["source"]
    total = row["total"]
    qs = Event.objects.filter(source=src)
    filled = {}
    for f in FIELDS:
        if f == "venue":
            n = qs.filter(venue__isnull=False).count()
        elif f in ("description", "url", "image_url", "price", "category",
                   "organizer", "organizer_url", "external_id"):
            n = qs.exclude(**{f: ""}).exclude(**{f: None}).count()
        elif f in ("starts_at", "ends_at"):
            n = qs.filter(**{f"__{f}__isnull": False}).count() if False else qs.exclude(**{f"{f}__isnull": True}).count()
        else:
            n = total
        filled[f] = n

    missing = [f for f in FIELDS if filled[f] < total]
    print(f"[{src}]  {total} events")
    print(f"  name={pct(filled['name'],total)}  starts_at={pct(filled['starts_at'],total)}  ends_at={pct(filled['ends_at'],total)}")
    print(f"  description={pct(filled['description'],total)}  url={pct(filled['url'],total)}  image_url={pct(filled['image_url'],total)}")
    print(f"  price={pct(filled['price'],total)}  category={pct(filled['category'],total)}")
    print(f"  organizer={pct(filled['organizer'],total)}  organizer_url={pct(filled['organizer_url'],total)}")
    print(f"  external_id={pct(filled['external_id'],total)}  venue={pct(filled['venue'],total)}")
    if missing:
        print(f"  *** GAPS: {', '.join(missing)}")
    print()

print("=" * 70)
print("VENUES BY SOURCE")
print("=" * 70)
vsources = Venue.objects.values("source").annotate(total=Count("id")).order_by("-total")
vtotal = Venue.objects.count()
print(f"Total venues in DB: {vtotal}\n")
for row in vsources:
    src = row["source"]
    n = row["total"]
    vqs = Venue.objects.filter(source=src)
    lat_n = vqs.filter(latitude__isnull=False).count()
    print(f"  [{src}] {n} venues | lat/lon={pct(lat_n,n)}")

print()
print("=" * 70)
print("ORGANIZERS BY SOURCE")
print("=" * 70)
osources = Organizer.objects.values("source").annotate(total=Count("id")).order_by("-total")
ototal = Organizer.objects.count()
print(f"Total organizers in DB: {ototal}\n")
for row in osources:
    src = row["source"]
    n = row["total"]
    oqs = Organizer.objects.filter(source=src)
    pending = oqs.filter(status="pending").count()
    confirmed = oqs.filter(status="confirmed").count()
    rejected = oqs.filter(status="rejected").count()
    print(f"  [{src}] {n} organizers | pending={pending} confirmed={confirmed} rejected={rejected}")

print()
print("=" * 70)
print("SAMPLE — 3 most recent events per scraper")
print("=" * 70)
for row in sources:
    src = row["source"]
    evts = Event.objects.filter(source=src).order_by("-scraped_at")[:3]
    print(f"\n[{src}]")
    for e in evts:
        dt = e.starts_at.strftime("%Y-%m-%d") if e.starts_at else "no-date"
        v = e.venue.name[:25] if e.venue else "—"
        print(f"  {dt} | {e.name[:55]:<55} | venue={v}")
