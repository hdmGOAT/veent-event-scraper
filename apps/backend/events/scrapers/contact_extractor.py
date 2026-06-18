"""Shared helper: extract contact info from parsed HTML.

Pulls email, phone, social URLs, description, and postal address (city/country)
out of a page's markup. Used by the organizer enrichment crawler.
"""
import json
import re

from bs4 import BeautifulSoup


def _normalize_social(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    if url.startswith("//"):
        return f"https:{url}"
    if not url.startswith("http"):
        return f"https://{url.lstrip('/')}"
    if url.startswith("http://"):
        return "https://" + url[len("http://"):]
    return url


def extract_contact_info(html: str, base_url: str = "") -> dict:
    """Parse HTML and return a dict of contact fields found.

    Returns subset of: email, phone, facebook_url, instagram_url, description,
    city, country. Only returns fields that were actually found (non-empty values).
    """
    soup = BeautifulSoup(html, "lxml")
    result: dict = {}

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        lower = href.lower()
        if lower.startswith("mailto:") and "email" not in result:
            email = href[len("mailto:"):].split("?")[0].strip()
            if email:
                result["email"] = email
        elif lower.startswith("tel:") and "phone" not in result:
            phone = href[len("tel:"):].strip()
            if phone:
                result["phone"] = phone
        elif "facebook.com/" in lower and "facebook_url" not in result:
            normalized = _normalize_social(href)
            if normalized:
                result["facebook_url"] = normalized
        elif "instagram.com/" in lower and "instagram_url" not in result:
            normalized = _normalize_social(href)
            if normalized:
                result["instagram_url"] = normalized

    description = ""
    og = soup.find("meta", attrs={"property": "og:description"})
    if og and og.get("content"):
        description = og["content"].strip()
    if not description:
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            description = meta["content"].strip()
    if description:
        result["description"] = description[:1000]

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        address = _find_postal_address(data)
        if address:
            locality = address.get("addressLocality")
            country = address.get("addressCountry")
            if locality and "city" not in result:
                result["city"] = _stringify(locality)
            if country and "country" not in result:
                result["country"] = _stringify(country)
        if "city" in result and "country" in result:
            break

    return result


def _stringify(value) -> str:
    if isinstance(value, dict):
        return str(value.get("name", "")).strip()
    return str(value).strip()


def _find_postal_address(data) -> dict | None:
    """Recursively search a parsed JSON-LD structure for a PostalAddress node."""
    if isinstance(data, dict):
        node_type = data.get("@type", "")
        types = node_type if isinstance(node_type, list) else [node_type]
        if any(isinstance(t, str) and "PostalAddress" in t for t in types):
            return data
        for value in data.values():
            found = _find_postal_address(value)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_postal_address(item)
            if found:
                return found
    return None
