"""Probe ArenaSoldOut: Cloudflare, page structure, API endpoints, PH coverage."""
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

def probe(label, url, method="GET", data=None, json_body=None, extra_headers=None, timeout=20):
    h = dict(sess.headers)
    if extra_headers:
        h.update(extra_headers)
    try:
        r = sess.request(method, url, headers=h, data=data, json=json_body,
                         timeout=timeout, allow_redirects=True)
        ct = r.headers.get("Content-Type", "")
        cf = any(x in r.text for x in ["Just a moment", "cf-browser-verification", "Checking your browser", "cloudflare"])
        try:
            body = json.dumps(r.json(), ensure_ascii=False)[:600]
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
print("ArenaSoldOut Discovery")
print("=" * 60)
r = probe("Homepage", "https://arenasoldout.com/")
if r and r.status_code == 200:
    soup = BeautifulSoup(r.text, "lxml")
    # SPA detection
    scripts = [s.get("src","") for s in soup.find_all("script", src=True)]
    print(f"\n  Scripts: {scripts[:5]}")
    next_data = soup.find("script", id="__NEXT_DATA__")
    react = any("react" in s.lower() or "_next" in s.lower() for s in scripts)
    ng = soup.find(attrs={"ng-app": True})
    vue = any("vue" in s.lower() for s in scripts)
    print(f"  Next.js: {bool(next_data)}, React: {react}, Angular: {bool(ng)}, Vue: {vue}")
    # Event links
    elinks = [a["href"] for a in soup.find_all("a", href=True)
              if re.search(r"/event|/shows?|/concerts?|/tickets?", a.get("href",""), re.I)]
    print(f"  Event links: {elinks[:8]}")
    # Check __NEXT_DATA__
    if next_data and next_data.string:
        nd = json.loads(next_data.string)
        print(f"  __NEXT_DATA__ keys: {list(nd.keys())}")
        pp = nd.get("props",{}).get("pageProps",{})
        print(f"  pageProps keys: {list(pp.keys())}")
        print(f"  pageProps[:1000]: {json.dumps(pp, ensure_ascii=False)[:1000]}")

# 2. Philippines browsing
for url in [
    "https://arenasoldout.com/philippines",
    "https://arenasoldout.com/manila",
    "https://arenasoldout.com/events?country=PH",
    "https://arenasoldout.com/events?location=philippines",
    "https://arenasoldout.com/browse?country=PH",
    "https://arenasoldout.com/search?q=philippines",
    "https://arenasoldout.com/search?q=manila",
]:
    r2 = probe(url.split("/")[-1] or url, url)

# 3. API probing
print("\n" + "=" * 60)
print("API probe")
print("=" * 60)
JHEADERS = {"Accept": "application/json, */*"}
for ep in [
    "https://arenasoldout.com/api/events",
    "https://arenasoldout.com/api/events?country=PH",
    "https://arenasoldout.com/api/v1/events",
    "https://arenasoldout.com/api/shows",
    "https://arenasoldout.com/api/concerts",
    "https://api.arenasoldout.com/events",
    "https://arenasoldout.com/api/search?q=manila",
]:
    probe(ep.split("/")[-1], ep, extra_headers=JHEADERS)

# 4. Robots / sitemap
print("\n" + "=" * 60)
print("Robots / Sitemap")
print("=" * 60)
probe("robots.txt", "https://arenasoldout.com/robots.txt")
probe("sitemap.xml", "https://arenasoldout.com/sitemap.xml")

print("\nDone.")
