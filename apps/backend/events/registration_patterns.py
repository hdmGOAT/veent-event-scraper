"""Catalog of URL patterns used to detect registration/sign-up links.

Patterns are checked in priority order — the first match for a given
URL wins. Add new platforms here; all scrapers share this list.
"""
import re

# Each entry: (platform_label, compiled_pattern)
# Ordered roughly by how common they appear in Philippine/SEA event listings.
REGISTRATION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("google_forms",  re.compile(r'https?://(docs\.google\.com/forms/|forms\.gle/|goo\.gl/forms/)', re.I)),
    ("eventbrite",    re.compile(r'https?://(www\.)?eventbrite\.(com|co\.\w+)/e/', re.I)),
    ("luma",          re.compile(r'https?://(www\.)?lu\.ma/', re.I)),
    ("tito",          re.compile(r'https?://ti\.to/', re.I)),
    ("typeform",      re.compile(r'https?://\w+\.typeform\.com/to/', re.I)),
    ("jotform",       re.compile(r'https?://(www\.)?jotform\.com/', re.I)),
    ("peatix",        re.compile(r'https?://(www\.)?peatix\.com/', re.I)),
    ("ticket2me",     re.compile(r'https?://(www\.)?ticket2me\.net/', re.I)),
]


def find_registration_url(text: str) -> str:
    """Return the first registration URL found in *text*, or empty string."""
    if not text:
        return ""
    url_re = re.compile(r'https?://\S+', re.I)
    for raw_url in url_re.findall(text):
        url = raw_url.rstrip('.,);"\'>]')
        for _label, pattern in REGISTRATION_PATTERNS:
            if pattern.match(url):
                return url
    return ""
