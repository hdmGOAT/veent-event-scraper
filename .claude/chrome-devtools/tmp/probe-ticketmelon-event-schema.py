"""Inspect full event schema from __NEXT_DATA__ and count PH events across sitemaps."""
import requests, re, json, sys
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")
import urllib3; urllib3.disable_warnings()

sess = requests.Session()
sess.verify = False
sess.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})

# 1. Get full event schema from a non-PH event first
print("=== Full event schema from __NEXT_DATA__ ===")
r = sess.get("https://www.ticketmelon.com/cloudylivehouse/goodmoodYMYmute2026", timeout=20)
soup = BeautifulSoup(r.text, "lxml")
nd = json.loads(soup.find("script", id="__NEXT_DATA__").string)
event = nd["props"]["pageProps"]["event"]
print(json.dumps(event, ensure_ascii=False, indent=2)[:6000])

# 2. Check a Philippines event
print("\n=== Philippines event from sitemap ===")
r2 = sess.get("https://www.ticketmelon.com/bbe/lullaboymanila", timeout=20)
soup2 = BeautifulSoup(r2.text, "lxml")
nd2 = json.loads(soup2.find("script", id="__NEXT_DATA__").string)
event2 = nd2["props"]["pageProps"]["event"]
print(json.dumps(event2, ensure_ascii=False, indent=2)[:5000])

# 3. Count PH events across ALL sitemaps
print("\n=== PH event inventory across all sitemaps ===")
all_urls = []
sitemap_index = sess.get("https://www.ticketmelon.com/sitemap.xml", timeout=15)
sitemap_files = re.findall(r'<loc>([^<]+)</loc>', sitemap_index.text)
print(f"Sitemap files: {len(sitemap_files)}")

for sm_url in sitemap_files:
    rs = sess.get(sm_url, timeout=15)
    locs = re.findall(r'<loc>([^<]+)</loc>', rs.text)
    all_urls.extend(locs)
    ph = [u for u in locs
          if any(k in u.lower() for k in ["manila", "phil", "/ph/", "cebu", "davao", "quezon", "makati"])]
    print(f"  {sm_url.split('/')[-1]}: {len(locs)} events, {len(ph)} PH-related")
    for u in ph:
        print(f"    {u}")

print(f"\nTotal events in sitemaps: {len(all_urls)}")
