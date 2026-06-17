"""Analyze saved allevents.in HTML to find event card selectors and data fields."""
import json, sys
sys.stdout.reconfigure(encoding="utf-8")
from bs4 import BeautifulSoup

with open("allevents-headless_solve_cf.html", encoding="utf-8") as f:
    soup = BeautifulSoup(f, "lxml")

# Find unique class names containing 'event'
all_ev = soup.select("[class*='event']")
print(f"All [class*=event]: {len(all_ev)}")
classes = set()
for el in all_ev:
    for c in (el.get("class") or []):
        if "event" in c.lower():
            classes.add(c)
print("Event class names:", sorted(classes))

# Try specific card selectors
for sel in ["[class*='event-item']", "[class*='event-card']", "[class*='EventCard']",
            "[class*='eventcard']", "[class*='event-box']", "[class*='event-tile']"]:
    found = soup.select(sel)
    if found:
        print(f"\n{sel}: {len(found)}")
        print(f"  First card ({len(str(found[0]))} chars):")
        print(str(found[0])[:1000])
        break

# Find all anchor tags with event-like hrefs
links = soup.find_all("a", href=True)
ev_links = [a for a in links if "/e/" in a.get("href", "") or "/event/" in a.get("href", "")]
print(f"\nEvent anchor links: {len(ev_links)}")
for lnk in ev_links[:5]:
    print(f"  {lnk.get('href')} — {lnk.get_text(strip=True)[:60]}")

# Look for JSON-LD structured data
scripts = soup.find_all("script", type="application/ld+json")
print(f"\nJSON-LD scripts: {len(scripts)}")
for sc in scripts[:3]:
    try:
        data = json.loads(sc.string)
        print(f"  type: {data.get('@type')} keys: {list(data.keys())}")
        if data.get("@type") in ("Event", "ItemList"):
            print(f"  {json.dumps(data)[:600]}")
    except Exception:
        pass

# Look for any script tags with event data
import re
for sc in soup.find_all("script"):
    txt = sc.string or ""
    if "event" in txt.lower() and len(txt) > 200:
        m = re.search(r'"name"\s*:\s*"([^"]{5,60})"', txt)
        if m:
            print(f"\nScript with event data (preview): ...{txt[max(0,m.start()-20):m.start()+100]}...")
            break
