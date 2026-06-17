"""Probe the actual AllEvents Azure API gateway (not the developer portal)."""
import requests, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

def probe(label, url, params=None, extra_headers=None):
    h = {**HEADERS, **(extra_headers or {})}
    try:
        r = requests.get(url, headers=h, params=params, timeout=20)
        ct = r.headers.get("Content-Type", "")
        try:
            body = r.json()
            preview = json.dumps(body)[:800]
        except Exception:
            preview = r.text[:500]
        print(f"\n[{label}]")
        print(f"  {r.status_code} | {ct[:50]}")
        print(f"  {preview}")
    except Exception as e:
        print(f"\n[{label}] ERROR: {e}")

# The actual Azure APIM gateway (separate from developer portal)
base = "https://allevents.azure-api.net"

print("=== Azure APIM Gateway ===")
probe("Gateway root", base)
probe("Gateway /v1", f"{base}/v1")
probe("Gateway /events", f"{base}/events")
probe("Gateway /v1/events", f"{base}/v1/events")
probe("Gateway /v2/events", f"{base}/v2/events")
probe("Gateway /api/events", f"{base}/api/events")
probe("Gateway /events/search", f"{base}/events/search")
probe("Gateway /v1/events/search", f"{base}/v1/events/search")
probe("Gateway /v1/events/search Manila", f"{base}/v1/events/search",
      params={"city": "Manila", "country": "PH"})
probe("Gateway /discovery", f"{base}/discovery")
probe("Gateway /v1/discovery", f"{base}/v1/discovery")

# AllEvents app API (might be the same or different)
print("\n=== allevents.app API variants ===")
for variant in [
    "https://api.allevents.in",
    "https://api.allevents.app",
    "https://allevents.in/api/v1/events",
    "https://allevents.in/api/v2/events",
]:
    probe(f"variant {variant}", variant)

print("\nDone.")
