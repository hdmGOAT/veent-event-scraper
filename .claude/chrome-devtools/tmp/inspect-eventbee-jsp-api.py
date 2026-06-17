"""Test Eventbee JSP API endpoints found in AngularJS controller."""
import requests, re, sys, time

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://www.eventbee.com"
EID = "238729652"
T = int(time.time() * 1000)  # millisecond timestamp

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*",
    "Referer": f"https://www.eventbee.com/v/cyber-revolution-summit-philippines/event?eid={EID}",
    "X-Requested-With": "XMLHttpRequest",
}

jsps = [
    f"/getEventMetaData.jsp?t={T}&eid={EID}",
    f"/getEventTickets.jsp?t={T}&eid={EID}",
    f"/getSeatingInfo.jsp?t={T}&eid={EID}",
    f"/PriorityRegBlock.jsp?t={T}&eid={EID}",
    # Try with https too
    f"/getEventMetaData.jsp?eid={EID}",
    f"/getEventTickets.jsp?eid={EID}",
]

for path in jsps:
    url = BASE + path
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        ct = r.headers.get("Content-Type", "")
        print(f"\n{r.status_code} | {ct[:40]} | {path[:60]}")
        try:
            j = r.json()
            print(f"  JSON keys: {list(j.keys())[:10] if isinstance(j, dict) else str(j)[:200]}")
        except:
            print(f"  Body: {r.text[:300]}")
    except Exception as e:
        print(f"  ERROR: {e}")

# Also try HTTPS base
print("\n--- HTTPS base ---")
BASE2 = "https://www.eventbee.com"
for path in [f"/getEventMetaData.jsp?t={T}&eid={EID}",
             f"/getEventTickets.jsp?t={T}&eid={EID}"]:
    url = BASE2 + path
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        print(f"\n{r.status_code} | {r.headers.get('Content-Type','')[:40]} | {path[:60]}")
        try:
            j = r.json()
            import json
            print(f"  {json.dumps(j, ensure_ascii=False)[:500]}")
        except:
            print(f"  Body: {r.text[:400]}")
    except Exception as e:
        print(f"  ERROR: {e}")
