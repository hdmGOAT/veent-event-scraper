"""Scraper for racemeister.com partner/organizer listings.

Fetches the partner gallery from the racemeister.com homepage (bottom section),
then visits each partner's own website to extract contact details (email, phone,
social links). Facebook and Instagram URLs are stored directly without fetching.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapedOrganizer, save_organizers

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; EventScraper/1.0)"
    )
}
_TIMEOUT = 15


def _get_soup(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except Exception as exc:
        logger.warning("Could not fetch %s: %s", url, exc)
        return None


def _extract_contact(base_url: str) -> dict:
    """Try to extract email, phone, facebook_url, instagram_url from a website."""
    contact: dict = {}

    def _scan(soup: BeautifulSoup) -> None:
        if not contact.get("email"):
            for a in soup.find_all("a", href=re.compile(r"^mailto:", re.I)):
                email = a["href"].replace("mailto:", "").strip().split("?")[0]
                if email:
                    contact["email"] = email
                    break

        if not contact.get("phone"):
            for a in soup.find_all("a", href=re.compile(r"^tel:", re.I)):
                phone = a["href"].replace("tel:", "").strip()
                if phone:
                    contact["phone"] = phone
                    break

        if not contact.get("facebook_url"):
            for a in soup.find_all("a", href=re.compile(r"facebook\.com/", re.I)):
                contact["facebook_url"] = a["href"]
                break

        if not contact.get("instagram_url"):
            for a in soup.find_all("a", href=re.compile(r"instagram\.com/", re.I)):
                contact["instagram_url"] = a["href"]
                break

    soup = _get_soup(base_url)
    if soup:
        _scan(soup)

    # If no email yet, try /contact and /about
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    for path in ("/contact", "/about"):
        if contact.get("email"):
            break
        sub = _get_soup(urljoin(root, path))
        if sub:
            _scan(sub)

    return contact


class RacemeisterPartnersScraper(BaseScraper):
    source = "racemeister_partners"
    _HOMEPAGE = "https://www.racemeister.com/"

    def fetch(self):
        soup = _get_soup(self._HOMEPAGE)
        if not soup:
            logger.error("Could not load racemeister.com homepage")
            return

        # Locate the partners section by finding a heading that contains "partner"
        heading = soup.find(
            re.compile(r"^h[2-6]$"),
            string=re.compile(r"partner", re.I),
        )

        # Walk up to the nearest section/div container; fall back to the whole page
        container = None
        if heading:
            container = heading.parent
            # Go up one more level if the heading's direct parent is too narrow
            if container and not container.find("a"):
                container = container.parent

        if container is None:
            container = soup

        partners = []
        seen_names: set[str] = set()
        for a in container.find_all("a", href=True):
            img = a.find("img")
            if not img:
                continue
            name = (img.get("title") or img.get("alt") or "").strip()
            href = a["href"].strip()
            if not name or not href or href.startswith("#"):
                continue
            if name.lower() in seen_names:
                continue
            seen_names.add(name.lower())
            partners.append({"name": name, "url": href})

        logger.info("Found %d partners on racemeister.com", len(partners))

        for p in partners:
            name = p["name"]
            url = p["url"]

            organizer = ScrapedOrganizer(
                name=name,
                external_id=name.lower().replace(" ", "-"),
                source_url=self._HOMEPAGE,
            )

            if "facebook.com" in url:
                organizer.facebook_url = url
            elif "instagram.com" in url:
                organizer.instagram_url = url
            else:
                organizer.website = url
                contact = _extract_contact(url)
                organizer.email = contact.get("email", "")
                organizer.phone = contact.get("phone", "")
                organizer.facebook_url = contact.get("facebook_url", "")
                organizer.instagram_url = contact.get("instagram_url", "")

            yield organizer

    def run(self, **_kwargs) -> dict:
        organizers = list(self.fetch())
        return save_organizers(self.source, organizers)
