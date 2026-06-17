"""Inspect TicketMelon Next.js data: __NEXT_DATA__, API routes, event structure."""
import requests, re, json, sys
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
JHEADERS = {**HEADERS, "Accept": "application/json, */*"}

sess = requests.Session()
sess.headers.update(HEADERS)
sess.verify = False  # certifi bundle missing in this venv

import urllib3
urllib3.disable_warnings()

def get_next_data(url, label):
    print(f"\n{'='*60}\n{label}\n{url}\n{'='*60}")
    r = sess.get(url, timeout=20)
    print(f"Status: {r.status_code} | Size: {len(r.text)}")
    soup = BeautifulSoup(r.text, "lxml")
    nd = soup.find("script", id="__NEXT_DATA__")
    if nd:
        try:
            data = json.loads(nd.string)
            print(f"  __NEXT_DATA__ keys: {list(data.keys())}")
            props = data.get("props", {})
            print(f"  props keys: {list(props.keys())}")
            page_props = props.get("pageProps", {})
            print(f"  pageProps keys: {list(page_props.keys())}")
            # Dump truncated JSON
            print(f"  pageProps (first 2000 chars):")
            print(json.dumps(page_props, ensure_ascii=False)[:2000])
            return data
        except Exception as e:
            print(f"  JSON parse error: {e}")
    else:
        print("  No __NEXT_DATA__ found")
    return None

# Homepage
get_next_data("https://www.ticketmelon.com/", "Homepage")

# Search pages
get_next_data("https://www.ticketmelon.com/search?q=manila", "Search: manila")
get_next_data("https://www.ticketmelon.com/search?q=philippines", "Search: philippines")

# Try to find events listing pages from the site
print("\n=== Probing known Next.js route patterns ===")
for url in [
    "https://www.ticketmelon.com/events",
    "https://www.ticketmelon.com/explore",
    "https://www.ticketmelon.com/discover",
    "https://www.ticketmelon.com/category",
    "https://www.ticketmelon.com/all-events",
]:
    r = sess.get(url, timeout=10)
    nd = BeautifulSoup(r.text, "lxml").find("script", id="__NEXT_DATA__")
    has_data = bool(nd)
    print(f"  {r.status_code} | __NEXT_DATA__={has_data} | {url}")

# Try Next.js API routes
print("\n=== Next.js API routes ===")
for url in [
    "https://www.ticketmelon.com/api/events",
    "https://www.ticketmelon.com/api/events?country=PH",
    "https://www.ticketmelon.com/api/search?q=manila",
    "https://www.ticketmelon.com/api/search?q=philippines",
    "https://www.ticketmelon.com/api/explore",
    "https://www.ticketmelon.com/api/home",
    "https://www.ticketmelon.com/api/event/list",
    "https://www.ticketmelon.com/api/events/list",
    "https://www.ticketmelon.com/api/events/featured",
    "https://www.ticketmelon.com/api/events/search?q=manila",
]:
    r = sess.get(url, headers={**HEADERS, "Accept": "application/json"}, timeout=10)
    ct = r.headers.get("Content-Type", "")
    try:
        j = r.json()
        print(f"  {r.status_code} JSON | {url}")
        print(f"    keys: {list(j.keys())[:8] if isinstance(j, dict) else str(j)[:100]}")
    except:
        print(f"  {r.status_code} HTML | {url} | {r.text[:60].strip()}")

# Check robots.txt and sitemap
print("\n=== Robots / Sitemap ===")
for url in [
    "https://www.ticketmelon.com/robots.txt",
    "https://www.ticketmelon.com/sitemap.xml",
]:
    r = sess.get(url, timeout=10)
    print(f"\n{url} -> {r.status_code}")
    print(r.text[:600])
