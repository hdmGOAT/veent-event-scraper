"""Inspect Eventbee #maincontent and find AJAX endpoints for event listings."""
import requests, re, sys
from bs4 import BeautifulSoup

# Force UTF-8 output
sys.stdout.reconfigure(encoding="utf-8")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

r = requests.get("https://www.eventbee.com/browse?country=PH", headers=HEADERS, timeout=25)
soup = BeautifulSoup(r.text, "lxml")

# Dump #maincontent
mc = soup.find("div", id="maincontent")
if mc:
    print("=== #maincontent (first 3000 chars) ===")
    print(str(mc)[:3000])
else:
    print("No #maincontent found")

# Find all AJAX/fetch patterns in all script tags
print("\n=== Script AJAX/fetch/xhr patterns ===")
all_inline_js = ""
for s in soup.find_all("script"):
    if not s.get("src"):
        all_inline_js += (s.string or "") + "\n"

# Look for URLs in inline JS
urls_in_js = re.findall(r'(?:url|href|endpoint|api)["\s:=]+["\']([^"\']+)["\']', all_inline_js, re.I)
print(f"URL patterns in JS ({len(urls_in_js)}):")
for u in urls_in_js[:20]:
    print(f"  {u}")

# Look for $.ajax or $.get or $.post or fetch(
ajax_calls = re.findall(r'(?:\$\.(?:ajax|get|post|getJSON)|fetch|XMLHttpRequest)\s*\([^)]{0,200}', all_inline_js)
print(f"\nAJAX calls ({len(ajax_calls)}):")
for call in ajax_calls[:10]:
    print(f"  {call[:200]}")

# Look for window. variables that set event data
win_vars = re.findall(r'window\.\w+\s*=\s*.{0,150}', all_inline_js)
print(f"\nwindow.* assignments ({len(win_vars)}):")
for v in win_vars[:10]:
    print(f"  {v[:150]}")

# Check if there are event-related inline data (JSON blobs)
json_blobs = re.findall(r'(?:events|items|results)\s*[:=]\s*(\[.{20,500}?\])', all_inline_js, re.DOTALL)
print(f"\nJSON event blobs: {len(json_blobs)}")
for b in json_blobs[:2]:
    print(f"  {b[:200]}")

# Also check full page for event-related patterns
event_patterns = re.findall(r'event[-_](?:id|eid|list|data|url)["\s:=]+["\']?([^"\'<\s]{3,80})', r.text, re.I)
print(f"\nEvent ID patterns in HTML ({len(event_patterns)}):")
for p in event_patterns[:10]:
    print(f"  {p}")

# Check if the browse page has a different URL for PH specifically
# Maybe it's /browse/PH or /events/philippines etc
print("\n=== Trying alternate browse URLs ===")
for url in [
    "https://www.eventbee.com/browse/ph",
    "https://www.eventbee.com/browse/philippines",
    "https://www.eventbee.com/events/philippines",
    "https://www.eventbee.com/search?q=manila&country=PH",
    "https://www.eventbee.com/search?country=PH",
]:
    try:
        rr = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        # Check if it has eid= links
        eid_count = rr.text.count("eid=")
        print(f"  {rr.status_code} | size={len(rr.text)} | eid_links={eid_count} | final_url={rr.url}")
    except Exception as e:
        print(f"  ERROR: {e}")
