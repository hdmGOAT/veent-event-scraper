"""Test scrapling StealthyFetcher with solve_cloudflare=True against allevents.in."""
import json
from scrapling.fetchers import StealthyFetcher

URL = "https://allevents.in/manila/all"

def test(label, **kwargs):
    print(f"\n=== {label} ===")
    print(f"    {kwargs}")
    try:
        page = StealthyFetcher.fetch(URL, **kwargs)
        blocked = "Just a moment" in (page.html_content or "")
        status = getattr(page, "status", "?")
        size = len(page.html_content or "")
        print(f"  status={status} blocked={blocked} size={size}")
        if not blocked:
            print("  SUCCESS!")
            # Quick event card check
            cards = page.css("[class*='event'], article, .card")
            print(f"  event-class elements: {len(cards)}")
            links = page.css("a[href*='/e/']")
            print(f"  /e/ links: {len(links)}")
            # Save HTML for inspection
            with open(f"allevents-{label.replace(' ','_')}.html", "w", encoding="utf-8") as f:
                f.write(page.html_content or "")
            print(f"  Saved HTML")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")

# Test 1: headless + solve_cloudflare
test("headless_solve_cf", headless=True, solve_cloudflare=True)

# Test 2: headless=False + solve_cloudflare (headed but no window with solve)
test("headed_solve_cf", headless=False, solve_cloudflare=True)
