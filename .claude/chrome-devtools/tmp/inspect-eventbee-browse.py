"""Inspect Eventbee browse page HTML structure for Philippines events."""
import requests, json, re
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def inspect_browse(url, label):
    print(f"\n{'='*60}")
    print(f"{label}")
    print(f"URL: {url}")
    print('='*60)
    r = requests.get(url, headers=HEADERS, timeout=25)
    print(f"Status: {r.status_code}, Size: {len(r.text)}")
    soup = BeautifulSoup(r.text, "lxml")

    # Find event cards — try common patterns
    cards = (
        soup.select("div.event-listing") or
        soup.select("div[class*='event-item']") or
        soup.select("div[class*='event-card']") or
        soup.select("li[class*='event']") or
        soup.select("div[class*='eventlist']") or
        soup.select("div.event") or
        soup.select("[data-eid]") or
        soup.select("a[href*='?eid=']")
    )
    print(f"Event card candidates: {len(cards)}")
    if cards:
        print(f"First card HTML: {str(cards[0])[:600]}")

    # Look for event links with eid param
    event_links = [(a.get_text(strip=True)[:60], a["href"])
                   for a in soup.find_all("a", href=True)
                   if "eid=" in a.get("href", "")]
    print(f"\nEvent links (eid=): {len(event_links)}")
    for name, href in event_links[:5]:
        eid = re.search(r"eid=(\d+)", href)
        print(f"  [{eid.group(1) if eid else '?'}] {name} -> {href[:80]}")

    # Pagination
    pages = soup.select("a[href*='page=']") or soup.select(".pagination a") or soup.select("a[href*='pg=']")
    print(f"\nPagination links: {len(pages)}")
    for p in pages[:5]:
        print(f"  {p.get_text(strip=True)} -> {p.get('href','')[:80]}")

    # Total count
    total_el = soup.find(string=re.compile(r"\d+\s+event", re.I))
    if total_el:
        print(f"\nTotal count text: {total_el.strip()[:100]}")

    return soup

# Browse Philippines
s1 = inspect_browse("https://www.eventbee.com/browse?country=PH", "Browse Philippines")

# Browse Manila
s2 = inspect_browse("https://www.eventbee.com/browse?city=Manila&country=PH", "Browse Manila PH")

# Inspect page 2 to understand pagination param
inspect_browse("https://www.eventbee.com/browse?country=PH&page=2", "Browse PH page=2")
inspect_browse("https://www.eventbee.com/browse?country=PH&pg=2", "Browse PH pg=2")
inspect_browse("https://www.eventbee.com/browse?country=PH&start=10", "Browse PH start=10")

# Check what params the browse form uses
print("\n=== Form / search params ===")
r = requests.get("https://www.eventbee.com/browse", headers=HEADERS, timeout=20)
soup = BeautifulSoup(r.text, "lxml")
forms = soup.find_all("form")
for f in forms:
    print(f"Form action={f.get('action','')} method={f.get('method','')}")
    for inp in f.find_all(["input", "select"]):
        print(f"  {inp.name} name={inp.get('name','')} value={inp.get('value','')} type={inp.get('type','')}")

print("\nDone.")
