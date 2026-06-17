"""Explore api.tickettailor.com endpoints - not Cloudflare protected."""
import requests, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

def check(url, params=None):
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=15)
        ct = r.headers.get("Content-Type", "")
        try:
            body = r.json()
            preview = json.dumps(body)[:600]
        except Exception:
            preview = r.text[:400]
        print(f"  {r.status_code} [{ct[:40]}] {url}")
        print(f"    {preview}")
    except Exception as e:
        print(f"  ERROR {url}: {e}")

print("=== api.tickettailor.com exploration ===")
endpoints = [
    "https://api.tickettailor.com/v1/events",
    "https://api.tickettailor.com/v1/box_offices",
    "https://api.tickettailor.com/v1/events/search",
    "https://api.tickettailor.com/v1/discover",
    "https://api.tickettailor.com/v1/events?country=PH",
    "https://api.tickettailor.com/v1/events?location=philippines",
    "https://api.tickettailor.com/v1",
]
for ep in endpoints:
    check(ep)

# Also get the widget JS to find embedded API URL patterns
print("\n=== Widget JS API URL patterns ===")
r = requests.get("https://cdn.tickettailor.com/js/widgets/min/widget.js",
    headers={"User-Agent": HEADERS["User-Agent"]}, timeout=15)
print(f"Widget JS: {r.status_code}, {len(r.text)} bytes")

import re
# Look for URLs that aren't CSS/JS/fonts
urls = re.findall(r'https?://[a-zA-Z0-9._/-]+', r.text)
tt_urls = [u for u in urls if "tickettailor" in u and not u.endswith(".css")]
print(f"Ticket Tailor URLs in widget JS: {len(tt_urls)}")
for u in set(tt_urls):
    print(f"  {u}")

# Look for relative API paths
api_paths = re.findall(r'["\'](/[a-zA-Z0-9/_-]+)["\']', r.text)
event_paths = [p for p in api_paths if "event" in p.lower() or "api" in p.lower() or "box" in p.lower()]
print(f"\nEvent/API relative paths: {len(event_paths)}")
for p in set(event_paths)[:20]:
    print(f"  {p}")

# Look for "widget" domain patterns
widget_patterns = re.findall(r'widget[A-Za-z0-9._/-]*', r.text[:5000])
print(f"\nWidget patterns: {set(widget_patterns)}")
