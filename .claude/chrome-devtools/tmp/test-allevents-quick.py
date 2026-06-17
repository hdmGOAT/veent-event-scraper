"""
Bypass check + API capture for allevents.in.
Uses firefox_user_prefs to start window off-screen from the beginning.
"""
import asyncio, json
from camoufox.async_api import AsyncCamoufox

URL = "https://allevents.in/manila/all"

# Move window off-screen via Firefox preferences — no runtime ctypes needed
OFFSCREEN_PREFS = {
    "browser.window.x": -10000,
    "browser.window.y": -10000,
    "browser.window.width": 1920,
    "browser.window.height": 1080,
}

async def main():
    print("Launching camoufox (window off-screen via prefs)...")
    async with AsyncCamoufox(headless=False, firefox_user_prefs=OFFSCREEN_PREFS) as b:
        p = await b.new_page()
        calls = []

        async def on_resp(resp):
            ct = resp.headers.get("content-type", "")
            if "json" in ct and "allevents" in resp.url:
                try:
                    body = await resp.json()
                    calls.append({"url": resp.url, "body": body})
                    print(f"  [json] {resp.url[:90]}")
                except Exception:
                    pass

        p.on("response", on_resp)

        try:
            await p.goto(URL, wait_until="load", timeout=60_000)
        except Exception as e:
            print(f"goto error: {e}")
            return

        # Wait for Turnstile with graceful error handling
        for step in range(12):
            try:
                await asyncio.sleep(2)
                title = await p.title()
                blocked = "Just a moment" in title
                print(f"  [{step*2}s] title={title[:50]} blocked={blocked}")
                if not blocked:
                    break
            except Exception:
                print(f"  [{step*2}s] page closed")
                break

        try:
            title = await p.title()
        except Exception:
            print("Page closed — could not get title")
            return

        blocked = "Just a moment" in title
        content = await p.content()
        print(f"\ntitle: {title[:80]}")
        print(f"blocked: {blocked}, size={len(content)}, json_calls={len(calls)}")

        if blocked:
            return

        # Scroll slowly to trigger lazy-loaded event data
        for i in range(5):
            try:
                await p.evaluate("window.scrollBy(0, 800)")
                await asyncio.sleep(2)
                print(f"  scrolled {i+1}/5")
            except Exception:
                print(f"  scroll {i+1} — page closed")
                break

        await asyncio.sleep(3)

        # Show API calls
        print(f"\n--- JSON API calls ({len(calls)}) ---")
        for c in calls:
            body = c["body"]
            keys = list(body.keys()) if isinstance(body, dict) else "?"
            print(f"\n  URL: {c['url']}")
            print(f"  keys: {keys}")
            if isinstance(body, dict):
                for k in ["data", "events", "items", "results", "list", "eventList"]:
                    v = body.get(k)
                    if isinstance(v, list) and v:
                        print(f"  [{k}] count={len(v)}")
                        if isinstance(v[0], dict):
                            print(f"  [{k}][0] keys: {list(v[0].keys())}")
                            print(f"  [{k}][0]: {json.dumps(v[0])[:500]}")
                        break

        # Save full dump
        with open("api-dump.json", "w") as f:
            json.dump([{"url": c["url"], "keys": list(c["body"].keys()) if isinstance(c["body"], dict) else None}
                       for c in calls], f, indent=2)
        print("\nSaved api-dump.json")

asyncio.run(main())
