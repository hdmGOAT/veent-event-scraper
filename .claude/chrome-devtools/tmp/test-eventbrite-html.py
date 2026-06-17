import requests, json
from bs4 import BeautifulSoup

headers = {"User-Agent": "Mozilla/5.0 (compatible; EventScraper/1.0)"}
resp = requests.get(
    "https://www.eventbrite.com/d/philippines--manila/all-events/",
    headers=headers, timeout=20
)
print("Status:", resp.status_code)
print("Content-Length:", len(resp.text))

soup = BeautifulSoup(resp.text, "lxml")
ld_scripts = soup.find_all("script", type="application/ld+json")
print("LD+JSON scripts found:", len(ld_scripts))

for i, s in enumerate(ld_scripts):
    try:
        raw = s.string or ""
        data = json.loads(raw)
        items = None
        if isinstance(data, dict) and "itemListElement" in data:
            items = data["itemListElement"]
        elif isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict) and "itemListElement" in entry:
                    items = entry["itemListElement"]
                    break
        if items is not None:
            print(f"\nScript {i}: {len(items)} events in itemListElement")
            if items:
                first = items[0].get("item", items[0])
                print("Keys:", list(first.keys()))
                print(json.dumps(first, indent=2)[:2000])
        else:
            tp = data.get("@type") if isinstance(data, dict) else type(data).__name__
            print(f"Script {i}: @type={tp}")
    except Exception as e:
        print(f"Script {i}: error {e}")
