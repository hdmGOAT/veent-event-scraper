"""Check TicketMelon __NEXT_DATA__ event keys — is price in there?"""
import sys, requests, json, re
from bs4 import BeautifulSoup
import urllib3; urllib3.disable_warnings()
sys.stdout.reconfigure(encoding="utf-8")

sess = requests.Session()
sess.verify = False
sess.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; EventScraper/1.0)",
    "Accept": "text/html,*/*",
})

# Fetch a known PH event URL
r = sess.get("https://www.ticketmelon.com/sitemap.xml", timeout=20)
sitemap_urls = re.findall(r"<loc>([^<]+)</loc>", r.text)
event_url = None
for sm in sitemap_urls:
    rs = sess.get(sm, timeout=20)
    locs = re.findall(r"<loc>([^<]+)</loc>", rs.text)
    if locs:
        event_url = locs[0]
        break

print(f"Probing: {event_url}")
r2 = sess.get(event_url, timeout=25)
soup = BeautifulSoup(r2.text, "lxml")
nd_tag = soup.find("script", id="__NEXT_DATA__")
if not nd_tag:
    print("No __NEXT_DATA__")
else:
    nd = json.loads(nd_tag.string)
    ev = nd.get("props", {}).get("pageProps", {}).get("event") or {}
    print(f"Event name: {ev.get('name')}")
    print(f"Currency: {ev.get('currency')}")
    print(f"\nAll top-level keys: {list(ev.keys())}")
    # Look for price-related keys
    price_keys = {k: v for k, v in ev.items()
                  if any(p in k.lower() for p in ["price", "ticket", "cost", "fee", "rate", "amount"])}
    print(f"\nPrice-related keys: {json.dumps(price_keys, ensure_ascii=False, default=str)[:2000]}")
    # Ticket types if present
    if "ticket_types" in ev:
        print(f"\nticket_types: {json.dumps(ev['ticket_types'], ensure_ascii=False, default=str)[:1000]}")
