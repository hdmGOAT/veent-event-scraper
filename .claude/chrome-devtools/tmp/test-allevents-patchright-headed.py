"""Test patchright headed + headless with extra args against allevents.in Turnstile."""
import asyncio, json
from patchright.async_api import async_playwright

URL = "https://allevents.in/manila/all"

async def test(label, headless, extra_args=None):
    print(f"\n=== {label} (headless={headless}) ===")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=extra_args or [],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = await context.new_page()

        intercepted = []
        async def on_resp(r):
            ct = r.headers.get("content-type", "")
            if "json" in ct and "allevents" in r.url:
                try:
                    body = await r.json()
                    intercepted.append({"url": r.url, "body": body})
                except Exception:
                    pass
        page.on("response", on_resp)

        await page.goto(URL, wait_until="load", timeout=60_000)
        await page.wait_for_timeout(12_000)

        title = await page.title()
        blocked = "Just a moment" in title
        content = await page.content()

        print(f"  title: {title[:60]}")
        print(f"  blocked: {blocked}, size: {len(content)}")
        print(f"  intercepted JSON: {len(intercepted)}")

        if not blocked:
            print("  SUCCESS!")
            links = await page.query_selector_all("a[href*='/e/']")
            print(f"  event links: {len(links)}")
            for item in intercepted[:2]:
                print(f"  API: {item['url'][:80]}")
                body = item["body"]
                items = body.get("data") or body.get("events") or body.get("items") or []
                print(f"    items: {len(items)}, keys: {list(body.keys())}")
                if items:
                    print(f"    first: {json.dumps(items[0])[:300]}")

        await browser.close()

async def main():
    # Test 1: headed (should work if patchright can bypass at all)
    await test("Headed", headless=False)
    # Test 2: headless with --disable-blink-features
    await test("Headless + disable-blink-features", headless=True, extra_args=[
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-setuid-sandbox",
    ])

asyncio.run(main())
