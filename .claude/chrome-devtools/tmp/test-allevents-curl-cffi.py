"""Test curl_cffi Chrome impersonation against Cloudflare-protected allevents.in."""
from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup
import json, re

session = cffi_requests.Session(impersonate="chrome124")

cities = [
    ("manila", "https://allevents.in/manila/all"),
    ("cebu", "https://allevents.in/cebu/all"),
    ("davao", "https://allevents.in/davao/all"),
    ("cagayan-de-oro", "https://allevents.in/cagayan-de-oro/all"),
]

for slug, url in cities:
    try:
        r = session.get(url, timeout=20)
        title_match = re.search(r"<title>(.*?)</title>", r.text, re.I)
        title = title_match.group(1) if title_match else "?"
        cloudflare_blocked = "Just a moment" in r.text or "challenge" in r.text.lower()
        print(f"{slug}: status={r.status_code}, title={title[:60]}, cf_blocked={cloudflare_blocked}, size={len(r.text)}")

        if not cloudflare_blocked and r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            # Look for event data
            event_ids = [a.get("data-eid") or a.get("data-event-id") for a in soup.find_all(attrs={"data-eid": True})]
            event_links = [a["href"] for a in soup.find_all("a", href=True) if "/e/" in a.get("href", "")]
            # Look for JSON data
            scripts = soup.find_all("script")
            json_data = [s.string for s in scripts if s.string and ("events" in s.string.lower()) and len(s.string) > 200]
            print(f"  event_ids={len(event_ids)}, event_links={len(event_links)}, json_scripts={len(json_data)}")
            if event_links:
                print(f"  sample links: {event_links[:3]}")
    except Exception as e:
        print(f"{slug}: ERROR {e}")

# Also try the internal API endpoint with curl_cffi
print("\n=== Internal API test ===")
for city, state in [("Manila", "National Capital Region"), ("Cebu", "Central Visayas")]:
    try:
        r = session.post(
            "http://api.allevents.in/events/list/",
            params={"city": city, "state": state, "country": "PH", "page": 1},
            timeout=20,
        )
        print(f"  POST /events/list/ {city}: {r.status_code} | {r.text[:200]}")
    except Exception as e:
        print(f"  POST /events/list/ {city}: ERROR {e}")
