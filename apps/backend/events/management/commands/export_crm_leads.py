"""Export the full events dataset as a UTF-8 TSV file for one-time CRM import.

Usage:
    python manage.py export_crm_leads
    python manage.py export_crm_leads --output leads.tsv
    python manage.py export_crm_leads --source facebook_events
"""
import csv
from datetime import date

from django.core.management.base import BaseCommand

from events.models import Event


def _iso(dt):
    """ISO 8601 string for a datetime, or '' when None."""
    return dt.isoformat() if dt else ""


def _str(v):
    """str(v) for a non-None value, or '' when None."""
    return str(v) if v is not None else ""


def _org(event, attr):
    """Attribute off the linked Organizer, or '' when no organizer/value."""
    if event.organizer_ref_id is None:
        return ""
    return getattr(event.organizer_ref, attr, "") or ""


def _tsv_cell(v):
    """Prefix formula-injection triggers so spreadsheets don't execute them."""
    s = str(v)
    return f"'{s}" if s and s[0] in ("=", "+", "-", "@") else s


HEADER = [
    "__row_type",
    "export_version",
    "event_id",
    "event_name",
    "event_slug",
    "event_category_raw",
    "event_category_clean",
    "event_starts_at",
    "event_ends_at",
    "event_post_date",
    "event_price",
    "event_source",
    "event_source_url",
    "event_registration_url",
    "event_image_url",
    "event_raw_text",
    "organizer_ref_id",
    "organizer_name",
    "organizer_slug",
    "organizer_status",
    "organizer_facebook_url",
    "organizer_instagram_url",
    "organizer_website",
    "organizer_email",
    "organizer_phone",
    "organizer_source",
    "organizer_enrichment_source",
    "organizer_scraped_at",
    "venue_name",
    "venue_address",
    "venue_city",
    "venue_country",
    "venue_latitude",
    "venue_longitude",
]


class Command(BaseCommand):
    help = "Export the full events dataset as a UTF-8 TSV file for CRM import."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default=None,
            help="Output file path (default: veent-leads-export-YYYY-MM-DD.tsv).",
        )
        parser.add_argument(
            "--source",
            default=None,
            help="Filter by Event.source.",
        )

    def handle(self, *args, **options):
        output_path = options["output"] or (
            f"veent-leads-export-{date.today().isoformat()}.tsv"
        )

        qs = (
            Event.objects.select_related("organizer_ref", "venue")
            .filter(organizer_ref__isnull=False)
            .order_by("organizer_ref_id", "starts_at")
        )
        if options["source"]:
            qs = qs.filter(source=options["source"])

        count = 0
        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
            writer.writerow(HEADER)

            for event in qs.iterator(chunk_size=2000):
                clean = event.agent_categories or []
                category_clean = "|".join(str(c) for c in clean)

                org_scraped_at = ""
                if event.organizer_ref_id is not None:
                    org = event.organizer_ref
                    org_scraped_at = _iso(org.scraped_at or org.created_at)

                venue = event.venue if event.venue_id is not None else None

                writer.writerow([_tsv_cell(v) for v in [
                    "veent_event_v1",
                    "1.0",
                    str(event.id),
                    event.name or "",
                    event.slug or "",
                    event.category or "",
                    category_clean,
                    _iso(event.starts_at),
                    _iso(event.ends_at),
                    _iso(event.post_date),
                    event.price or "",
                    event.source or "",
                    event.url or "",
                    event.registration_url or "",
                    event.image_url or "",
                    event.raw_text or "",
                    _str(event.organizer_ref_id),
                    _org(event, "name"),
                    _org(event, "slug"),
                    _org(event, "status"),
                    _org(event, "facebook_url"),
                    _org(event, "instagram_url"),
                    _org(event, "website"),
                    _org(event, "email"),
                    _org(event, "phone"),
                    _org(event, "source"),
                    _org(event, "enrichment_source"),
                    org_scraped_at,
                    venue.name or "" if venue else "",
                    venue.address or "" if venue else "",
                    venue.city or "" if venue else "",
                    venue.country or "" if venue else "",
                    _str(venue.latitude) if venue else "",
                    _str(venue.longitude) if venue else "",
                ]])
                count += 1

        self.stdout.write(
            self.style.SUCCESS(f"Exported {count} rows to {output_path}")
        )
