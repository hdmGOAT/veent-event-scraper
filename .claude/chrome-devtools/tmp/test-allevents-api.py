"""Probe AllEvents API endpoints from the Azure API Management portal."""
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
        print(f"  URL: {url}")
        print(f"  Status: {r.status_code} | CT: {ct[:60]}")
        print(f"  Body: {preview}")
    except Exception as e:
        print(f"\n[{label}] ERROR: {e}")

# === Azure API Management Portal ===
print("=" * 60)
print("Azure API Management endpoints")
print("=" * 60)

# The portal URL suggests these base endpoints
base_azure = "https://allevents.developer.azure-api.net"

probe("Azure portal root", base_azure)
probe("Azure portal /apis", f"{base_azure}/apis")
probe("Azure portal /events", f"{base_azure}/events")
probe("Azure portal /v1/events", f"{base_azure}/v1/events")
probe("Azure portal /v2/events", f"{base_azure}/v2/events")

# Common Azure APIM docs endpoints
probe("Azure APIM swagger", f"{base_azure}/swagger.json")
probe("Azure APIM openapi", f"{base_azure}/openapi.json")

# === allevents.in API ===
print("\n" + "=" * 60)
print("allevents.in endpoints")
print("=" * 60)

probe("allevents.in root", "https://allevents.in/")
probe("allevents.in /api", "https://allevents.in/api/")
probe("allevents.in /api/events", "https://allevents.in/api/events")
probe("allevents.in Philippines", "https://allevents.in/philippines/")
probe("allevents.in Manila", "https://allevents.in/manila/")
probe("allevents.in Cebu", "https://allevents.in/cebu/")

# Check for JSON API that powers their app
probe("allevents.in /app/events", "https://allevents.in/app/events")
probe("allevents.in events.json", "https://allevents.in/events.json")
probe("allevents.in REST", "https://allevents.in/rest/events")

# === allevents.app ===
print("\n" + "=" * 60)
print("allevents.app endpoints")
print("=" * 60)

probe("allevents.app root", "https://allevents.app/")
probe("allevents.app /api", "https://allevents.app/api/")
probe("allevents.app /events", "https://allevents.app/events")
probe("allevents.app /v1/events", "https://allevents.app/v1/events")

print("\nDone.")
