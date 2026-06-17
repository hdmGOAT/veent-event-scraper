"""Debug script: capture happeningnext.com CDO *event detail* page HTML.

Opens the listing page (solves CF once), then navigates into the first
event card to capture the detail page HTML. Prints all elements whose
class name contains 'organizer', 'host', or 'org' so we can find the
right CSS selector for the organizer profile URL.

Run:
    ../.venv/Scripts/python debug_detail_happeningnext.py
"""
import os, re
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from scrapling.fetchers import StealthyFetcher
from bs4 import BeautifulSoup

BASE_URL = "https://happeningnext.com/cagayan%2Bde%2Boro"
_detail_html = []


def _page_html(page) -> str:
    html = page.content()
    return html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html


def _scrape_detail(page) -> None:
    # 1. Parse listing to find first event link
    soup = BeautifulSoup(_page_html(page), "lxml")
    link_el = soup.select_one(".event-item.card .card-body a[href]")
    if not link_el:
        link_el = soup.select_one(".card-body a[href]")
    if not link_el:
        print("ERROR: no event card link found on listing page")
        return

    detail_url = link_el["href"]
    print(f"Navigating to detail page: {detail_url}")

    page.goto(detail_url, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(2_000)

    html = _page_html(page)
    _detail_html.append(html)
    print(f"Detail page captured: {len(html)} chars")

    # Print organizer-related elements
    detail_soup = BeautifulSoup(html, "lxml")
    print("\n=== Elements with class containing 'organizer', 'host', or 'org' ===")
    for tag in detail_soup.find_all(True):
        classes = " ".join(tag.get("class", []))
        if re.search(r"organizer|host(?!name)|/org/", classes, re.I):
            print(f"  <{tag.name} class='{classes}'> {tag.get_text(strip=True)[:80]!r}")
            if tag.get("href"):
                print(f"    href={tag['href']!r}")

    # Also print any <a> whose href contains /org/
    print("\n=== <a> tags with href containing '/org/' ===")
    for a in detail_soup.find_all("a", href=re.compile(r"/org/")):
        print(f"  href={a['href']!r}  text={a.get_text(strip=True)[:60]!r}")

    # Print raw HTML around .ep-organizer-name
    print("\n=== Context around .ep-organizer-name ===")
    org_el = detail_soup.select_one(".ep-organizer-name")
    if org_el:
        parent = org_el.parent
        grandparent = parent.parent if parent else None
        print("  element:", str(org_el)[:300])
        print("  parent:", str(parent)[:300] if parent else "(none)")
        print("  grandparent:", str(grandparent)[:300] if grandparent else "(none)")
    else:
        print("  .ep-organizer-name NOT FOUND on detail page")


StealthyFetcher.fetch(
    BASE_URL,
    headless=True,
    network_idle=True,
    timeout=90_000,
    solve_cloudflare=True,
    page_action=_scrape_detail,
)

if _detail_html:
    with open("debug_detail_page.html", "w", encoding="utf-8") as f:
        f.write(_detail_html[0])
    print("\nSaved to debug_detail_page.html")
else:
    print("\nNo detail page HTML captured.")
