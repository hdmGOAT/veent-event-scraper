"""
Test camoufox headless with disable_coop + humanize against allevents.in Turnstile.
disable_coop: allows Turnstile iframe element interaction.
humanize: simulates real cursor movement.
"""
import asyncio, json
from camoufox.async_api import AsyncCamoufox

URL = "https://allevents.in/manila/all"

async def test(label, **kwargs):
    print(f"\n=== {label} ===")
    print(f"    opts: {kwargs}")
    try:
        async with AsyncCamoufox(**kwargs) as b:
            p = await b.new_page()
            calls = []

            async def on_resp(resp):
                ct = resp.headers.get("content-type", "")
                if "json" in ct and "allevents" in resp.url:
                    try:
                        body = await resp.json()
                        calls.append({"url": resp.url, "body": body})
                    except Exception:
                        pass

            p.on("response", on_resp)

            try:
                await p.goto(URL, wait_until="load", timeout=60_000)
            except Exception as e:
                print(f"  goto error: {e}")
                return

            # Poll for up to 30s
            for i in range(15):
                await asyncio.sleep(2)
                try:
                    title = await p.title()
                except Exception:
                    print(f"  [{i*2}s] page closed")
                    return
                blocked = "Just a moment" in title
                print(f"  [{i*2}s] title={title[:50]!r} blocked={blocked}")
                if not blocked:
                    break

            try:
                title = await p.title()
                content = await p.content()
            except Exception:
                print("  page closed after poll")
                return

            blocked = "Just a moment" in title
            print(f"  RESULT: blocked={blocked} size={len(content)} calls={len(calls)}")

            if not blocked:
                print("  SUCCESS — Turnstile bypassed headlessly!")
                for c in calls[:3]:
                    body = c["body"]
                    keys = list(body.keys()) if isinstance(body, dict) else "?"
                    print(f"  api: {c['url'][:80]}  keys={keys}")
    except Exception as e:
        print(f"  launch error: {e}")


async def main():
    # Try 1: headless + disable_coop
    await test("headless + disable_coop",
               headless=True, disable_coop=True)

    # Try 2: headless + disable_coop + humanize
    await test("headless + disable_coop + humanize",
               headless=True, disable_coop=True, humanize=True)

    # Try 3: headed but 1x1 window (nearly invisible)
    await test("headed window=(1,1)",
               headless=False, window=(1, 1))

asyncio.run(main())
