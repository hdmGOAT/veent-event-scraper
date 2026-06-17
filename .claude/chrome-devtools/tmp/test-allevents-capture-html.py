"""
Capture allevents.in page HTML + all API calls after successful Turnstile bypass.
Saves raw HTML to allevents-manila.html for structure analysis.
"""
import asyncio, json
from camoufox.async_api import AsyncCamoufox

URL = "https://allevents.in/manila/all"

async def main():
    print("Launching camoufox headed...")
    async with AsyncCamoufox(headless=False) as b:
        p = await b.new_page()
        calls = []

        async def on_resp(resp):
            ct = resp.headers.get("content-type", "")
            if "json" in ct:
                try:
                    body = await resp.json()
                    calls.append({"url": resp.url, "body": body})
                except Exception:
                    pass

        p.on("response", on_resp)

        await p.goto(URL, wait_until="load", timeout=60_000)

        # Poll until bypass or 30s
        for i in range(15):
            await asyncio.sleep(2)
            try:
                title = await p.title()
            except Exception:
                print(f"  [{i*2}s] page closed")
                return
            blocked = "Just a moment" in title
            print(f"  [{i*2}s] {title[:60]!r} blocked={blocked}")
            if not blocked:
                break

        title = await p.title()
        blocked = "Just a moment" in title
        if blocked:
            print("Still blocked after 30s — IP rate-limited, try later")
            return

        # Scroll to trigger lazy content
        for _ in range(6):
            await p.evaluate("window.scrollBy(0, 800)")
            await asyncio.sleep(1.5)

        await asyncio.sleep(3)

        content = await p.content()
        print(f"\nPage size: {len(content)}")

        # Save full HTML
        with open("allevents-manila.html", "w", encoding="utf-8") as f:
            f.write(content)
        print("Saved allevents-manila.html")

        # Show all JSON calls
        print(f"\n--- JSON API calls ({len(calls)}) ---")
        for c in calls:
            body = c["body"]
            print(f"  {c['url'][:90]}")
            if isinstance(body, dict):
                print(f"    keys: {list(body.keys())}")

        # Quick DOM analysis
        result = await p.evaluate("""() => {
            // Look for event cards by common patterns
            const cards = document.querySelectorAll('[class*="event"], [class*="Event"], article, .card, [class*="item"]');
            const eventLinks = Array.from(document.querySelectorAll('a[href]'))
                .filter(a => /\\/e\\/|event|\\d{4}/.test(a.href))
                .slice(0, 5)
                .map(a => a.href);
            const h3s = Array.from(document.querySelectorAll('h3, h2')).slice(0, 8).map(h => h.innerText.trim());
            return {
                cardCount: cards.length,
                eventLinks,
                headings: h3s,
                bodyClasses: Array.from(document.body.classList)
            };
        }""")
        print(f"\nDOM analysis: {json.dumps(result, indent=2)}")

asyncio.run(main())
