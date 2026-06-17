"""Find Eventbee Angular API and count total PH events across search terms."""
import requests, re, sys
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://www.eventbee.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.eventbee.com/search",
    "Origin": "https://www.eventbee.com",
    "X-Requested-With": "XMLHttpRequest",
}

def search(term):
    r = requests.post(f"{BASE}/search!searchResult",
                      headers=HEADERS,
                      data={"searchcontent": term}, timeout=20)
    soup = BeautifulSoup(r.text, "lxml")
    rows = soup.select("tr.edata")
    events = []
    for row in rows:
        a = row.find("a", href=re.compile(r"\?eid=\d+"))
        img = row.find("img")
        date_p = row.find("p", class_="mb-1")
        venue_p = row.find("p", class_="mb-0")
        if not a:
            continue
        eid_m = re.search(r"eid=(\d+)", a["href"])
        events.append({
            "eid": eid_m.group(1) if eid_m else "",
            "name": a.get_text(strip=True),
            "url": a["href"],
            "date_raw": date_p.get_text(strip=True) if date_p else "",
            "venue_raw": venue_p.get_text(separator=" ", strip=True) if venue_p else "",
            "img": img["src"] if img else "",
        })
    return events

# Search all PH-related terms and deduplicate by eid
print("=== PH event search ===")
ph_terms = [
    "manila", "philippines", "cebu", "davao", "quezon", "makati",
    "taguig", "pasig", "antipolo", "caloocan", "manila philippines",
    "ph", "metro manila", "bgc", "ortigas"
]
seen_eids = set()
all_events = []
for term in ph_terms:
    evts = search(term)
    new = [e for e in evts if e["eid"] not in seen_eids]
    for e in new:
        seen_eids.add(e["eid"])
        all_events.append(e)
    print(f"  '{term}' -> {len(evts)} results ({len(new)} new)")

print(f"\nTotal unique PH events: {len(all_events)}")
for e in all_events:
    print(f"  [{e['eid']}] {e['name']}")
    print(f"    date: {e['date_raw']}")
    print(f"    venue: {e['venue_raw']}")
    print(f"    url: {e['url'][:70]}")
    print(f"    img: {e['img'][:60]}")

# Try Angular API endpoints for event detail
print("\n=== Angular API probe ===")
EID = "238729652"
SLUG = "cyber-revolution-summit-philippines"
JSON_H = {**HEADERS, "Accept": "application/json"}

for path in [
    f"/v/{SLUG}/event!getTickets?eid={EID}",
    f"/v/{SLUG}/event!getEventDetails?eid={EID}",
    f"/v/{SLUG}/event!getInfo?eid={EID}",
    f"/v/{SLUG}/event!getEventInfo?eid={EID}",
    f"/v/{SLUG}/event!getEventDetailsBySite?eid={EID}",
    f"/registration/getEventDetailsBySite?eid={EID}",
    f"/v/{SLUG}/event!getTktTypes?eid={EID}",
    f"/v/{SLUG}/event!eventInfo?eid={EID}",
    f"/registration/eventInfo?eid={EID}",
    f"/registration!eventInfo?eid={EID}",
    f"/api/events/{EID}",
    f"/event/getDetails?eid={EID}",
]:
    try:
        r = requests.get(f"{BASE}{path}", headers=JSON_H, timeout=10)
        ct = r.headers.get("Content-Type", "")
        try:
            j = r.json()
            print(f"  {r.status_code} JSON | {path[:60]}")
            print(f"    keys: {list(j.keys())[:8] if isinstance(j, dict) else type(j)}")
        except:
            print(f"  {r.status_code} HTML | {path[:60]} | {r.text[:80].strip()}")
    except Exception as ex:
        print(f"  ERR | {path[:50]} | {ex}")
