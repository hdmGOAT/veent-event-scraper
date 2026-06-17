"""Inspect Eventbee search page and sitemaps for Philippines events."""
import requests, re, sys
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def dump_page(url, label):
    print(f"\n{'='*60}\n{label}\n{url}\n{'='*60}")
    r = requests.get(url, headers=HEADERS, timeout=25)
    soup = BeautifulSoup(r.text, "lxml")
    mc = soup.find("div", id="maincontent") or soup.find("main")
    print(f"Status: {r.status_code} | Size: {len(r.text)}")
    if mc:
        print(str(mc)[:3000])
    else:
        # Show body text
        body = soup.find("body")
        if body:
            print(body.get_text(separator="\n", strip=True)[:1500])
    # Event links
    elinks = [(a.get_text(strip=True)[:60], a["href"])
              for a in soup.find_all("a", href=True)
              if "eid=" in a.get("href", "")]
    print(f"\nEvent links (eid=): {len(elinks)}")
    for name, href in elinks[:8]:
        eid = re.search(r"eid=(\d+)", href)
        print(f"  [{eid.group(1) if eid else '?'}] {name} -> {href[:80]}")
    return r, soup

# Search pages
dump_page("https://www.eventbee.com/search?q=manila", "Search: manila")
dump_page("https://www.eventbee.com/search?q=philippines", "Search: philippines")
dump_page("https://www.eventbee.com/search?q=cebu", "Search: cebu")
dump_page("https://www.eventbee.com/search?country=PH", "Search: country=PH")

# Browse without params (homepage-like)
dump_page("https://www.eventbee.com/browse", "Browse (no filter)")

# Country page pattern from footer JS
dump_page("https://www.eventbee.com/ticketing-system-in-Philippines", "Ticketing in Philippines")

# Check sitemap
print("\n=== Sitemaps ===")
for url in [
    "https://www.eventbee.com/sitemap/sitemapindex_2023.xml",
    "https://www.eventbee.com/sitemap/sitemaprenderer.jsp",
    "https://www.eventbee.com/sitemap.xml",
]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        print(f"\n{url}")
        print(f"  Status: {r.status_code} | Size: {len(r.text)}")
        if r.status_code == 200:
            ph_urls = [u for u in re.findall(r'<loc>([^<]+)</loc>', r.text)
                       if "ph" in u.lower() or "manila" in u.lower() or "cebu" in u.lower() or "philippines" in u.lower()]
            print(f"  PH-related URLs: {len(ph_urls)}")
            for u in ph_urls[:10]:
                print(f"    {u}")
            # Show first few urls
            all_locs = re.findall(r'<loc>([^<]+)</loc>', r.text)[:5]
            print(f"  First URLs: {all_locs}")
    except Exception as e:
        print(f"  ERROR: {e}")

# Check the homepage for any event listing mechanism
print("\n=== Homepage event links ===")
r = requests.get("https://www.eventbee.com/", headers=HEADERS, timeout=20)
soup = BeautifulSoup(r.text, "lxml")
elinks = [(a.get_text(strip=True)[:60], a["href"])
          for a in soup.find_all("a", href=True)
          if "eid=" in a.get("href", "")]
print(f"eid= links on homepage: {len(elinks)}")
for name, href in elinks[:5]:
    eid = re.search(r"eid=(\d+)", href)
    print(f"  [{eid.group(1) if eid else '?'}] {name} -> {href[:80]}")
