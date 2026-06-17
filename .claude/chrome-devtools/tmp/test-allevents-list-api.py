"""Test AllEvents List Events by City API for Philippine cities."""
import requests, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

BASE = "http://api.allevents.in/events/list/"

def call(label, params):
    try:
        r = requests.get(BASE, headers=HEADERS, params=params, timeout=20)
        ct = r.headers.get("Content-Type", "")
        print(f"\n[{label}]")
        print(f"  URL: {r.url}")
        print(f"  Status: {r.status_code} | CT: {ct[:60]}")
        try:
            data = r.json()
            print(f"  Keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
            print(f"  Body: {json.dumps(data)[:800]}")
        except Exception:
            print(f"  Body: {r.text[:500]}")
    except Exception as e:
        print(f"\n[{label}] ERROR: {e}")

# Test without API key
call("Manila (no key)", {"city": "Manila", "state": "National Capital Region", "country": "PH", "page": 1})
call("Cebu (no key)", {"city": "Cebu", "state": "Central Visayas", "country": "PH", "page": 1})

# Try HTTPS
print("\n=== HTTPS variant ===")
r = requests.get("https://api.allevents.in/events/list/",
    headers=HEADERS,
    params={"city": "Manila", "state": "National Capital Region", "country": "PH"},
    timeout=20)
print(f"HTTPS status: {r.status_code} | CT: {r.headers.get('Content-Type','')[:60]}")
try:
    data = r.json()
    print(f"Keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
    print(f"Body: {json.dumps(data)[:1000]}")
except Exception:
    print(f"Body: {r.text[:500]}")

# Also try fetching the OpenAPI spec
print("\n=== OpenAPI spec ===")
for spec_url in [
    "https://allevents.developer.azure-api.net/developer/apis/5506d19acfdd541258b896c1?api-version=2022-04-01-preview",
    "https://allevents.azure-api.net/5506d19acfdd541258b896c1/swagger.json",
]:
    rs = requests.get(spec_url, headers=HEADERS, timeout=15)
    print(f"\n{spec_url}")
    print(f"  Status: {rs.status_code}")
    try:
        d = rs.json()
        print(f"  JSON keys: {list(d.keys()) if isinstance(d, dict) else type(d).__name__}")
        print(f"  Preview: {json.dumps(d)[:600]}")
    except Exception:
        print(f"  Body: {rs.text[:300]}")
