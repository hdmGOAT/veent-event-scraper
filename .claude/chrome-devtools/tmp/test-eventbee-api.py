"""Probe Eventbee structure: server-render, APIs, Philippines coverage."""
import requests, json, re
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
JHEADERS = {**HEADERS, "Accept": "application/json"}

def probe(label, url, method="GET", params=None, headers=None, timeout=20):
    h = headers or HEADERS
    try:
        r = requests.request(method, url, headers=h, params=params, timeout=timeout)
        ct = r.headers.get("Content-Type", "")
        blocked = "Just a moment" in r.text or "cf-browser-verification" in r.text
        try:
            body = r.json()
            preview = json.dumps(body)[:600]
        except Exception:
            preview = r.text[:400]
        print(f"\n[{label}] {r.status_code} | {ct[:45]} | cf={blocked}")
        print(f"  {preview}")
        return r
    except Exception as e:
        print(f"\n[{label}] ERROR: {e}")
        return None

# 1. Homepage
print("=" * 60)
print("Eventbee Homepage & Discovery")
print("=" * 60)
r = probe("Homepage", "https://www.eventbee.com/")
if r and r.status_code == 200 and "Just a moment" not in r.text:
    soup = BeautifulSoup(r.text, "lxml")
    links = [a["href"] for a in soup.find_all("a", href=True) if "event" in a.get("href","").lower()]
    print(f"  Event-related links: {links[:8]}")

# 2. Browse/Search pages
probe("Browse all", "https://www.eventbee.com/browse")
probe("Browse Philippines", "https://www.eventbee.com/browse?country=PH")
probe("Browse Manila", "https://www.eventbee.com/browse?city=Manila")
probe("Search", "https://www.eventbee.com/search?q=philippines")
probe("Events index", "https://www.eventbee.com/events")
probe("Events Philippines", "https://www.eventbee.com/events?country=PH")

# 3. API endpoints
print("\n" + "=" * 60)
print("API probe")
print("=" * 60)
for ep in [
    "https://www.eventbee.com/api/events",
    "https://www.eventbee.com/api/v1/events",
    "https://www.eventbee.com/api/v2/events",
    "https://api.eventbee.com/events",
    "https://api.eventbee.com/v1/events",
    "https://www.eventbee.com/api/events/search?q=philippines",
    "https://www.eventbee.com/v/events.json",
]:
    probe(ep.split("/")[-1] or ep, ep, headers=JHEADERS)

# 4. Sitemap/robots
print("\n" + "=" * 60)
print("Sitemap / robots")
print("=" * 60)
probe("robots.txt", "https://www.eventbee.com/robots.txt")
probe("sitemap.xml", "https://www.eventbee.com/sitemap.xml")
probe("sitemap_index", "https://www.eventbee.com/sitemap_index.xml")

print("\nDone.")
