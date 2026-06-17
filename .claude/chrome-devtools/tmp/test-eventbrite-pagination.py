"""
Test:
  1. How many pages does Manila have?
  2. Does ?page=2 work the same way?
  3. Can we call the internal API without session cookies?
  4. What do price + organizer look like in full card DOM?
"""
import requests, json, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EventScraper/1.0)"}

def get_events_from_page(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    soup = BeautifulSoup(resp.text, "lxml")

    # JSON-LD event list
    events = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
            items = None
            if isinstance(data, dict) and "itemListElement" in data:
                items = data["itemListElement"]
            elif isinstance(data, list):
                for entry in data:
                    if isinstance(entry, dict) and "itemListElement" in entry:
                        items = entry["itemListElement"]
                        break
            if items:
                events = [item.get("item", item) for item in items if "@type" in item.get("item", item)]
        except Exception:
            pass

    # Event IDs from DOM cards
    ids = []
    for a in soup.find_all("a", attrs={"data-event-id": True}):
        eid = a.get("data-event-id", "")
        if eid and eid not in ids:
            ids.append(eid)

    # Price from DOM — look at price spans
    prices = {}
    for a in soup.find_all("a", attrs={"data-event-id": True}):
        eid = a.get("data-event-id", "")
        status = a.get("data-event-paid-status", "")
        cat = a.get("data-event-category", "")
        prices[eid] = {"paid_status": status, "category": cat}

    # Also try getting price text from card
    for card in soup.find_all(class_="discover-search-desktop-card"):
        link = card.find("a", attrs={"data-event-id": True})
        if not link:
            continue
        eid = link.get("data-event-id", "")
        price_el = card.find(attrs={"data-testid": "event-card-price"})
        if not price_el:
            # fallback: any element containing price-like text
            for el in card.find_all(True):
                cls = " ".join(el.get("class", []))
                if "price" in cls.lower() or "ticket" in cls.lower():
                    price_el = el
                    break
        if price_el and eid:
            prices.setdefault(eid, {})["price_text"] = price_el.get_text(strip=True)

    # Check for organizer in card
    organizers = {}
    for card in soup.find_all(class_="discover-search-desktop-card"):
        link = card.find("a", attrs={"data-event-id": True})
        if not link:
            continue
        eid = link.get("data-event-id", "")
        for el in card.find_all(True):
            cls = " ".join(el.get("class", []))
            if "organizer" in cls.lower() or "host" in cls.lower():
                organizers[eid] = el.get_text(strip=True)
                break

    return events, ids, prices, organizers

# Test pages 1 and 2
print("=== PAGE 1 ===")
ev1, ids1, prices1, orgs1 = get_events_from_page(
    "https://www.eventbrite.com/d/philippines--manila/all-events/"
)
print(f"Events from JSON-LD: {len(ev1)}, IDs from DOM: {len(ids1)}")
if ids1:
    print("Sample prices dict:", json.dumps(dict(list(prices1.items())[:3]), indent=2))
    print("Organizers found:", len(orgs1))

print("\n=== PAGE 2 ===")
ev2, ids2, prices2, orgs2 = get_events_from_page(
    "https://www.eventbrite.com/d/philippines--manila/all-events/?page=2"
)
print(f"Events from JSON-LD: {len(ev2)}, IDs from DOM: {len(ids2)}")
overlap = set(ids1) & set(ids2)
print(f"Overlap between page 1 and 2: {len(overlap)}")

print("\n=== PAGE 3 ===")
ev3, ids3, prices3, orgs3 = get_events_from_page(
    "https://www.eventbrite.com/d/philippines--manila/all-events/?page=3"
)
print(f"Events from JSON-LD: {len(ev3)}, IDs from DOM: {len(ids3)}")

print("\n=== Internal API test (no session cookies) ===")
if ids1:
    api_url = (
        "https://www.eventbrite.com/api/v3/destination/events/"
        f"?event_ids={','.join(ids1[:3])}"
        "&page_size=3"
        "&expand=event_sales_status,image,primary_venue,ticket_availability,primary_organizer"
    )
    r = requests.get(api_url, headers=HEADERS, timeout=20)
    print("API status:", r.status_code)
    if r.status_code == 200:
        data = r.json()
        events_api = data.get("events", [])
        print(f"Events returned: {len(events_api)}")
        if events_api:
            ev = events_api[0]
            print("First event keys:", list(ev.keys()))
            org = ev.get("primary_organizer") or {}
            venue = ev.get("primary_venue") or {}
            tickets = ev.get("ticket_availability") or {}
            sales = ev.get("event_sales_status") or {}
            print("Organizer:", json.dumps(org, indent=2)[:600])
            print("Venue:", json.dumps(venue, indent=2)[:400])
            print("Ticket availability:", json.dumps(tickets, indent=2)[:400])
            print("Sales status:", json.dumps(sales, indent=2)[:300])
    else:
        print("Response:", r.text[:500])
