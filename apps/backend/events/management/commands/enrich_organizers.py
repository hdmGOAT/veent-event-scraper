"""Management command: enrich Organizer records by crawling their websites.

For each organizer with a website, fetch the homepage (plain HTTP first, then a
stealth browser fallback for Cloudflare-protected sites) and parse out contact
details: email, phone, social URLs, description, city, country. The /contact and
/about subpages are also checked over plain HTTP to fill any remaining gaps.

Only blank fields are written — existing non-blank contact data is never
overwritten. enriched_at and enrichment_source are set on every processed
organizer.

Examples:
    manage.py enrich_organizers                  # unenriched organizers only (default)
    manage.py enrich_organizers --force          # re-enrich already-enriched records
    manage.py enrich_organizers --limit 20       # cap at 20 organizers this run
    manage.py enrich_organizers --dry-run        # print what would be crawled, no DB writes
    manage.py enrich_organizers --delay 2        # seconds between organizers (default 2)
"""

import ipaddress
import socket
import time
from urllib.parse import urljoin, urlparse

import requests
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from events.models import Organizer
from events.scrapers.contact_extractor import extract_contact_info

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _USER_AGENT}

_CONTACT_FIELDS = (
    "email",
    "phone",
    "address",
    "city",
    "country",
    "facebook_url",
    "instagram_url",
    "description",
)


def _is_safe_public_url(url: str) -> bool:
    """Return True only for http/https URLs that resolve to a public IP."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.hostname or ""
        if not host:
            return False
        ip = ipaddress.ip_address(socket.gethostbyname(host))
        return ip.is_global and not ip.is_loopback and not ip.is_link_local
    except Exception:
        return False


def _http_get(url: str, timeout: int) -> str | None:
    """Plain HTTP GET. Returns HTML on a 200, else None."""
    try:
        resp = requests.get(url, timeout=timeout, headers=_HEADERS)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    resp.encoding = resp.apparent_encoding
    return resp.text


def _stealth_get(url: str) -> str | None:
    """Stealth browser fallback for Cloudflare-protected sites."""
    from scrapling.fetchers import StealthyFetcher

    try:
        page = StealthyFetcher.fetch(
            url,
            headless=True,
            solve_cloudflare=True,
            network_idle=True,
        )
    except Exception:
        return None
    html = page.html_content or ""
    if not html or "Just a moment" in html:
        return None
    return html


class Command(BaseCommand):
    help = "Enrich Organizer records by crawling their websites for contact details."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-enrich organizers that have already been enriched.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of organizers to process this run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be crawled without writing to the DB.",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=2.0,
            help="Seconds to sleep between organizers (default 2).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        delay = options["delay"]

        if options["limit"] is not None and options["limit"] <= 0:
            raise CommandError("--limit must be a positive integer.")
        if delay < 0:
            raise CommandError("--delay must be a non-negative number.")

        qs = Organizer.objects.exclude(status=Organizer.STATUS_REJECTED).exclude(website="").order_by("created_at")
        if not options["force"]:
            qs = qs.filter(enriched_at__isnull=True)
        if options["limit"]:
            qs = qs[: options["limit"]]

        organizers = list(qs)
        total = len(organizers)

        if total == 0:
            self.stdout.write(self.style.WARNING("No organizers to enrich."))
            return

        if dry_run:
            self.stdout.write(f"[dry-run] Would crawl {total} organizer(s):")
            for org in organizers:
                website = org.website or "no website"
                self.stdout.write(f"  - {org.name} (slug={org.slug}) → {website}")
            return

        self.stdout.write(f"Enriching {total} organizer(s)…")

        enriched_count = 0

        for i, org in enumerate(organizers, start=1):
            self.stdout.write(f"  [{i}/{total}] {org.name} (slug={org.slug})")

            if not org.website:
                org.enriched_at = timezone.now()
                org.enrichment_source = "skipped_no_website"
                org.save(update_fields=["enriched_at", "enrichment_source"])
                self.stdout.write("    → skipped: no website")
                if i < total:
                    time.sleep(delay)
                continue

            if not _is_safe_public_url(org.website):
                self.stdout.write(self.style.WARNING("    → skipped: unsafe or private URL"))
                if i < total:
                    time.sleep(delay)
                continue

            homepage_html = _http_get(org.website, timeout=10)
            if homepage_html is None:
                homepage_html = _stealth_get(org.website)
            if homepage_html is None:
                self.stdout.write(self.style.WARNING("    → failed to fetch homepage, skipping"))
                if i < total:
                    time.sleep(delay)
                continue

            data = extract_contact_info(homepage_html, base_url=org.website)

            for path in ("/contact", "/about"):
                if all(key in data for key in _CONTACT_FIELDS):
                    break
                subpage_url = urljoin(org.website, path)
                if not _is_safe_public_url(subpage_url):
                    continue
                subpage_html = _http_get(subpage_url, timeout=8)
                if subpage_html is None:
                    continue
                subpage_data = extract_contact_info(subpage_html, base_url=subpage_url)
                for key, value in subpage_data.items():
                    if key not in data:
                        data[key] = value

            changed_fields = []
            for field in _CONTACT_FIELDS:
                value = data.get(field)
                if value and not getattr(org, field):
                    setattr(org, field, value)
                    changed_fields.append(field)

            org.enriched_at = timezone.now()
            org.enrichment_source = "crawler"
            changed_fields += ["enriched_at", "enrichment_source"]

            org.save(update_fields=changed_fields)
            enriched_count += 1

            filled = [f for f in _CONTACT_FIELDS if f in changed_fields]
            self.stdout.write(f"    ✓ filled: {', '.join(filled) if filled else 'nothing new'}")

            if i < total:
                time.sleep(delay)

        self.stdout.write(
            self.style.SUCCESS(f"Done. Enriched {enriched_count}/{total} organizer(s).")
        )
