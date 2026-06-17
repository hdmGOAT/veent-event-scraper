"""Test camoufox headed mode + longer wait against allevents.in Turnstile."""
import asyncio, json
from camoufox.async_api import AsyncCamoufox

URL = "https://allevents.in/manila/all"

async def test(label, headless, humanize=False):
    print(f"\n=== {label} headless={headless} humanize={humanize} ===")
    kwargs = {"headless": headless}
    if humanize:
        kwargs["humanize"] = True
    async with AsyncCamoufox(**kwargs) as browser:
        page = await browser.new_page()

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
        print("Waiting 20s for Turnstile challenge...")
        await page.wait_for_timeout(20_000)

        title = await page.title()
        content = await page.content()
        blocked = "Just a moment" in title or "Just a moment" in content

        print(f"Title: {title[:80]}")
        print(f"Blocked: {blocked}")
        print(f"Size: {len(content)}")
        print(f"Intercepted JSON: {len(intercepted)}")

        if not blocked:
            print("SUCCESS — Turnstile bypassed!")
            links = await page.query_selector_all("a[href*='/e/']")
            print(f"Event links: {len(links)}")
            for item in intercepted[:2]:
                print(f"\nAPI: {item['url'][:100]}")
                body = item["body"]
                events = body.get("data") or body.get("events") or body.get("items") or body.get("results") or []
                print(f"  keys: {list(body.keys())}")
                print(f"  events: {len(events)}")
                if events and isinstance(events, list) and isinstance(events[0], dict):
                    print(f"  first keys: {list(events[0].keys())}")
                    print(f"  first: {json.dumps(events[0])[:400]}")
        else:
            print("Still blocked.")

async def main():
    # Try headless with humanize
    await test("Headless+humanize", headless=True, humanize=True)
    # Try headed (visible)
    await test("Headed", headless=False)

asyncio.run(main())
