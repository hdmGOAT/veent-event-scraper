"""Download and inspect Eventbee Angular services.js to find event detail API."""
import requests, re, sys

sys.stdout.reconfigure(encoding="utf-8")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
}

for js_url in [
    "https://d3slxyu0cebjsi.cloudfront.net/pj/atw/services",
    "https://d3slxyu0cebjsi.cloudfront.net/pj/atw/angularEventPage.v4",
    "https://d3slxyu0cebjsi.cloudfront.net/pj/atw/controllers.tickets.v11",
]:
    print(f"\n{'='*60}")
    print(f"URL: {js_url}")
    r = requests.get(js_url, headers=HEADERS, timeout=20)
    print(f"Status: {r.status_code} | Size: {len(r.text)}")
    js = r.text

    # Look for HTTP calls, URLs, $http, $resource
    http_calls = re.findall(r'\$http\.\w+\s*\([^)]{5,150}\)', js)[:10]
    print(f"\n$http calls ({len(http_calls)}):")
    for c in http_calls:
        print(f"  {c[:150]}")

    # URL strings
    url_strings = re.findall(r'["\']([^"\']*(?:jsp|action|api|event|registration)[^"\']{3,80})["\']', js)[:15]
    print(f"\nURL strings ({len(url_strings)}):")
    for u in url_strings:
        print(f"  {u}")

    # Look for servadd usage (API base variable)
    servadd_uses = re.findall(r'servadd\s*\+\s*["\'][^"\']{3,80}["\']', js)[:10]
    print(f"\nservadd + path ({len(servadd_uses)}):")
    for u in servadd_uses:
        print(f"  {u}")

    # Full first 2000 chars
    print(f"\nFirst 1500 chars:")
    print(js[:1500])
