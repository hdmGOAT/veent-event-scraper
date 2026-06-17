"""Inspect Eventbee search result HTML and event detail page fields."""
import requests, re, sys
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.eventbee.com/search",
    "Origin": "https://www.eventbee.com",
    "X-Requested-With": "XMLHttpRequest",
}

# Dump search result HTML
print("=== search!searchResult HTML dump ===")
r = requests.post("https://www.eventbee.com/search!searchResult",
                  headers=HEADERS,
                  data={"searchcontent": "manila"}, timeout=20)
print(f"Status: {r.status_code} | Size: {len(r.text)}")
print(r.text)

# Inspect event detail page
print("\n=== Event detail page: Cyber Revolution Summit ===")
detail_url = "https://www.eventbee.com/v/cyber-revolution-summit-philippines/event?eid=238729652"
rr = requests.get(detail_url, headers={
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}, timeout=20)
print(f"Status: {rr.status_code} | Size: {len(rr.text)}")
soup = BeautifulSoup(rr.text, "lxml")
mc = soup.find("div", id="maincontent") or soup.find("main") or soup.find("body")
if mc:
    print(str(mc)[:5000])
