"""Deep probe of ArenaSoldOut — full wp-toolkit routes + events page AJAX clues."""
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

# 1. Full wp-toolkit routes
print("=" * 60)
print("Full wp-toolkit routes")
print("=" * 60)
r = sess.get(f"{BASE}/wp-json/wp-toolkit/api/", timeout=20)
data = r.json()
routes = data.get("routes", {})
print(f"Total routes: {len(routes)}")
for route in sorted(routes.keys()):
    print(f"  {route}")

# 2. Events page — look for AJAX and JS patterns
print("\n" + "=" * 60)
print("Events page — AJAX / REST API patterns")
print("=" * 60)
r = sess.get(f"{BASE}/events/", timeout=20)
soup = BeautifulSoup(r.text, "lxml")

# Find REST nonce in page
nonce_patterns = re.findall(r'"nonce"\s*:\s*"([^"]{5,})"', r.text)
print(f"REST nonces found: {nonce_patterns[:3]}")

# Find all wp_ajax actions / REST API calls in inline scripts
scripts = [s.string or "" for s in soup.find_all("script") if not s.get("src")]
all_scripts = "\n".join(scripts)

# Look for AJAX admin-ajax.php calls
ajax_calls = re.findall(r'admin-ajax\.php[^"\']*', all_scripts)
print(f"\nAJAX admin-ajax.php calls: {len(ajax_calls)}")
for a in ajax_calls[:5]:
    print(f"  {a[:100]}")

# Look for fetch/axios/XMLHttpRequest with API paths
api_calls = re.findall(r'(?:fetch|axios|xhr|url)[^;{]*?(?:\/api\/|\/wp-json\/)[^;"\'\)]{5,60}', all_scripts, re.I)
print(f"\nAPI call patterns: {len(api_calls)}")
for a in api_calls[:10]:
    print(f"  {a[:120]}")

# Look for elementor-related JS data
elementor_data = re.findall(r'elementorFrontendConfig\s*=\s*(\{.{1,3000})', all_scripts)
print(f"\nElementor frontend config: {bool(elementor_data)}")
if elementor_data:
    try:
        ec = json.loads(elementor_data[0][:5000])
        print(f"  Keys: {list(ec.keys())[:10]}")
    except:
        print(f"  {elementor_data[0][:400]}")

# Look for wp-json REST in localized scripts
rest_patterns = re.findall(r'"rest_url"\s*:\s*"([^"]+)"', r.text)
print(f"\nREST URL from localizations: {rest_patterns}")

# 3. Check all inline script content for event-loading clues
print("\n" + "=" * 60)
print("Inline scripts — event loading patterns")
print("=" * 60)
for i, s in enumerate(scripts):
    if any(kw in s.lower() for kw in ["event", "post", "loop", "product", "category", "ajax"]):
        print(f"\n--- Script {i} (first 500) ---")
        print(s[:500])

# 4. Try WPML language endpoint
print("\n" + "=" * 60)
print("WPML / language-specific URLs")
print("=" * 60)
for url in [
    f"{BASE}/wp-json/wpml/v1/languages",
    f"{BASE}/wp-json/wpml/v1/language_switching",
    f"{BASE}/et/events/",       # Estonian
    f"{BASE}/ru/events/",       # Russian
    f"{BASE}/en/events/",       # English
]:
    r = sess.get(url, timeout=15)
    ct = r.headers.get("Content-Type", "")
    print(f"\n[{url.split('/')[-2] or url.split('/')[-1]}] {r.status_code} | {ct[:40]}")
    try:
        j = r.json()
        print(f"  {json.dumps(j, ensure_ascii=False)[:400]}")
    except:
        print(f"  {r.text[:200]}")

# 5. Try direct wp-toolkit events with fake auth
print("\n" + "=" * 60)
print("wp-toolkit events — try with various approaches")
print("=" * 60)
for url in [
    f"{BASE}/wp-json/wp-toolkit/api/events",
    f"{BASE}/wp-json/wp-toolkit/api/events/list",
    f"{BASE}/wp-json/wp-toolkit/api/events/search",
    f"{BASE}/wp-json/wp-toolkit/api/v1/events",
    f"{BASE}/wp-json/wp-toolkit/api/v2/events",
]:
    r = sess.get(url, timeout=15)
    print(f"\n[{url.split('/api/')[-1]}] {r.status_code}")
    try:
        print(f"  {json.dumps(r.json(), ensure_ascii=False)[:200]}")
    except:
        print(f"  {r.text[:100]}")

# 6. Check if site has PH or Manila content at all
print("\n" + "=" * 60)
print("Philippines content check")
print("=" * 60)
for url in [
    f"{BASE}/events-manila/",
    f"{BASE}/events-philippines/",
    f"{BASE}/manila/",
    f"{BASE}/philippines/",
    f"{BASE}/?s=manila",
    f"{BASE}/?s=philippines",
]:
    r = sess.get(url, timeout=15)
    print(f"\n[{url.split('/')[-2] or url.split('/')[-1]}] {r.status_code} | size={len(r.text)}")
    if r.status_code == 200 and len(r.text) > 1000:
        soup = BeautifulSoup(r.text, "lxml")
        h1 = [h.get_text(strip=True) for h in soup.find_all(["h1","h2"])[:3]]
        print(f"  Headings: {h1}")
