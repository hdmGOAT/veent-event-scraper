"""POST event records as CRM leads to an external HTTP endpoint.

One lead is created per future event (not per organizer). The same organizer will
appear multiple times if they have multiple upcoming events — each is a separate
sales cycle. The CRM deduplicates by sourceRef (event ID), so re-running the
command is safe and idempotent.

Usage:
    python manage.py push_crm_leads --dry-run
    python manage.py push_crm_leads --status pending --batch-size 50
    python manage.py push_crm_leads --source allevents_ph

Env vars (required unless --dry-run):
    CRM_INGEST_URL     Target ingest endpoint.
    CRM_INGEST_SECRET  Bearer token for the Authorization header.
"""
import html
import json
import os
import re
from urllib.parse import urlparse

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db.models import F, Q
from django.utils import timezone

from events.models import Event


# Maps raw scraper/Groq category strings to the CRM canonical category names
# (crm_categories table — seeded in 0026 migration + seed-scraper-categories.ts).
# CRM canonical names are the source of truth; update this map when the CRM seed changes.
CATEGORY_MAP = {
    # --- Sports ---
    "Fun Run / Road Race": "Fun Run / Road Race",
    "Fun Run": "Fun Run / Road Race",
    "Trail Run": "Trail Run",
    "Triathlon / Duathlon": "Triathlon / Duathlon",
    "Cycling": "Cycling",
    "Swimming": "Swimming",
    "Sports & Fitness": "Sports & Fitness",
    "Sports & Recreation": "Sports & Fitness",
    "Sports": "Sports & Fitness",
    "Competition": "Sports & Fitness",
    "Health": "Sports & Fitness",
    # --- Music / Performing Arts ---
    "Music & Concert": "Music & Concert",
    "Concert": "Music & Concert",
    "Live Band": "Music & Concert",
    "Music": "Music & Concert",
    "Festival": "Festival",
    "Music Fest": "Festival",
    # --- Theater ---
    "Theater & Performing Arts": "Theater & Performing Arts",
    "Theater": "Theater & Performing Arts",
    "Performing Arts": "Theater & Performing Arts",
    # --- Arts & Culture ---
    "Arts & Culture": "Arts & Culture",
    "Art": "Arts & Culture",
    "Exhibition": "Arts & Culture",
    "Expo": "Arts & Culture",
    # --- Business / Learning ---
    "Conference / Seminar": "Conference / Seminar",
    "Conference": "Conference / Seminar",
    "Convention": "Conference / Seminar",
    "Webinar": "Conference / Seminar",
    "Workshop / Training": "Workshop / Training",
    "Workshop": "Workshop / Training",
    # --- Food ---
    "Food & Dining": "Food & Dining",
    "Restaurant": "Food & Dining",
    # --- Charity ---
    "Charity / Fundraiser": "Charity / Fundraiser",
    # --- Other (no clean canonical match) ---
    "Church": "Other",
    "Religious": "Other",
    "Fan Fair": "Other",
    "School": "Other",
    "Education": "Other",
    "Camp": "Other",
    "Film": "Other",
    "Screening": "Other",
    "Bar/DJ": "Other",
    "Nightlife": "Other",
    "Community": "Other",
    "Travel and Tours": "Other",
    "Modelling": "Other",
    "Adventure Parks": "Other",
    "Club": "Other",
}


_GARBAGE_HANDLES = frozenset({"login", "top", "profilephp", "pages", "groups", "events", "search"})

# Facebook URL path patterns that indicate a broken/unresolvable URL.
_BAD_FB_PATH_RE = re.compile(
    r"^/(profile\.php|login|search(/|$))",
    re.IGNORECASE,
)


def _is_valid_social_url(url: str, platform: str) -> bool:
    """Return False for known-broken Facebook URLs that produce junk handles."""
    if platform != "Facebook":
        return True
    parsed = urlparse(url)
    if _BAD_FB_PATH_RE.match(parsed.path):
        return False
    # Bare numeric path (e.g. facebook.com/682029768) — raw user/page ID
    segments = [s for s in parsed.path.split("/") if s]
    if segments and segments[-1].isdigit():
        # Only valid when the numeric ID follows /people/ or /p/ (handled in _handle_from_url)
        if not (segments[0] in ("people", "p") and len(segments) >= 3):
            return False
    return True


def _handle_from_website(url: str) -> str:
    """Extract a short slug from a website domain (strips www., uses first label)."""
    netloc = urlparse(url).netloc.lower()
    netloc = netloc.removeprefix("www.")
    label = netloc.split(".")[0] if netloc else ""
    return label


def _handle_from_url(url):
    """
    Derive a stable, readable handle from a social/website URL.

    Facebook /people/Name/NUMERIC_ID  →  name segment
    Facebook /p/Name-NUMERIC_ID       →  name segment with trailing numeric suffix stripped
    Everything else                   →  last path segment, @ prefix stripped
    """
    path = urlparse(url).path
    segments = [seg for seg in path.split("/") if seg]
    if not segments:
        return ""

    # /people/Display-Name/123456789  — use the name segment, not the numeric ID
    if segments[0] == "people" and len(segments) >= 3 and segments[-1].isdigit():
        handle = segments[1].lower()
    # /p/Display-Name-123456789  — strip trailing long numeric suffix
    elif segments[0] == "p" and len(segments) >= 2:
        handle = re.sub(r"-\d{7,}$", "", segments[-1].lower())
    else:
        handle = segments[-1].lower().lstrip("@")
        # Also strip trailing numeric suffixes on any platform (e.g. Instagram legacy URLs)
        if handle.isdigit():
            handle = segments[-2].lower() if len(segments) >= 2 else handle

    return handle


class Command(BaseCommand):
    help = "POST event records as CRM leads (one lead per future event) to an external HTTP endpoint."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print payloads instead of POSTing.",
        )
        parser.add_argument(
            "--status",
            default="pending",
            help="Filter by Organizer.status (default: pending).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=50,
            help="Leads per POST request (default: 50).",
        )
        parser.add_argument(
            "--source",
            default=None,
            help="Filter by Organizer.source.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            default=False,
            dest="push_all",
            help="Push all future events regardless of crm_pushed_at (full re-push).",
        )
        parser.add_argument(
            "--future-only",
            action="store_true",
            default=False,
            help="Deprecated — future events are always the scope. Kept for backward compat.",
        )
        parser.add_argument(
            "--repush",
            action="store_true",
            default=False,
            help="Deprecated — use --all instead.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        crm_url = os.environ.get("CRM_INGEST_URL")
        crm_secret = os.environ.get("CRM_INGEST_SECRET")
        if not dry_run:
            if not crm_url:
                raise CommandError("CRM_INGEST_URL environment variable is required.")
            if not crm_secret:
                raise CommandError("CRM_INGEST_SECRET environment variable is required.")

        push_all = options["push_all"] or options["repush"]

        qs = Event.objects.filter(
            starts_at__gte=timezone.now()
        ).select_related("organizer_ref", "venue").exclude(
            organizer_ref__isnull=True
        ).exclude(
            agent_categories__isnull=True
        ).exclude(
            agent_categories=[]
        )
        if options["status"]:
            qs = qs.filter(organizer_ref__status=options["status"])
        if options["source"]:
            qs = qs.filter(organizer_ref__source=options["source"])

        # Delta filter: only push events not yet pushed, or updated since last push.
        if not push_all:
            qs = qs.filter(
                Q(crm_pushed_at__isnull=True) | Q(updated_at__gt=F("crm_pushed_at"))
            )

        qs = qs.order_by("starts_at")

        batch = []
        batch_event_ids = []
        batch_num = 0
        totals = {"received": 0, "created": 0, "skipped": 0, "review": 0}
        leads_built = 0
        skipped_no_url = 0
        skipped_bad_url = 0

        for event in qs.iterator():
            organizer = event.organizer_ref

            platform = None
            url = None
            handle = None

            if organizer.facebook_url and organizer.facebook_url.startswith("http"):
                if _is_valid_social_url(organizer.facebook_url, "Facebook"):
                    candidate = _handle_from_url(organizer.facebook_url)
                    if candidate and candidate not in _GARBAGE_HANDLES and not candidate.isdigit():
                        platform, url, handle = "Facebook", organizer.facebook_url, candidate
                    else:
                        skipped_bad_url += 1
                else:
                    skipped_bad_url += 1

            # Fallback: event.organizer_url may carry a clean FB page URL even when
            # organizer.facebook_url is missing or invalid — e.g. when the organizer
            # was matched from a non-FB source and the facebook_url field was never set,
            # but the event card itself captured the organizer's FB page directly.
            if url is None:
                ev_org_url = event.organizer_url
                if ev_org_url and ev_org_url.startswith("http") and "facebook.com" in ev_org_url:
                    if _is_valid_social_url(ev_org_url, "Facebook"):
                        candidate = _handle_from_url(ev_org_url)
                        if candidate and candidate not in _GARBAGE_HANDLES and not candidate.isdigit():
                            platform, url, handle = "Facebook", ev_org_url, candidate

            if url is None and organizer.instagram_url and organizer.instagram_url.startswith("http"):
                candidate = _handle_from_url(organizer.instagram_url)
                if candidate and candidate not in _GARBAGE_HANDLES and not candidate.isdigit():
                    platform, url, handle = "Instagram", organizer.instagram_url, candidate

            if url is None and organizer.website and organizer.website.startswith("http"):
                website_handle = _handle_from_website(organizer.website)
                if website_handle and website_handle not in _GARBAGE_HANDLES:
                    url, handle = organizer.website, website_handle

            # No social/website URL — require at least a valid email or phone to be worth pushing.
            has_email = bool(organizer.email and re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", organizer.email))
            has_phone = bool(organizer.phone and organizer.phone.strip())
            if url is None and not has_email and not has_phone:
                skipped_no_url += 1
                continue

            if handle is None:
                handle = re.sub(r"[^a-z0-9-]+", "-", organizer.name.lower().strip()).strip("-")[:50]
                if not handle:
                    handle = f"org-{organizer.id}"

            category = "Other"
            agent_cats = event.agent_categories or []
            if agent_cats:
                category = CATEGORY_MAP.get(agent_cats[0], "Other")

            location = ""
            if event.venue_id is not None:
                venue = event.venue
                seen_lc: set[str] = set()
                parts = []
                for p in (venue.city, venue.country):
                    if p and p.lower() not in seen_lc:
                        seen_lc.add(p.lower())
                        parts.append(p)
                location = ", ".join(parts)

            page_name = html.unescape(organizer.name.split("|")[0].strip())
            event_name = html.unescape((event.name or "").split("|")[0].strip())

            lead = {
                "pageName": page_name,
                "handle": handle,
                "category": category,
                "location": location,
                "eventName": event_name,
                "sourceRef": str(event.id),
                "scraperOrgId": organizer.id,
            }
            if event.starts_at:
                lead["eventDate"] = event.starts_at.strftime("%Y-%m-%d")
            if event.post_date:
                lead["firstAnnouncedDate"] = event.post_date.strftime("%Y-%m-%d")
            if event.url and event.url.startswith("http"):
                lead["eventLink"] = event.url
            # Primary URL / platform (drives dedup handle and CRM pageUrl).
            if url:
                lead["url"] = url
            if platform:
                lead["platform"] = platform
            # Push every social URL we have — CRM stores them in separate columns.
            _fb = organizer.facebook_url or event.organizer_url or ""
            if _fb and _fb.startswith("http") and "facebook.com" in _fb:
                if _is_valid_social_url(_fb, "Facebook"):
                    candidate = _handle_from_url(_fb)
                    if candidate and candidate not in _GARBAGE_HANDLES and not candidate.isdigit():
                        lead["facebookUrl"] = _fb
            if organizer.instagram_url and organizer.instagram_url.startswith("http"):
                candidate = _handle_from_url(organizer.instagram_url)
                if candidate and candidate not in _GARBAGE_HANDLES and not candidate.isdigit():
                    lead["instagramUrl"] = organizer.instagram_url
            if organizer.email and re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", organizer.email):
                lead["email"] = organizer.email
            if organizer.phone and organizer.phone.strip():
                lead["phone"] = organizer.phone.strip()

            batch.append(lead)
            batch_event_ids.append(event.id)
            leads_built += 1

            if len(batch) >= batch_size:
                batch_num += 1
                self._flush(batch, batch_event_ids, batch_num, dry_run, crm_url, crm_secret, totals)
                batch = []
                batch_event_ids = []

        if batch:
            batch_num += 1
            self._flush(batch, batch_event_ids, batch_num, dry_run, crm_url, crm_secret, totals)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Done. leads_built={leads_built} batches={batch_num} "
            f"skipped_no_url={skipped_no_url} skipped_bad_url={skipped_bad_url}"
        ))
        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                f"Totals: received={totals['received']} created={totals['created']} "
                f"skipped={totals['skipped']} review={totals['review']}"
            ))

    def _flush(self, batch, event_ids, batch_num, dry_run, crm_url, crm_secret, totals):
        if dry_run:
            self.stdout.write(f"--- Batch {batch_num} ({len(batch)} leads) ---")
            self.stdout.write(json.dumps({"leads": batch}, indent=2))
            return

        resp = requests.post(
            crm_url,
            json={"leads": batch},
            headers={
                "Authorization": f"Bearer {crm_secret}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        for key in totals:
            totals[key] += data.get(key, 0)

        # Stamp crm_pushed_at on all events in this batch now that the POST succeeded.
        Event.objects.filter(id__in=event_ids).update(crm_pushed_at=timezone.now())

        self.stdout.write(
            f"Batch {batch_num}: received={data.get('received', 0)} "
            f"created={data.get('created', 0)} skipped={data.get('skipped', 0)} "
            f"review={data.get('review', 0)}"
        )
