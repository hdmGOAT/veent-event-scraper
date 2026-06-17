"""Find the correct Eventbrite location slugs for PH cities."""
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EventScraper/1.0)"}

candidates = [
    "philippines--cebu-city",
    "philippines--cebu",
    "philippines--cebu-city--1",
    "philippines--davao-city",
    "philippines--davao",
    "philippines--cagayan-de-oro",
]

for slug in candidates:
    url = f"https://www.eventbrite.com/d/{slug}/all-events/"
    r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
    final = r.url
    print(f"{slug}: status={r.status_code} final_url={final[:80]}")
