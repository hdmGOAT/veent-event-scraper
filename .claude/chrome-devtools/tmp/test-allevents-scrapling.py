"""Test scrapling StealthyFetcher against Cloudflare-protected allevents.in."""
import asyncio, json, re
from scrapling.fetchers import StealthyFetcher

async def main():
    fetcher = StealthyFetcher(headless=True)

    cities = [
        ("manila", "https://allevents.in/manila/all"),
        ("cebu", "https://allevents.in/cebu/all"),
        ("cagayan-de-oro", "https://allevents.in/cagayan-de-oro/all"),
    ]

    for slug, url in cities:
        print(f"\n=== {slug} ===")
        try:
            page = await fetcher.async_fetch(url)
            cf_blocked = "Just a moment" in page.html_content or "Cloudflare" in page.html_content
            print(f"  status={page.status}, cf_blocked={cf_blocked}, size={len(page.html_content)}")

            if not cf_blocked:
                # Look for event IDs / links
                event_links = page.css("a[href*='/e/']")
                data_eids = page.css("[data-eid]")
                print(f"  event links: {len(event_links)}, data-eid elements: {len(data_eids)}")
                if event_links:
                    print(f"  sample: {[a.attrib.get('href') for a in event_links[:3]]}")

                # Look for embedded JSON (window.__data__ or similar)
                scripts = page.css("script:not([src])")
                for s in scripts:
                    text = s.text or ""
                    if len(text) > 500 and ("events" in text.lower() or "event_id" in text.lower()):
                        print(f"  JSON script found, len={len(text)}, preview: {text[:300]}")
                        break
            else:
                print(f"  Still blocked. Title: {page.css('title')[0].text if page.css('title') else '?'}")
        except Exception as e:
            print(f"  ERROR: {e}")

    # Also test the internal AJAX API with StealthyFetcher cookies/session
    print("\n=== Internal AJAX API via StealthyFetcher ===")
    # First get cookies by visiting the site
    try:
        base_page = await fetcher.async_fetch("https://allevents.in/manila/all")
        print(f"  Base page status: {base_page.status}, cf_blocked: {'Just a moment' in base_page.html_content}")

        # Try to find AJAX endpoint by looking at page source for API calls
        scripts = base_page.css("script[src]")
        print(f"  External scripts: {[s.attrib.get('src','')[:80] for s in scripts[:5]]}")
    except Exception as e:
        print(f"  ERROR: {e}")

asyncio.run(main())
