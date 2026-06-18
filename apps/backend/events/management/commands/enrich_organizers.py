"""Management command: enrich Organizer records using Diffbot Enhance and Hunter.io.

Waterfall strategy per organizer:
  1. Diffbot Enhance — fills website, social URLs (FB/IG), location, description.
     Works with a domain URL (precise) or company name (fuzzy).
  2. Hunter.io domain-search — fills email (and optionally phone/social) if a
     domain is known after step 1. Limited to 25 free searches/month; the command
     tracks usage per run and stops when the budget is consumed.

Only blank fields are written — existing non-blank contact data is never overwritten.
enriched_at and enrichment_source are set on every processed organizer.

Examples:
    manage.py enrich_organizers                  # unenriched organizers only (default)
    manage.py enrich_organizers --force          # re-enrich already-enriched records
    manage.py enrich_organizers --limit 20       # cap at 20 organizers this run
    manage.py enrich_organizers --dry-run        # print what would change, no DB writes
    manage.py enrich_organizers --delay 13       # seconds between Diffbot calls (default 13)
    manage.py enrich_organizers --skip-hunter    # skip Hunter.io even if key is set
"""

import time
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import Organizer


def _extract_domain(url: str) -> str:
    """Return bare domain (e.g. 'example.com') from a URL string, or '' if invalid."""
    if not url:
        return ""
    try:
        parsed = urlparse(url if url.startswith("http") else f"https://{url}")
        return parsed.netloc.lower().lstrip("www.") or ""
    except Exception:
        return ""


def _diffbot_enhance(name: str, domain: str, api_key: str) -> dict:
    """Call Diffbot Enhance API. Returns extracted fields dict (may be empty)."""
    params = {"type": "Organization", "token": api_key, "size": 1}
    if domain:
        params["url"] = f"https://{domain}"
    else:
        params["name"] = name

    try:
        resp = requests.get(
            "https://kg.diffbot.com/kg/v3/enhance",
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data") or []
        if not data:
            return {}
        entity = data[0].get("entity", {})
    except Exception:
        return {}

    result = {}

    homepage = entity.get("homepageUri", "")
    if homepage:
        result["website"] = homepage if homepage.startswith("http") else f"https://{homepage}"

    description = entity.get("description", {})
    if isinstance(description, dict) and description.get("value"):
        result["description"] = description["value"]
    elif isinstance(description, str) and description:
        result["description"] = description

    location = entity.get("location", {}) or {}
    if location.get("city", {}).get("name"):
        result["city"] = location["city"]["name"]
    elif isinstance(location.get("city"), str):
        result["city"] = location["city"]
    if location.get("country", {}).get("name"):
        result["country"] = location["country"]["name"]
    elif isinstance(location.get("country"), str):
        result["country"] = location["country"]

    for uri_obj in entity.get("allUris", []) or []:
        uri = uri_obj if isinstance(uri_obj, str) else uri_obj.get("uri", "")
        if not uri:
            continue
        if "facebook.com/" in uri and "facebook_url" not in result:
            result["facebook_url"] = uri
        elif "instagram.com/" in uri and "instagram_url" not in result:
            result["instagram_url"] = uri

    return result


def _hunter_domain_search(domain: str, api_key: str) -> dict:
    """Call Hunter.io domain-search API. Returns extracted fields dict (may be empty)."""
    if not domain or not api_key:
        return {}
    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json().get("data") or {}
    except Exception:
        return {}

    result = {}

    emails = payload.get("emails") or []
    if emails:
        result["email"] = emails[0].get("value", "")

    org = payload.get("organization") or {}
    if org.get("phone"):
        result["phone"] = org["phone"]
    if org.get("facebook"):
        result["facebook_url"] = org["facebook"]
    if org.get("instagram"):
        result["instagram_url"] = org["instagram"]

    return {k: v for k, v in result.items() if v}


class Command(BaseCommand):
    help = "Enrich Organizer records using Diffbot Enhance and Hunter.io domain-search."

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
            help="Print what would change without writing to the DB.",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=13.0,
            help="Seconds to sleep between Diffbot calls (default 13 — keeps under 5/min).",
        )
        parser.add_argument(
            "--skip-hunter",
            action="store_true",
            help="Skip Hunter.io even if HUNTER_API_KEY is configured.",
        )

    def handle(self, *args, **options):
        diffbot_key = settings.DIFFBOT_API_KEY
        hunter_key = "" if options["skip_hunter"] else settings.HUNTER_API_KEY
        dry_run = options["dry_run"]
        delay = options["delay"]

        if not diffbot_key:
            self.stdout.write(self.style.ERROR(
                "DIFFBOT_API_KEY is not set. Add it to .env and try again."
            ))
            return

        qs = Organizer.objects.exclude(status=Organizer.STATUS_REJECTED).order_by("created_at")
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
            self.stdout.write(
                f"[dry-run] Would process {total} organizer(s). No writes."
            )
            return

        self.stdout.write(f"Enriching {total} organizer(s)…")

        # Hunter.io is capped at 25 free searches/month — track per-run.
        hunter_used = 0
        HUNTER_MONTHLY_BUDGET = 25

        enriched_count = 0

        for i, org in enumerate(organizers, start=1):
            self.stdout.write(f"  [{i}/{total}] {org.name} (slug={org.slug})")

            domain = _extract_domain(org.website)
            updates: dict = {}
            sources_used: list = []

            # Step 1: Diffbot Enhance
            diffbot_result = _diffbot_enhance(org.name, domain, diffbot_key)
            if diffbot_result:
                sources_used.append("diffbot")
                for field, value in diffbot_result.items():
                    if value and not getattr(org, field):
                        updates[field] = value
                # If Diffbot found a website and we had no domain, extract it now.
                if not domain and updates.get("website"):
                    domain = _extract_domain(updates["website"])

            # Step 2: Hunter.io (only if domain known, email blank, budget remaining)
            if (
                hunter_key
                and domain
                and not org.email
                and "email" not in updates
                and hunter_used < HUNTER_MONTHLY_BUDGET
            ):
                hunter_result = _hunter_domain_search(domain, hunter_key)
                hunter_used += 1
                if hunter_result:
                    sources_used.append("hunter")
                    for field, value in hunter_result.items():
                        if value and not getattr(org, field) and field not in updates:
                            updates[field] = value

            # Apply updates
            changed_fields = []
            for field, value in updates.items():
                setattr(org, field, value)
                changed_fields.append(field)

            org.enriched_at = timezone.now()
            org.enrichment_source = ",".join(sources_used)
            changed_fields += ["enriched_at", "enrichment_source"]

            org.save(update_fields=changed_fields)
            enriched_count += 1

            if changed_fields:
                filled = [f for f in updates]
                self.stdout.write(f"    ✓ filled: {', '.join(filled) if filled else 'nothing new'}")

            # Rate-limit: sleep between Diffbot calls (skip after the last item).
            if i < total:
                time.sleep(delay)

        summary = f"Done. Enriched {enriched_count}/{total} organizer(s)."
        if hunter_key:
            summary += f" Hunter searches used this run: {hunter_used}/{HUNTER_MONTHLY_BUDGET}."
        self.stdout.write(self.style.SUCCESS(summary))
