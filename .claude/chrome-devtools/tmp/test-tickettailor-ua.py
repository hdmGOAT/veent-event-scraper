"""Test Ticket Tailor with browser-like User-Agent and session cookies."""
import requests
from bs4 import BeautifulSoup
import json

HEADERS_BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

session = requests.Session()
session.headers.update(HEADERS_BROWSER)

# 1. Test /discover with real browser headers
print("=== /discover with browser UA ===")
r = session.get("https://www.tickettailor.com/discover", timeout=20)
print(f"Status: {r.status_code}, Size: {len(r.text)}")

if r.status_code == 200:
    soup = BeautifulSoup(r.text, "lxml")
    # Check for event cards
    cards = soup.find_all(attrs={"data-event-id": True})
    print(f"data-event-id elements: {len(cards)}")
    event_links = [a["href"] for a in soup.find_all("a", href=True) if "/events/" in a.get("href", "")]
    print(f"Event links: {len(event_links)}")
    for link in event_links[:5]:
        print(f"  {link}")
    # Look for __NEXT_DATA__
    nd = soup.find("script", id="__NEXT_DATA__")
    if nd:
        data = json.loads(nd.string)
        print(f"__NEXT_DATA__ keys: {list(data.keys())}")
        if "props" in data:
            print(f"  props keys: {list(data['props'].keys())}")
    # Look for any inline JSON
    for s in soup.find_all("script"):
        text = s.string or ""
        if "events" in text.lower() and len(text) > 100:
            print(f"  Script with 'events': {len(text)} chars, preview: {text[:300]}")
            break
else:
    print(f"Response body: {r.text[:500]}")

# 2. Test category page
print("\n=== /discover/categories/sports with browser UA ===")
r2 = session.get("https://www.tickettailor.com/discover/categories/sports", timeout=20)
print(f"Status: {r2.status_code}, Size: {len(r2.text)}")
if r2.status_code == 200:
    soup2 = BeautifulSoup(r2.text, "lxml")
    cards2 = soup2.find_all(attrs={"data-event-id": True})
    print(f"data-event-id elements: {len(cards2)}")
    ev_links2 = [a["href"] for a in soup2.find_all("a", href=True) if "/events/" in a.get("href", "")]
    print(f"Event links: {len(ev_links2)}")
    for link in ev_links2[:3]:
        print(f"  {link}")

# 3. Try to get discover page with JSON Accept header (check for API endpoint)
print("\n=== /discover JSON endpoint check ===")
for url in [
    "https://www.tickettailor.com/discover/events",
    "https://www.tickettailor.com/discover/search",
    "https://www.tickettailor.com/discover?format=json",
]:
    r3 = session.get(url, headers={**HEADERS_BROWSER, "Accept": "application/json, */*"}, timeout=15)
    ct = r3.headers.get("Content-Type", "")
    print(f"  {url}: {r3.status_code} | {ct[:60]}")
    if "json" in ct and r3.status_code == 200:
        print(f"    Preview: {r3.text[:300]}")

print("\nDone.")
