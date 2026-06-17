"""Test scrapling DynamicFetcher and correct StealthyFetcher API against allevents.in."""
import asyncio
from scrapling.fetchers import StealthyFetcher, DynamicFetcher

URL = "https://allevents.in/manila/all"

async def test_stealthy():
    print("=== StealthyFetcher (Camoufox) ===")
    try:
        StealthyFetcher.configure(headless=True)
        page = await StealthyFetcher.async_fetch(URL)
        blocked = "Just a moment" in (page.html_content or "")
        print(f"  status={page.status}, blocked={blocked}, size={len(page.html_content or '')}")
        if not blocked:
            links = page.css("a[href*='/e/']")
            print(f"  event links: {len(links)}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")

async def test_dynamic():
    print("\n=== DynamicFetcher (Playwright) ===")
    try:
        fetcher = DynamicFetcher(headless=True)
        page = await fetcher.async_fetch(URL, wait=8000)
        blocked = "Just a moment" in (page.html_content or "")
        print(f"  status={page.status}, blocked={blocked}, size={len(page.html_content or '')}")
        if not blocked:
            links = page.css("a[href*='/e/']")
            print(f"  event links: {len(links)}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")

# Also check scrapling API surface
print("=== StealthyFetcher methods ===")
print([m for m in dir(StealthyFetcher) if not m.startswith("_")])

async def main():
    await test_stealthy()
    await test_dynamic()

asyncio.run(main())
