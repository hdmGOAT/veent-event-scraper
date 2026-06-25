"""Show cumulative bandwidth usage vs the DataImpulse 2.5 GB quota.

Usage:
    python manage.py bandwidth_usage
    python manage.py bandwidth_usage --days 30
"""
from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone
from datetime import timedelta

from events.models import BandwidthLog
from events.scrapers.facebook_events import DATAIMPULSE_QUOTA_BYTES


class Command(BaseCommand):
    help = "Show cumulative DataImpulse bandwidth usage vs 2.5 GB quota."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=None,
            help="Limit to the last N days (default: all time).",
        )

    def handle(self, *args, **options):
        qs = BandwidthLog.objects.all()
        if options["days"]:
            since = timezone.now() - timedelta(days=options["days"])
            qs = qs.filter(created_at__gte=since)
            self.stdout.write(f"Bandwidth usage (last {options['days']} days):\n")
        else:
            self.stdout.write("Bandwidth usage (all time):\n")

        for proxy_type, label in BandwidthLog.PROXY_CHOICES:
            total = qs.filter(proxy_type=proxy_type).aggregate(
                total=Sum("bytes_transferred")
            )["total"] or 0
            mb = total / 1_048_576
            if proxy_type == BandwidthLog.PROXY_DATAIMPULSE:
                pct = 100 * total / DATAIMPULSE_QUOTA_BYTES
                bar_filled = int(pct / 2)
                bar = "█" * bar_filled + "░" * (50 - bar_filled)
                self.stdout.write(
                    f"  {label:15s}: {mb:8.1f} MB / 2500.0 MB  ({pct:5.1f}%)\n"
                    f"  [{bar}]\n"
                )
            else:
                self.stdout.write(f"  {label:15s}: {mb:8.1f} MB\n")

        self.stdout.write("\nPer source:\n")
        rows = (
            qs.values("source", "proxy_type")
            .annotate(total=Sum("bytes_transferred"))
            .order_by("-total")
        )
        for row in rows:
            mb = row["total"] / 1_048_576
            self.stdout.write(
                f"  {row['source']:35s} {row['proxy_type']:12s} {mb:8.1f} MB\n"
            )

        self.stdout.write("\nRecent entries (last 10):\n")
        for log in qs.order_by("-created_at")[:10]:
            mb = log.bytes_transferred / 1_048_576
            self.stdout.write(
                f"  {log.created_at.strftime('%Y-%m-%d %H:%M')}  "
                f"{log.source:35s}  {log.proxy_type:12s}  {mb:8.1f} MB\n"
            )
