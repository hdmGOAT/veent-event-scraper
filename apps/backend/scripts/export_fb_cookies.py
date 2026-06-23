"""One-time Facebook cookie export helper.

Opens a visible browser window on the Facebook login page. Log in manually.
The script auto-detects when you're logged in (watches for the 'c_user' cookie)
and saves your session cookies to a JSON file the facebook_posts scraper can use.

Run from a visible terminal (not Claude Code):
    cd apps/backend
    python scripts/export_fb_cookies.py

Then add to apps/backend/.env:
    FB_COOKIES_FILE=scripts/fb_cookies.json
"""

import glob
import json
import os
import sys
import time

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Try Windows path first, then Linux/macOS path
_venv_root = os.path.join(BACKEND_DIR, "..", "..", ".venv")
_candidates = [
    os.path.join(_venv_root, "Lib", "site-packages"),          # Windows
    os.path.join(_venv_root, "lib", "site-packages"),           # Linux/macOS (some)
]
_candidates += glob.glob(os.path.join(_venv_root, "lib", "python*", "site-packages"))
for VENV_SITE in _candidates:
    if os.path.isdir(VENV_SITE):
        sys.path.insert(0, os.path.abspath(VENV_SITE))
        break

from playwright.sync_api import sync_playwright

DEFAULT_OUT = os.path.join(os.path.dirname(__file__), "fb_cookies.json")
WAIT_SECONDS = 180  # 3 minutes to log in


def main():
    out_path = os.path.abspath(DEFAULT_OUT)

    print("=" * 60)
    print("Facebook Cookie Export Helper")
    print("=" * 60)
    print()
    print("A browser window will open. Log in to Facebook in it.")
    print(f"The script auto-saves cookies once it detects login (up to {WAIT_SECONDS}s).")
    print()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=["--no-first-run", "--no-default-browser-check"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        page = context.new_page()
        page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=30_000)
        print("Browser is open. Log in to Facebook now...")
        print()

        # Poll until c_user cookie (FB session ID) appears — up to WAIT_SECONDS
        logged_in = False
        for elapsed in range(WAIT_SECONDS):
            cookies = context.cookies(["https://www.facebook.com"])
            if any(c["name"] == "c_user" for c in cookies):
                logged_in = True
                print(f"  Login detected after {elapsed}s!")
                break
            if elapsed % 10 == 0 and elapsed > 0:
                print(f"  Still waiting... {WAIT_SECONDS - elapsed}s remaining")
            time.sleep(1)

        if not logged_in:
            print("ERROR: Login not detected within the timeout. Re-run and try again.")
            browser.close()
            sys.exit(1)

        # Small grace period for FB to set all session cookies
        time.sleep(3)
        all_cookies = context.cookies(["https://www.facebook.com"])
        fb_cookies = [c for c in all_cookies if "facebook.com" in c.get("domain", "")]

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(fb_cookies, f, indent=2)

        print(f"Saved {len(fb_cookies)} cookies → {out_path}")
        print()
        print("Next steps:")
        print("  1. Add to apps/backend/.env:")
        print(f"       FB_COOKIES_FILE={out_path}")
        print("  2. Run the scraper:")
        print("       python manage.py scrape facebook_posts --max-events 3")
        print()

        browser.close()


if __name__ == "__main__":
    main()
