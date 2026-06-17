"""Dump raw HTML sections of Eventbee browse page to understand structure."""
import requests, re
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

r = requests.get("https://www.eventbee.com/browse?country=PH", headers=HEADERS, timeout=25)
soup = BeautifulSoup(r.text, "lxml")

# Check if angular/react/vue app
scripts = soup.find_all("script")
print(f"Script tags: {len(scripts)}")
for s in scripts[:5]:
    src = s.get("src", "")
    if src:
        print(f"  src: {src}")
    else:
        content = (s.string or "")[:200]
        if content.strip():
            print(f"  inline: {content[:200]}")

# Main content area
main = soup.find("main") or soup.find("div", id="main") or soup.find("div", {"id": "content"})
if main:
    print(f"\nMain content: {str(main)[:1000]}")
else:
    print("\nNo <main> tag found")

# Body classes / id
body = soup.find("body")
if body:
    print(f"\nBody class={body.get('class','')} id={body.get('id','')}")

# Angular/React entry points
ng_app = soup.find(attrs={"ng-app": True}) or soup.find(attrs={"data-reactroot": True})
print(f"\nSPA root: {ng_app}")

# All divs with id
divs = soup.find_all("div", id=True)
print(f"\nDivs with ID ({len(divs)}):")
for d in divs[:15]:
    print(f"  #{d['id']} class={d.get('class','')} -> {str(d)[:150]}")

# Check for API XHR endpoints in JS
all_js = " ".join(s.string or "" for s in scripts if not s.get("src"))
api_hints = re.findall(r'["\']([^"\']*api[^"\']*)["\']', all_js, re.I)[:10]
print(f"\nAPI hints in inline JS: {api_hints}")

# Check all anchor tags
all_links = [(a.get_text(strip=True)[:50], a.get("href","")[:80])
             for a in soup.find_all("a", href=True)]
print(f"\nAll links ({len(all_links)}):")
for name, href in all_links[:20]:
    print(f"  {name} -> {href}")
