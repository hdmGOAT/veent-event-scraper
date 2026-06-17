"""Test camoufox (patched Firefox) against allevents.in Cloudflare Turnstile."""
import asyncio, json
from camoufox.async_api import AsyncCamoufox

URL = "https://allevents.in/manila/all"

async def main():
    print("Launching camoufox (headless Firefox)...")
    async with AsyncCamoufox(headless=True) as browser:
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

        print(f"Navigating to {URL}...")
        await page.goto(URL, wait_until="load", timeout=60_000)
        print("Waiting 12s for Turnstile challenge...")
        await page.wait_for_timeout(12_000)

        title = await page.title()
        content = await page.content()
        blocked = "Just a moment" in title or "Just a moment" in content

        print(f"Title: {title[:80]}")
        print(f"Blocked: {blocked}")
        print(f"Size: {len(content)}")
        print(f"Intercepted JSON: {len(intercepted)}")

        if not blocked:
            print("\nSUCCESS — Turnstile bypassed!")
            links = await page.query_selector_all("a[href*='/e/']")
            print(f"Event links on page: {len(links)}")

            for item in intercepted[:3]:
                print(f"\nAPI call: {item['url'][:100]}")
                body = item["body"]
                events = body.get("data") or body.get("events") or body.get("items") or body.get("results") or []
                print(f"  keys: {list(body.keys())}")
                print(f"  event count: {len(events)}")
                if events and isinstance(events, list):
                    print(f"  first event keys: {list(events[0].keys()) if isinstance(events[0], dict) else events[0]}")
                    print(f"  first event: {json.dumps(events[0])[:500]}")
        else:
            print("\nStill blocked.")
            print(f"Turnstile present: {'turnstile' in content.lower()}")

asyncio.run(main())
