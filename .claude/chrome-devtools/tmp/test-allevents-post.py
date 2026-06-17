"""Test AllEvents List Events by City as POST (not GET)."""
import requests, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

BASE = "http://api.allevents.in/events/list/"

def post(label, params):
    try:
        r = requests.post(BASE, headers=HEADERS, params=params, timeout=20)
        ct = r.headers.get("Content-Type", "")
        print(f"\n[{label}]")
        print(f"  Status: {r.status_code} | CT: {ct[:60]}")
        try:
            data = r.json()
            print(f"  Keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
            print(f"  Body: {json.dumps(data)[:1000]}")
        except Exception:
            print(f"  Body: {r.text[:500]}")
    except Exception as e:
        print(f"\n[{label}] ERROR: {e}")

# POST with query params (as shown in the portal URL pattern)
post("Manila POST (no key)", {"city": "Manila", "state": "National Capital Region", "country": "PH", "page": 1})

# Try with HTTPS
r = requests.post(
    "https://api.allevents.in/events/list/",
    headers=HEADERS,
    params={"city": "Manila", "state": "National Capital Region", "country": "PH"},
    timeout=20
)
print(f"\n[Manila POST HTTPS]: {r.status_code} | {r.headers.get('Content-Type','')[:60]}")
print(f"  {r.text[:500]}")

# Try also with body JSON instead of query params
r2 = requests.post(
    "http://api.allevents.in/events/list/",
    headers=HEADERS,
    json={"city": "Manila", "state": "National Capital Region", "country": "PH"},
    timeout=20
)
print(f"\n[Manila POST body JSON]: {r2.status_code}")
print(f"  {r2.text[:500]}")

# Check if we get a different error (key-related vs auth-error vs 404)
print("\n=== Error analysis ===")
print("GET /events/list/:")
rg = requests.get("http://api.allevents.in/events/list/", headers=HEADERS, params={"city": "Manila", "country": "PH"}, timeout=15)
print(f"  {rg.status_code}: {rg.text[:200]}")

print("POST /events/list/:")
rp = requests.post("http://api.allevents.in/events/list/", headers=HEADERS, params={"city": "Manila", "country": "PH"}, timeout=15)
print(f"  {rp.status_code}: {rp.text[:200]}")

print("POST /events/list/ missing state:")
rp2 = requests.post("http://api.allevents.in/events/list/", headers=HEADERS, params={"city": "Manila", "state": "NCR", "country": "PH"}, timeout=15)
print(f"  {rp2.status_code}: {rp2.text[:200]}")
