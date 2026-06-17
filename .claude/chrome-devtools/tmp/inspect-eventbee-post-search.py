"""Try POST search endpoint and sample event sitemaps for Philippines events."""
import requests, re, sys
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.eventbee.com/search",
    "Origin": "https://www.eventbee.com",
}
AJAX_HEADERS = {**HEADERS, "X-Requested-With": "XMLHttpRequest", "Accept": "text/html,*/*"}

def show_event_links(html, label=""):
    soup = BeautifulSoup(html, "lxml")
    elinks = [(a.get_text(strip=True)[:60], a["href"])
              for a in soup.find_all("a", href=True)
              if "eid=" in a.get("href", "")]
    print(f"  [{label}] event links: {len(elinks)}")
    for name, href in elinks[:8]:
        eid = re.search(r"eid=(\d+)", href)
        print(f"    [{eid.group(1) if eid else '?'}] {name} -> {href[:80]}")
    if not elinks:
        # Show first 600 chars of HTML
        text = soup.get_text(separator=" ", strip=True)[:400]
        print(f"  Body text: {text}")
    return elinks

# Try POST to search endpoint
print("=== POST search!searchResult ===")
for q in ["manila", "cebu", "philippines", "davao"]:
    url = "https://www.eventbee.com/search!searchResult"
    data = {"searchcontent": q}
    r = requests.post(url, headers=AJAX_HEADERS, data=data, timeout=20)
    print(f"\nPOST {url} q={q!r} -> {r.status_code} | size={len(r.text)}")
    show_event_links(r.text, q)

# Also try POST to just /search
print("\n=== POST /search ===")
for q in ["manila", "philippines"]:
    r = requests.post("https://www.eventbee.com/search",
                      headers=AJAX_HEADERS,
                      data={"searchcontent": q}, timeout=20)
    print(f"\nPOST /search q={q!r} -> {r.status_code} | size={len(r.text)}")
    show_event_links(r.text, q)

# Sample the most recent daily event sitemaps
print("\n=== Recent event sitemaps ===")
r = requests.get("https://www.eventbee.com/sitemap/sitemapindex_2023.xml",
                 headers=HEADERS, timeout=20)
sitemap_urls = re.findall(r'<loc>([^<]+)</loc>', r.text)
# Get last 5 sitemaps (most recent)
recent = sitemap_urls[-5:]
print(f"Total sitemaps: {len(sitemap_urls)}, checking last 5:")
for url in recent:
    print(f"\n  Sitemap: {url}")
    try:
        rs = requests.get(url, headers=HEADERS, timeout=15)
        locs = re.findall(r'<loc>([^<]+)</loc>', rs.text)
        ph_locs = [u for u in locs
                   if any(k in u.lower() for k in ["manila", "cebu", "davao", "philippines", "ph", "quezon"])]
        print(f"  Total events: {len(locs)} | PH events: {len(ph_locs)}")
        for u in ph_locs[:5]:
            print(f"    {u}")
        if locs and not ph_locs:
            print(f"  Sample: {locs[0]}")
    except Exception as e:
        print(f"  ERROR: {e}")
