"""Debug script: dump allevents.in page HTML, screenshot, and intercepted JSON."""
import json
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

BASE_URL = "https://allevents.in/cagayan-de-oro/all"

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    )
    page = context.new_page()
    Stealth(chrome_runtime=True).use_sync(page)

    intercepted = []

    def on_response(response):
        if "allevents.in" not in response.url:
            return
        ct = response.headers.get("content-type", "")
        if "json" in ct and response.status == 200:
            try:
                data = response.json()
                print(f"[JSON] {response.url[:120]}")
                intercepted.append({"url": response.url, "data": data})
            except Exception as e:
                print(f"[JSON parse error] {response.url}: {e}")

    page.on("response", on_response)

    print(f"Navigating to {BASE_URL} ...")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=90_000)
    print("Waiting for Cloudflare challenge to complete...")
    try:
        # Wait up to 30s for the title to change from the CF interstitial
        page.wait_for_function(
            "document.title !== 'Just a moment...'",
            timeout=30_000,
        )
    except Exception:
        pass
    page.wait_for_timeout(3_000)
    print(f"Current URL: {page.url}")
    print(f"Page title: {page.title()}")

    # Scroll a bit
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(3_000)

    html = page.content()
    page.screenshot(path="debug_screenshot.png", full_page=True)
    browser.close()

# Save outputs
with open("debug_page.html", "w", encoding="utf-8") as f:
    f.write(html)
print(f"\nHTML saved to debug_page.html ({len(html)} chars)")
print(f"Screenshot saved to debug_screenshot.png")
print(f"Intercepted JSON responses: {len(intercepted)}")

for i, item in enumerate(intercepted):
    fname = f"debug_json_{i}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(item, f, indent=2, default=str)
    print(f"  [{i}] {item['url'][:100]} → {fname}")

# Quick check: does the HTML look like events or CF challenge?
if "Just a moment" in html or "cf-challenge" in html.lower():
    print("\nWARNING: Still seeing Cloudflare challenge page!")
elif "event" in html.lower():
    print("\nOK: HTML appears to contain event content")
else:
    print("\n?: HTML does not obviously contain events — check debug_page.html")
