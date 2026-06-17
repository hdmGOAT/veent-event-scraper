"""Deep-probe TicketMelon JSON API and sitemaps for event data structure."""
import requests, re, json, sys
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

import urllib3
urllib3.disable_warnings()

sess = requests.Session()
sess.verify = False
sess.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, */*",
    "Accept-Language": "en-US,en;q=0.9",
})

def jp(label, url, **kwargs):
    print(f"\n[{label}]")
    r = sess.get(url, timeout=15, **kwargs)
    print(f"  {r.status_code} | {r.headers.get('Content-Type','')[:40]}")
    try:
        j = r.json()
        print(f"  {json.dumps(j, ensure_ascii=False)[:800]}")
        return j
    except:
        print(f"  {r.text[:300]}")
        return None

# 1. Explore JSON API with various params
print("=" * 60)
print("JSON API exploration")
print("=" * 60)

# Base endpoints
jp("list (bare)", "https://www.ticketmelon.com/api/events/list")
jp("list country=PH", "https://www.ticketmelon.com/api/events/list?country=PH")
jp("list countryCode=PH", "https://www.ticketmelon.com/api/events/list?countryCode=PH")
jp("list page=1&limit=20", "https://www.ticketmelon.com/api/events/list?page=1&limit=20")
jp("list page=1&size=20&country=PH", "https://www.ticketmelon.com/api/events/list?page=1&size=20&country=PH")
jp("featured", "https://www.ticketmelon.com/api/events/featured")
jp("featured country=PH", "https://www.ticketmelon.com/api/events/featured?country=PH")
jp("search manila", "https://www.ticketmelon.com/api/events/search?q=manila")
jp("search manila+PH", "https://www.ticketmelon.com/api/events/search?q=manila&country=PH")

# Try alternate path patterns
jp("v1 events", "https://www.ticketmelon.com/api/v1/events")
jp("v2 events", "https://www.ticketmelon.com/api/v2/events")

# 2. Sitemap exploration
print("\n" + "=" * 60)
print("Sitemap exploration")
print("=" * 60)
r = sess.get("https://www.ticketmelon.com/sitemap.xml", timeout=15)
sitemap_urls = re.findall(r'<loc>([^<]+)</loc>', r.text)
print(f"Sitemap entries: {sitemap_urls}")

# Check first event sitemap
if sitemap_urls:
    for sm_url in sitemap_urls[:2]:
        print(f"\n--- {sm_url} ---")
        rs = sess.get(sm_url, timeout=15)
        locs = re.findall(r'<loc>([^<]+)</loc>', rs.text)
        ph_locs = [u for u in locs if "manila" in u.lower() or "philippines" in u.lower()
                   or "/ph/" in u.lower()]
        print(f"  Total URLs: {len(locs)} | PH-related: {len(ph_locs)}")
        print(f"  First 5: {locs[:5]}")
        print(f"  PH: {ph_locs[:5]}")

# 3. Event detail page __NEXT_DATA__
# Get a real event URL from sitemap
print("\n" + "=" * 60)
print("Event detail page __NEXT_DATA__")
print("=" * 60)
if sitemap_urls:
    rs = sess.get(sitemap_urls[0], timeout=15)
    locs = re.findall(r'<loc>([^<]+)</loc>', rs.text)
    if locs:
        event_url = locs[0]
        print(f"Checking: {event_url}")
        re2 = sess.get(event_url, headers={
            "Accept": "text/html,*/*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        }, timeout=20)
        soup = BeautifulSoup(re2.text, "lxml")
        nd = soup.find("script", id="__NEXT_DATA__")
        if nd:
            data = json.loads(nd.string)
            page_props = data.get("props", {}).get("pageProps", {})
            print(f"  pageProps keys: {list(page_props.keys())}")
            print(f"  pageProps (3000 chars):")
            print(json.dumps(page_props, ensure_ascii=False)[:3000])
        else:
            print("  No __NEXT_DATA__")
            print(re2.text[:500])
