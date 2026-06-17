"""Capture all API calls from allevents.in using camoufox; hide Firefox window via ctypes."""
import asyncio, json, ctypes, threading, time
from camoufox.async_api import AsyncCamoufox

URL = "https://allevents.in/manila/all"

def move_firefox_offscreen():
    """Background thread: move Firefox window off-screen after launch (safer than SW_HIDE)."""
    user32 = ctypes.windll.user32
    # Wait for browser to fully initialize before moving
    time.sleep(3)
    for cls in ("MozillaWindowClass", "Navigator"):
        hwnd = user32.FindWindowW(cls, None)
        if hwnd:
            # Move to -10000,-10000 keeping 1920x1080 size — window exists but is invisible
            user32.SetWindowPos(hwnd, 0, -10000, -10000, 1920, 1080, 0)
            print(f"  [moved window off-screen hwnd={hwnd} cls={cls}]")
            return
    print("  [window not found to move]")

async def main():
    print("Starting off-screen mover thread...")
    threading.Thread(target=move_firefox_offscreen, daemon=True).start()

    print("Launching camoufox (headed, window will be hidden)...")
    async with AsyncCamoufox(headless=False) as browser:
        page = await browser.new_page()

        all_responses = []

        async def on_resp(r):
            ct = r.headers.get("content-type", "")
            url = r.url
            if "json" in ct:
                try:
                    body = await r.json()
                    all_responses.append({"url": url, "status": r.status, "body": body})
                    print(f"  [JSON] {r.status} {url[:90]}")
                except Exception:
                    pass

        page.on("response", on_resp)

        print(f"Navigating to {URL}...")
        await page.goto(URL, wait_until="load", timeout=60_000)
        print("Waiting 10s for initial load...")
        await page.wait_for_timeout(10_000)

        print("Scrolling to trigger lazy-loaded events...")
        for _ in range(6):
            await page.evaluate("window.scrollBy(0, 800)")
            await page.wait_for_timeout(1_500)

        await page.wait_for_timeout(5_000)

        title = await page.title()
        content = await page.content()
        print(f"\nTitle: {title}")
        print(f"Page size: {len(content)}")
        print(f"Total JSON responses: {len(all_responses)}")

        # Show all unique API endpoints
        print("\n--- All API endpoints ---")
        for r in all_responses:
            keys = list(r["body"].keys()) if isinstance(r["body"], dict) else "[]"
            print(f"  {r['status']} {r['url'][:100]}  keys={keys}")

        # Deep-inspect event-like responses
        print("\n--- Event data candidates ---")
        for r in all_responses:
            body = r["body"]
            if not isinstance(body, dict):
                continue
            for key in ["data", "events", "items", "results", "list", "eventList"]:
                val = body.get(key)
                if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict):
                    print(f"\n  URL: {r['url'][:100]}")
                    print(f"  [{key}] count={len(val)}")
                    print(f"  [{key}][0] keys: {list(val[0].keys())}")
                    print(f"  [{key}][0]: {json.dumps(val[0])[:600]}")
                    break

        # Event links in DOM
        links = await page.evaluate("""() => {
            const all = Array.from(document.querySelectorAll("a[href]"));
            const ev = all.filter(a => a.href.includes('/e/') || a.href.includes('/event'));
            return ev.slice(0, 5).map(a => ({href: a.href, text: a.innerText.trim().slice(0, 80)}));
        }""")
        print(f"\nEvent-like links: {len(links)}")
        for lnk in links:
            print(f"  {lnk['href']}")

        with open("api-dump.json", "w") as f:
            json.dump([{"url": r["url"], "status": r["status"],
                        "keys": list(r["body"].keys()) if isinstance(r["body"], dict) else None}
                       for r in all_responses], f, indent=2)
        print("\nSaved api-dump.json")

asyncio.run(main())
