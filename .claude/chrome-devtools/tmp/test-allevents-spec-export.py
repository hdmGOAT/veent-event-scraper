"""Try AllEvents Azure APIM spec export URL patterns."""
import requests, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}

api_id = "5506d19acfdd541258b896c1"  # List Events by City
api_ids = {
    "list-events-by-city": "5506d19acfdd541258b896c1",
    "events-search-global": "55e6f4cbadecff1658d2910c",
    "search-organizers": "598ad298adecff12f8d890eb",
}

# Try various Azure APIM export URL patterns
portal = "https://allevents.developer.azure-api.net"
apim_version = "2022-04-01-preview"

candidates = [
    f"{portal}/developer/apis/{api_id}/export?format=openapi%2Bjson&api-version={apim_version}",
    f"{portal}/developer/apis/{api_id}/export?format=openapi+json&api-version={apim_version}",
    f"{portal}/developer/apis/{api_id}/export?format=openapi&api-version={apim_version}",
    f"{portal}/developer/apis/{api_id}/export?format=swagger&api-version={apim_version}",
    f"{portal}/apis/{api_id}/export?format=openapi%2Bjson",
    f"https://allevents.azure-api.net/{api_id}/openapi.json",
    f"https://allevents.azure-api.net/events/list/openapi.json",
]

for url in candidates:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        ct = r.headers.get("Content-Type", "")
        body_preview = r.text[:300]
        print(f"\n{r.status_code} [{ct[:40]}]")
        print(f"  {url}")
        print(f"  {body_preview}")
    except Exception as e:
        print(f"\nERROR {url}: {e}")

print("\n=== Also try WADL which may not need auth ===")
wadl_url = f"{portal}/developer/apis/{api_id}/export?format=wadl&api-version={apim_version}"
r = requests.get(wadl_url, headers=HEADERS, timeout=15)
print(f"{r.status_code}: {r.text[:500]}")
