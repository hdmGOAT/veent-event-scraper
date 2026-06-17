"""Probe TicketMelon: Cloudflare check, page structure, API endpoints, PH coverage."""
import requests, re, json, sys
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
JHEADERS = {**HEADERS, "Accept": "application/json, */*"}

def probe(label, url, method="GET", data=None, headers=None, timeout=20):
    h = headers or HEADERS
    try:
        r = requests.request(method, url, headers=h, data=data, timeout=timeout,
                             allow_redirects=True)
        ct = r.headers.get("Content-Type", "")
        cf = "Just a moment" in r.text or "cf-browser-verification" in r.text or "Checking your browser" in r.text
        try:
            body = json.dumps(r.json())[:500]
        except Exception:
            body = r.text[:300]
        print(f"\n[{label}] {r.status_code} | cf={cf} | {ct[:40]}")
        print(f"  URL: {r.url}")
        print(f"  {body}")
        return r
    except Exception as e:
        print(f"\n[{label}] ERROR: {e}")
        return None

# 1. Homepage
print("=" * 60)
print("TicketMelon Discovery")
print("=" * 60)
r = probe("Homepage", "https://www.ticketmelon.com/")
if r and r.status_code == 200:
    soup = BeautifulSoup(r.text, "lxml")
    # SPA check
    scripts = soup.find_all("script", src=True)
    print(f"\n  Ext scripts: {[s['src'] for s in scripts[:5]]}")
    ng = soup.find(attrs={"ng-app": True}) or soup.find(attrs={"data-reactroot": True})
    next_data = soup.find("script", id="__NEXT_DATA__")
    print(f"  Angular: {bool(ng)}, React/Next: {bool(next_data)}")
    # Event links
    elinks = [a["href"] for a in soup.find_all("a", href=True)
              if "/event" in a.get("href","").lower() or "/e/" in a.get("href","")]
    print(f"  Event links: {elinks[:5]}")

# 2. Philippines browsing
probe("Browse PH", "https://www.ticketmelon.com/browse?country=PH")
probe("Browse PH events", "https://www.ticketmelon.com/events?country=PH")
probe("PH page", "https://www.ticketmelon.com/ph")
probe("Philippines page", "https://www.ticketmelon.com/philippines")
probe("Manila page", "https://www.ticketmelon.com/manila")
probe("Search manila", "https://www.ticketmelon.com/search?q=manila")
probe("Search PH", "https://www.ticketmelon.com/search?q=philippines")

# 3. API endpoints
print("\n" + "=" * 60)
print("API probe")
print("=" * 60)
for ep in [
    "https://www.ticketmelon.com/api/events",
    "https://www.ticketmelon.com/api/v1/events",
    "https://www.ticketmelon.com/api/v2/events",
    "https://api.ticketmelon.com/events",
    "https://api.ticketmelon.com/v1/events",
    "https://www.ticketmelon.com/api/events?country=PH",
    "https://www.ticketmelon.com/api/events/search?q=philippines",
]:
    probe(ep.split("/")[-1] or ep, ep, headers=JHEADERS)

# 4. Robots / sitemap
print("\n" + "=" * 60)
print("Robots / Sitemap")
print("=" * 60)
probe("robots.txt", "https://www.ticketmelon.com/robots.txt")
probe("sitemap.xml", "https://www.ticketmelon.com/sitemap.xml")
probe("sitemap_index", "https://www.ticketmelon.com/sitemap_index.xml")

print("\nDone.")
