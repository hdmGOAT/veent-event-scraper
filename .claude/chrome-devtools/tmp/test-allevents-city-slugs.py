"""Find correct allevents.in city URL slugs for Philippine cities using Playwright stealth."""
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

CANDIDATES = [
    "manila",
    "metro-manila",
    "national-capital-region",
    "quezon-city",
    "cebu",
    "cebu-city",
    "davao",
    "davao-city",
    "cagayan-de-oro",
    "philippines",
]

results = {}

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    for slug in CANDIDATES:
        context = browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ))
        page = context.new_page()
        Stealth().use_sync(page)
        url = f"https://allevents.in/{slug}/all"
        try:
            page.goto(url, wait_until="load", timeout=60_000)
            page.wait_for_timeout(6_000)
            title = page.title()
            final_url = page.url
            # Check for event cards
            cards = page.query_selector_all("[class*='event']") or []
            results[slug] = {
                "status": "ok",
                "title": title,
                "final_url": final_url,
                "event_elements": len(cards),
            }
        except Exception as e:
            results[slug] = {"status": "error", "error": str(e)[:100]}
        finally:
            context.close()
    browser.close()

for slug, info in results.items():
    print(f"{slug}: {info}")
