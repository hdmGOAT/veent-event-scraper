"""Check exact field formats from the internal API: datetime, image, organizer, price."""
import requests, json

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EventScraper/1.0)"}

# Get some IDs from page 1
from bs4 import BeautifulSoup
resp = requests.get(
    "https://www.eventbrite.com/d/philippines--manila/all-events/",
    headers=HEADERS, timeout=20
)
soup = BeautifulSoup(resp.text, "lxml")
ids = []
for a in soup.find_all("a", attrs={"data-event-id": True}):
    eid = a.get("data-event-id", "").strip()
    if eid and eid not in ids:
        ids.append(eid)

print(f"IDs found: {len(ids)}")

# Fetch full data for first 5
api_url = "https://www.eventbrite.com/api/v3/destination/events/"
r = requests.get(api_url, headers=HEADERS, params={
    "event_ids": ",".join(ids[:5]),
    "page_size": 5,
    "expand": "event_sales_status,image,primary_venue,ticket_availability,primary_organizer",
}, timeout=20)
print("API status:", r.status_code)

data = r.json()
events = data.get("events", [])
print(f"Events returned: {len(events)}\n")

for ev in events[:3]:
    print("=" * 60)
    print(f"name: {ev.get('name')}")
    print(f"eid: {ev.get('eid')}, id: {ev.get('id')}")
    print(f"start_date: {ev.get('start_date')}")
    print(f"start_time: {ev.get('start_time')}")
    print(f"end_date: {ev.get('end_date')}")
    print(f"end_time: {ev.get('end_time')}")
    print(f"timezone: {ev.get('timezone')}")
    print(f"url: {ev.get('url')}")
    print(f"is_online_event: {ev.get('is_online_event')}")
    print(f"summary: {str(ev.get('summary',''))[:120]}")
    print(f"tags: {ev.get('tags')}")

    # Image
    img = ev.get("image") or {}
    print(f"image.url: {img.get('url','')[:100]}")
    print(f"image.id: {img.get('id')}")

    # Venue
    venue = ev.get("primary_venue") or {}
    addr = venue.get("address") or {}
    print(f"venue.name: {venue.get('name')}")
    print(f"venue.address_1: {addr.get('address_1')}")
    print(f"venue.city: {addr.get('city')}")
    print(f"venue.region: {addr.get('region')}")
    print(f"venue.country: {addr.get('country')}")
    print(f"venue.latitude: {addr.get('latitude')}")
    print(f"venue.longitude: {addr.get('longitude')}")

    # Organizer
    org = ev.get("primary_organizer") or {}
    print(f"organizer.name: {org.get('name')}")
    print(f"organizer.id: {org.get('id')}")
    print(f"organizer.url: {org.get('url')}")
    print(f"organizer.website_url: {org.get('website_url')}")
    print(f"organizer.facebook: {org.get('facebook')}")
    print(f"organizer.twitter: {org.get('twitter')}")
    print(f"organizer.summary: {str(org.get('summary') or '')[:100]}")

    # Price
    ta = ev.get("ticket_availability") or {}
    print(f"ticket.is_free: {ta.get('is_free')}")
    min_p = ta.get("minimum_ticket_price") or {}
    max_p = ta.get("maximum_ticket_price") or {}
    print(f"ticket.min: {min_p.get('major_value')} {min_p.get('currency')}")
    print(f"ticket.max: {max_p.get('major_value')} {max_p.get('currency')}")
    print()
