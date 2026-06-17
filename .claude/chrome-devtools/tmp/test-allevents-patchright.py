"""Test patchright (patched Playwright) against Cloudflare-protected allevents.in."""
import asyncio, json, re
from patchright.async_api import async_playwright

URL = "https://allevents.in/manila/all"

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        )
        page = await context.new_page()

        intercepted_json = []

        async def on_response(resp):
            ct = resp.headers.get("content-type", "")
            if "json" in ct and "allevents" in resp.url:
                try:
                    body = await resp.json()
                    intercepted_json.append({"url": resp.url, "body": body})
                except Exception:
                    pass

        page.on("response", on_response)

        print(f"Navigating to {URL}...")
        await page.goto(URL, wait_until="load", timeout=60_000)

        # Wait for Cloudflare challenge to complete
        print("Waiting for CF challenge...")
        await page.wait_for_timeout(10_000)

        title = await page.title()
        content = await page.content()
        blocked = "Just a moment" in title or "Just a moment" in content

        print(f"Title: {title}")
        print(f"Blocked: {blocked}")
        print(f"Page size: {len(content)}")

        if not blocked:
            print("SUCCESS — Cloudflare bypassed!")
            # Find event links
            links = await page.query_selector_all("a[href*='/e/']")
            print(f"Event links: {len(links)}")

            # Get sample event text
            body_text = await page.evaluate("document.body.innerText")
            print(f"Body preview: {body_text[:500]}")

            print(f"\nIntercepted JSON calls: {len(intercepted_json)}")
            for item in intercepted_json[:3]:
                print(f"  {item['url']}")
                print(f"  {json.dumps(item['body'])[:400]}")
        else:
            # Check if it's Turnstile
            turnstile = "turnstile" in content.lower()
            challenge_type = "Turnstile" if turnstile else "JS challenge"
            print(f"Challenge type: {challenge_type}")
            print(f"Intercepted JSON: {len(intercepted_json)}")

        await browser.close()

asyncio.run(main())
