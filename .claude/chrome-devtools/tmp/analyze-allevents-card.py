"""Extract one full event card structure from allevents.in HTML."""
import sys, json
sys.stdout.reconfigure(encoding="utf-8")
from bs4 import BeautifulSoup

with open("allevents-headless_solve_cf.html", encoding="utf-8") as f:
    soup = BeautifulSoup(f, "lxml")

cards = soup.select("li.event-card")
print(f"Total event cards: {len(cards)}")

# Print first 3 cards fully to understand all fields
for i, card in enumerate(cards[:3]):
    print(f"\n{'='*60}")
    print(f"CARD {i+1}")
    print(f"{'='*60}")
    # Key attributes on li
    print(f"data-eid    : {card.get('data-eid')}")
    print(f"data-link   : {card.get('data-link')}")
    print(f"data-external: {card.get('data-external')}")

    # Image
    img = card.select_one("img.banner-img")
    if img:
        print(f"title(alt)  : {img.get('alt')}")
        print(f"image_url   : {img.get('src')}")

    # Title element
    for sel in [".event-title-v3", ".event-title", "[class*='title']"]:
        t = card.select_one(sel)
        if t:
            print(f"title({sel}): {t.get_text(strip=True)[:80]}")
            break

    # Date
    for sel in [".event-date-v3", ".event-date-section", "[class*='date']"]:
        d = card.select_one(sel)
        if d:
            print(f"date({sel})  : {d.get_text(strip=True)[:80]}")
            break

    # Venue / location
    for sel in ["[class*='venue']", "[class*='location']", "[class*='place']", ".event-meta-container"]:
        v = card.select_one(sel)
        if v:
            print(f"venue({sel}) : {v.get_text(strip=True)[:80]}")
            break

    # Category
    for sel in ["[class*='category']", "[class*='tag']", "[class*='type']"]:
        c2 = card.select_one(sel)
        if c2:
            print(f"cat({sel})   : {c2.get_text(strip=True)[:60]}")
            break

    # Price
    for sel in ["[class*='price']", "[class*='cost']", "[class*='ticket']"]:
        p = card.select_one(sel)
        if p:
            print(f"price({sel}) : {p.get_text(strip=True)[:60]}")
            break

    # All text in card
    print(f"full text   : {card.get_text(' | ', strip=True)[:200]}")
