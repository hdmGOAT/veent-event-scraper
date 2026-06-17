"""Probe ArenaSoldOut WooCommerce API, events page content, and city pages."""
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

def jp(label, url):
    r = sess.get(url, timeout=20)
    ct = r.headers.get("Content-Type", "")
    print(f"\n[{label}] {r.status_code} | {ct[:40]}")
    try:
        j = r.json()
        print(f"  {json.dumps(j, ensure_ascii=False)[:600]}")
        return r, j
    except:
        print(f"  {r.text[:300]}")
        return r, None

# 1. WooCommerce REST API
print("=" * 60)
print("WooCommerce API")
print("=" * 60)
jp("wc/v3 products", f"{BASE}/wp-json/wc/v3/products?per_page=3")
jp("wc/v3 products PH cat", f"{BASE}/wp-json/wc/v3/products?per_page=5&category=philippines")
jp("wc/v2 products", f"{BASE}/wp-json/wc/v2/products?per_page=3")
jp("wc/v1 products", f"{BASE}/wp-json/wc/v1/products?per_page=3")
jp("wc/v3 categories", f"{BASE}/wp-json/wc/v3/products/categories?per_page=20")

# 2. wp-toolkit/api namespace
jp("wp-toolkit root", f"{BASE}/wp-json/wp-toolkit/api/")
jp("wp-toolkit events", f"{BASE}/wp-json/wp-toolkit/api/events")
jp("wp-toolkit v1", f"{BASE}/wp-json/wp-toolkit/api/v1/events")

# 3. Elementor API
jp("elementor data", f"{BASE}/wp-json/elementor/v1/globals")

# 4. Events page — dump full HTML to see Elementor structure
print("\n" + "=" * 60)
print("Events page HTML structure")
print("=" * 60)
r = sess.get(f"{BASE}/events/", timeout=20)
soup = BeautifulSoup(r.text, "lxml")

# Look for Elementor widgets and dynamic content
elementor_widgets = soup.select("[data-widget_type]")
print(f"Elementor widgets: {len(elementor_widgets)}")
for w in elementor_widgets[:10]:
    print(f"  {w.get('data-widget_type','')} | {str(w)[:150]}")

# WooCommerce product listings
products = soup.select(".product, li.product, .woocommerce-loop-product")
print(f"\nWooCommerce products: {len(products)}")
for p in products[:5]:
    print(f"  {str(p)[:200]}")

# Any links with ticket/event URLs
links = [(a.get_text(strip=True)[:50], a["href"])
         for a in soup.find_all("a", href=True)
         if re.search(r"ticket|event|concert|show|product", a.get("href",""), re.I)
         and "arenasoldout.com" in a.get("href","")]
print(f"\nTicket/event/product links: {len(links)}")
for name, href in links[:10]:
    print(f"  {name!r} -> {href}")

# Dump #content or main div
main = soup.find("main") or soup.find("div", id="content") or soup.find("div", id="primary")
if main:
    print(f"\nMain content (first 2000):")
    print(str(main)[:2000])

# 5. Check events-prague page for structure clues
print("\n" + "=" * 60)
print("Events-Prague page (checking city event page structure)")
print("=" * 60)
r2 = sess.get(f"{BASE}/events-prague/", timeout=20)
soup2 = BeautifulSoup(r2.text, "lxml")
print(f"Status: {r2.status_code} | Size: {len(r2.text)}")
main2 = soup2.find("main") or soup2.find("div", id="content")
if main2:
    print(str(main2)[:2000])

# 6. Check shop page for event products
print("\n" + "=" * 60)
print("Shop page")
print("=" * 60)
r3 = sess.get(f"{BASE}/shop/", timeout=20)
soup3 = BeautifulSoup(r3.text, "lxml")
products3 = soup3.select("li.product")
print(f"Products: {len(products3)}")
for p in products3[:5]:
    name_tag = p.find(class_="woocommerce-loop-product__title")
    price_tag = p.find(class_="price")
    link_tag = p.find("a", href=True)
    print(f"  {name_tag.get_text(strip=True) if name_tag else '?'} | {price_tag.get_text(strip=True) if price_tag else '?'} | {link_tag['href'] if link_tag else '?'}")
