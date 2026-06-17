"""Test whether Ticket Tailor discover page is server-rendered and find API endpoints."""
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EventScraper/1.0)"}

# 1. Test if /discover page has event data in raw HTML
print("=== /discover page ===")
r = requests.get("https://www.tickettailor.com/discover", headers=HEADERS, timeout=20)
print(f"Status: {r.status_code}, Size: {len(r.text)} bytes")

soup = BeautifulSoup(r.text, "lxml")
# Look for event cards
cards = soup.find_all(attrs={"data-event-id": True})
print(f"data-event-id elements: {len(cards)}")

# Look for any event links
event_links = [a["href"] for a in soup.find_all("a", href=True) if "/events/" in a.get("href", "")]
print(f"Event links found: {len(event_links)}")
if event_links:
    for link in event_links[:5]:
        print(f"  {link}")

# Look for JSON data embedded in page
scripts = soup.find_all("script", type="application/json")
print(f"JSON script tags: {len(scripts)}")
for s in scripts[:3]:
    content = s.string or ""
    print(f"  JSON script length: {len(content)} chars, preview: {content[:200]}")

# Look for __NEXT_DATA__ or similar
next_data = soup.find("script", id="__NEXT_DATA__")
print(f"__NEXT_DATA__: {'found' if next_data else 'not found'}")
if next_data:
    import json
    data = json.loads(next_data.string)
    print(f"  Keys: {list(data.keys())}")

# 2. Test Philippines location filter
print("\n=== /discover with Philippines location ===")
for url in [
    "https://www.tickettailor.com/discover?location=Philippines",
    "https://www.tickettailor.com/discover?country=PH",
    "https://www.tickettailor.com/discover?q=philippines",
]:
    r2 = requests.get(url, headers=HEADERS, timeout=15)
    soup2 = BeautifulSoup(r2.text, "lxml")
    links2 = [a["href"] for a in soup2.find_all("a", href=True) if "/events/" in a.get("href", "")]
    print(f"  {url.split('?')[1]}: status={r2.status_code}, event_links={len(links2)}")

# 3. Test if there's a search/API endpoint
print("\n=== Search API test ===")
api_candidates = [
    "https://www.tickettailor.com/api/discover",
    "https://www.tickettailor.com/api/events",
    "https://www.tickettailor.com/discover.json",
    "https://www.tickettailor.com/api/v1/discover",
]
for api_url in api_candidates:
    try:
        ra = requests.get(api_url, headers={**HEADERS, "Accept": "application/json"}, timeout=10)
        print(f"  {api_url}: {ra.status_code}")
        if ra.status_code == 200:
            print(f"    Content-Type: {ra.headers.get('Content-Type')}")
            print(f"    Preview: {ra.text[:200]}")
    except Exception as e:
        print(f"  {api_url}: ERROR {e}")

# 4. Check a known PH box office URL pattern
print("\n=== Box office HTML check ===")
# Racemeister events often list on multiple platforms - check if they use ticket tailor
r3 = requests.get("https://www.tickettailor.com/events/racemeister", headers=HEADERS, timeout=15)
print(f"tickettailor.com/events/racemeister: {r3.status_code}")
if r3.status_code == 200:
    soup3 = BeautifulSoup(r3.text, "lxml")
    ev_links = [a["href"] for a in soup3.find_all("a", href=True) if "/events/" in a.get("href", "")]
    print(f"  Event links: {len(ev_links)}")

print("\nDone.")
