"""Probe ArenaSoldOut WordPress REST API and events page structure."""
import requests, re, json, sys
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")
import urllib3; urllib3.disable_warnings()

sess = requests.Session()
sess.verify = False
sess.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
})

BASE = "https://arenasoldout.com"

def jp(label, url, **kwargs):
    r = sess.get(url, timeout=20, **kwargs)
    ct = r.headers.get("Content-Type", "")
    print(f"\n[{label}] {r.status_code} | {ct[:40]}")
    try:
        j = r.json()
        print(f"  {json.dumps(j, ensure_ascii=False)[:600]}")
        return r, j
    except:
        print(f"  {r.text[:300]}")
        return r, None

# 1. WordPress REST API discovery
print("=" * 60)
print("WordPress REST API")
print("=" * 60)
jp("wp-json root", f"{BASE}/wp-json/")
jp("wp/v2 posts", f"{BASE}/wp-json/wp/v2/posts?per_page=3")
jp("wp/v2 types", f"{BASE}/wp-json/wp/v2/types")

# The Events Calendar plugin endpoints
jp("tribe events v1", f"{BASE}/wp-json/tribe/events/v1/events?per_page=5")
jp("tribe events PH", f"{BASE}/wp-json/tribe/events/v1/events?per_page=20&location=philippines")
jp("tribe events cat", f"{BASE}/wp-json/tribe/events/v1/categories")

# Custom post type guesses
for cpt in ["event", "events", "show", "concert", "tribe_events"]:
    r, j = jp(f"wp/v2/{cpt}", f"{BASE}/wp-json/wp/v2/{cpt}?per_page=3")

# 2. Events page HTML
print("\n" + "=" * 60)
print("Events page HTML")
print("=" * 60)
r = sess.get(f"{BASE}/events/", timeout=20)
soup = BeautifulSoup(r.text, "lxml")
print(f"Status: {r.status_code} | Size: {len(r.text)}")

# Check for The Events Calendar markup
tribe_events = soup.select(".tribe-events-calendar, .tribe-event, .tribe_events_cat, [class*='tribe']")
print(f"Tribe Events elements: {len(tribe_events)}")

# Generic event card selectors
cards = (soup.select("article.tribe_events_cat") or
         soup.select("article[class*='event']") or
         soup.select(".event-item") or
         soup.select(".events-list article") or
         soup.select("article"))
print(f"Article/event cards: {len(cards)}")
if cards:
    print(f"First card: {str(cards[0])[:600]}")

# All links containing 'event'
event_links = [(a.get_text(strip=True)[:50], a["href"])
               for a in soup.find_all("a", href=True)
               if "/event" in a.get("href","").lower() and "arenasoldout" in a.get("href","")]
print(f"\nEvent links: {len(event_links)}")
for name, href in event_links[:10]:
    print(f"  {name} -> {href}")

# 3. Sitemap
print("\n" + "=" * 60)
print("Sitemap")
print("=" * 60)
r = sess.get(f"{BASE}/sitemap_index.xml", timeout=15)
sitemap_urls = re.findall(r"<loc>([^<]+)</loc>", r.text)
print(f"Sitemaps: {sitemap_urls}")
for sm in sitemap_urls[:3]:
    rs = sess.get(sm, timeout=15)
    locs = re.findall(r"<loc>([^<]+)</loc>", rs.text)
    ph = [u for u in locs if any(k in u.lower() for k in ["manila","phil","cebu","davao","event"])]
    print(f"\n  {sm.split('/')[-1]}: {len(locs)} URLs | event-related: {len(ph)}")
    print(f"  First 5: {locs[:5]}")
    print(f"  PH/event: {ph[:5]}")
