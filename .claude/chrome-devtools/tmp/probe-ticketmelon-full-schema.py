"""Dump complete event JSON for a Philippines event to see all fields."""
import requests, json, sys
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")
import urllib3; urllib3.disable_warnings()

sess = requests.Session()
sess.verify = False
sess.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
})

r = sess.get("https://www.ticketmelon.com/bbe/lullaboymanila", timeout=20)
soup = BeautifulSoup(r.text, "lxml")
nd = json.loads(soup.find("script", id="__NEXT_DATA__").string)
event = nd["props"]["pageProps"]["event"]

# Print full event — all keys and values (truncate long strings)
print("=== All event keys ===")
def summarize(val, depth=0):
    if isinstance(val, dict):
        return {k: summarize(v, depth+1) for k, v in val.items()}
    elif isinstance(val, list):
        if not val:
            return []
        return [summarize(val[0], depth+1), f"...({len(val)} items)"] if len(val) > 1 else [summarize(val[0], depth+1)]
    elif isinstance(val, str) and len(val) > 200:
        return val[:200] + "..."
    return val

print(json.dumps(summarize(event), ensure_ascii=False, indent=2))

print("\n=== ticket_type field ===")
print(json.dumps(event.get("ticket_type", "NOT FOUND"), ensure_ascii=False, indent=2)[:3000])

print("\n=== eo_profile field ===")
print(json.dumps(event.get("eo_profile", "NOT FOUND"), ensure_ascii=False, indent=2)[:2000])

print("\n=== venue field ===")
print(json.dumps(event.get("venue", "NOT FOUND"), ensure_ascii=False, indent=2))

print("\n=== timestamps ===")
import datetime
start_ms = event.get("show_starttime", 0)
end_ms = event.get("show_endtime", 0)
tz = event.get("timezone", {})
print(f"show_starttime: {start_ms} -> {datetime.datetime.fromtimestamp(start_ms/1000, tz=datetime.timezone.utc)}")
print(f"show_endtime:   {end_ms} -> {datetime.datetime.fromtimestamp(end_ms/1000, tz=datetime.timezone.utc)}")
print(f"timezone: {tz}")
print(f"currency: {event.get('currency')}")
print(f"categories: {event.get('categories')}")
print(f"tag: {event.get('tag')}")
print(f"eo_slug: {event.get('eo_slug')}")
print(f"event_id: {event.get('event_id')}")
print(f"img_poster: {event.get('img_poster','')[:80]}")
print(f"img_banner: {event.get('img_banner','')[:80]}")
