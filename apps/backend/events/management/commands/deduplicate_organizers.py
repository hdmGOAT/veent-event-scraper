"""Detect and merge duplicate ``Organizer`` rows scraped from different sources.

Tier 1 (auto-merge with ``--execute``): organizers that share a normalized
identifier (website, facebook URL, instagram URL, email, or phone) across
different ``source`` values are merged into a single winning row. All
``Event.organizer_ref`` FKs pointing at the losers are re-pointed to the winner,
then the loser rows are hard-deleted.

Tier 2 (review only): organizers with fuzzy name similarity
(``difflib.SequenceMatcher.ratio() >= 0.88``) are reported but never auto-merged.
They can be written to CSV via ``--fuzzy-output``.

This command is intentionally self-contained: normalization helpers are
re-implemented here rather than imported from ``base.py`` to avoid coupling.
"""

import csv
import re
import unicodedata
from datetime import datetime, timezone as dt_timezone
from difflib import SequenceMatcher
from urllib.parse import urlparse, urlunparse

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count

from events.models import Event, Organizer


# Identifier fields used for Tier 1 exact-match clustering, in report order.
_IDENTIFIER_FIELDS = ("website", "facebook_url", "instagram_url", "email", "phone")

# Fields counted toward an organizer's completeness score (string fields only).
_COMPLETENESS_FIELDS = (
    "website", "email", "phone", "address", "city", "country",
    "facebook_url", "instagram_url", "description",
)

# Fuzzy-name similarity threshold for Tier 2.
_FUZZY_THRESHOLD = 0.88

# Naive datetime sentinel for sorting organizers whose scraped_at is None.
_MIN_DT = datetime.min.replace(tzinfo=dt_timezone.utc)


# --------------------------------------------------------------------------- #
# Step 1 — Normalization helpers
# --------------------------------------------------------------------------- #

def _normalize_url(url: str) -> str:
    """Lowercase scheme+host, strip ``www.`` and a trailing slash. "" for blank."""
    if not url:
        return ""
    parsed = urlparse(url.strip())
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    normalized = parsed._replace(scheme=parsed.scheme.lower(), netloc=netloc)
    return urlunparse(normalized).rstrip("/")


def _normalize_email(email: str) -> str:
    """Lowercase and trim. "" for blank/None."""
    if not email:
        return ""
    return email.strip().lower()


def _normalize_phone(phone: str) -> str:
    """Strip non-digits and a leading PH country code. "" if too short to match.

    Drops a leading ``63`` only when doing so yields exactly 10 digits (a
    Philippine national number), and drops a single leading ``0``. Returns ""
    for anything shorter than 7 digits, which is too short to be a meaningful
    match key.
    """
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("63") and len(digits) - 2 == 10:
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = digits[1:]
    if len(digits) < 7:
        return ""
    return digits


def _normalize_name(name: str) -> str:
    """Lowercase, strip accents/punctuation, collapse whitespace. "" for blank."""
    if not name:
        return ""
    decomposed = unicodedata.normalize("NFD", name)
    without_accents = "".join(
        c for c in decomposed if unicodedata.category(c) != "Mn"
    )
    lowered = without_accents.lower()
    no_punct = re.sub(r"[^\w\s]", "", lowered)
    return " ".join(no_punct.split())


def _normalized_identifier_values(org: Organizer) -> dict[str, str]:
    """Return {field: normalized_value} for non-empty identifier fields only."""
    values: dict[str, str] = {}
    for field in ("website", "facebook_url", "instagram_url"):
        norm = _normalize_url(getattr(org, field, "") or "")
        if norm:
            values[field] = norm
    email = _normalize_email(org.email or "")
    if email:
        values["email"] = email
    phone = _normalize_phone(org.phone or "")
    if phone:
        values["phone"] = phone
    return values


# --------------------------------------------------------------------------- #
# Step 2 — Tier 1 cluster detection
# --------------------------------------------------------------------------- #

def _union_find_clusters(adjacency: dict[int, set[int]]) -> list[list[int]]:
    """Group pks into connected components from an undirected adjacency map.

    ``adjacency`` maps each pk to the set of pks it should be grouped with.
    Returns a list of pk groups (each group is a list of pks).
    """
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        # Path compression.
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for node, neighbours in adjacency.items():
        find(node)
        for other in neighbours:
            union(node, other)

    groups: dict[int, list[int]] = {}
    for node in parent:
        groups.setdefault(find(node), []).append(node)
    return list(groups.values())


def find_exact_match_clusters(source_filter: str | None) -> list[list[Organizer]]:
    """Return Tier 1 clusters: cross-source organizers sharing an identifier.

    Each cluster is a list of ``Organizer`` instances (with an ``event_count``
    annotation). Only components with at least two distinct ``source`` values
    are returned. When ``source_filter`` is set, clusters that contain no
    organizer from that source are discarded.
    """
    organizers = list(
        Organizer.objects.annotate(event_count=Count("events")).all()
    )
    by_pk = {org.pk: org for org in organizers}

    # Map "field:value" identifier keys to the pks that share them.
    identifier_index: dict[str, list[int]] = {}
    for org in organizers:
        for field, value in _normalized_identifier_values(org).items():
            identifier_index.setdefault(f"{field}:{value}", []).append(org.pk)

    # Build adjacency from every identifier key shared by 2+ organizers.
    adjacency: dict[int, set[int]] = {org.pk: set() for org in organizers}
    for pks in identifier_index.values():
        if len(pks) < 2:
            continue
        for i, pk_a in enumerate(pks):
            for pk_b in pks[i + 1:]:
                adjacency[pk_a].add(pk_b)
                adjacency[pk_b].add(pk_a)

    clusters: list[list[Organizer]] = []
    for pk_group in _union_find_clusters(adjacency):
        if len(pk_group) < 2:
            continue
        members = [by_pk[pk] for pk in pk_group]
        sources = {m.source for m in members}
        if len(sources) < 2:
            continue  # All from the same source — not a cross-source duplicate.
        if source_filter is not None and source_filter not in sources:
            continue
        clusters.append(members)
    return clusters


# --------------------------------------------------------------------------- #
# Step 3 — Winner selection
# --------------------------------------------------------------------------- #

def _completeness_score(org: Organizer) -> int:
    """Count non-empty string fields on the organizer (higher = more complete)."""
    return sum(1 for f in _COMPLETENESS_FIELDS if (getattr(org, f, "") or "").strip())


def select_winner(cluster: list[Organizer]) -> tuple[Organizer, list[Organizer]]:
    """Pick the canonical organizer for a cluster; return ``(winner, losers)``.

    Waterfall (highest priority first): confirmed status > event count >
    completeness > most recent ``scraped_at`` > lowest pk.
    """
    def sort_key(org: Organizer):
        return (
            1 if org.status == Organizer.STATUS_CONFIRMED else 0,
            getattr(org, "event_count", 0) or 0,
            _completeness_score(org),
            org.scraped_at or _MIN_DT,
            -org.pk,
        )

    ranked = sorted(cluster, key=sort_key, reverse=True)
    return ranked[0], ranked[1:]


# --------------------------------------------------------------------------- #
# Step 4 — Merge execution
# --------------------------------------------------------------------------- #

def merge_cluster(
    winner: Organizer, losers: list[Organizer], dry_run: bool
) -> dict:
    """Re-point events off ``losers`` onto ``winner`` and delete the losers.

    Returns ``{"events_repointed": int, "organizers_deleted": int}``. When
    ``dry_run`` is True no DB writes occur and the returned counts are the
    would-be values.
    """
    loser_pks = [loser.pk for loser in losers]
    if not loser_pks:
        return {"events_repointed": 0, "organizers_deleted": 0}

    if dry_run:
        events_repointed = Event.objects.filter(
            organizer_ref__in=loser_pks
        ).count()
        return {
            "events_repointed": events_repointed,
            "organizers_deleted": len(loser_pks),
        }

    with transaction.atomic():
        events_repointed = Event.objects.filter(
            organizer_ref__in=loser_pks
        ).update(organizer_ref=winner)

        if winner.scraped_at is None:
            loser_times = [loser.scraped_at for loser in losers if loser.scraped_at]
            if loser_times:
                winner.scraped_at = max(loser_times)
                winner.save(update_fields=["scraped_at"])

        organizers_deleted, _ = Organizer.objects.filter(
            pk__in=loser_pks
        ).delete()

    return {
        "events_repointed": events_repointed,
        "organizers_deleted": organizers_deleted,
    }


# --------------------------------------------------------------------------- #
# Step 6 — Tier 2 fuzzy name pass
# --------------------------------------------------------------------------- #

def find_fuzzy_clusters(
    source_filter: str | None, exclude_pks: set[int]
) -> list[list[Organizer]]:
    """Return cross-source clusters of fuzzily-similar names (review only).

    ``exclude_pks`` are organizers already consumed by Tier 1 and skipped here.
    Names must share their first three characters to be compared, and a pair is
    grouped only when ``SequenceMatcher.ratio() >= 0.88`` and sources differ.
    """
    organizers = [
        org
        for org in Organizer.objects.annotate(event_count=Count("events")).all()
        if org.pk not in exclude_pks
    ]

    entries = []
    for org in organizers:
        norm = _normalize_name(org.name)
        if norm:
            entries.append((norm, org))
    entries.sort(key=lambda item: item[0])

    by_pk = {org.pk: org for _, org in entries}
    adjacency: dict[int, set[int]] = {org.pk: set() for _, org in entries}

    for i, (name_a, org_a) in enumerate(entries):
        prefix_a = name_a[:3]
        for name_b, org_b in entries[i + 1:]:
            if name_b[:3] != prefix_a:
                break  # Sorted: no further candidate can share the prefix.
            if org_a.source == org_b.source:
                continue
            if SequenceMatcher(None, name_a, name_b).ratio() >= _FUZZY_THRESHOLD:
                adjacency[org_a.pk].add(org_b.pk)
                adjacency[org_b.pk].add(org_a.pk)

    clusters: list[list[Organizer]] = []
    for pk_group in _union_find_clusters(adjacency):
        if len(pk_group) < 2:
            continue
        members = [by_pk[pk] for pk in pk_group]
        sources = {m.source for m in members}
        if len(sources) < 2:
            continue
        if source_filter is not None and source_filter not in sources:
            continue
        clusters.append(members)
    return clusters


# --------------------------------------------------------------------------- #
# Step 5 — Management command
# --------------------------------------------------------------------------- #

class Command(BaseCommand):
    help = "Detect and merge duplicate Organizer rows across sources."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Print proposals without writing (default when no mode flag given).",
        )
        parser.add_argument(
            "--execute", action="store_true",
            help="Actually merge Tier 1 clusters.",
        )
        parser.add_argument(
            "--source", type=str, default=None,
            help="Restrict to clusters involving this source.",
        )
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Cap the number of clusters to process/report.",
        )
        parser.add_argument(
            "--fuzzy-output", type=str, default=None,
            help="Write the Tier 2 fuzzy-name review CSV to this path.",
        )

    def handle(self, *args, **options):
        if options["dry_run"] and options["execute"]:
            raise CommandError("--dry-run and --execute are mutually exclusive.")

        execute = options["execute"]
        source_filter = options["source"]
        limit = options["limit"]
        fuzzy_output = options["fuzzy_output"]

        clusters = find_exact_match_clusters(source_filter=source_filter)
        if limit is not None:
            clusters = clusters[:limit]

        consumed_pks: set[int] = set()
        total_clusters = 0
        total_freed = 0
        total_repointed = 0

        if not clusters:
            self.stdout.write("No duplicate clusters found.")

        for index, cluster in enumerate(clusters, start=1):
            winner, losers = select_winner(cluster)
            consumed_pks.add(winner.pk)
            consumed_pks.update(loser.pk for loser in losers)

            matched_on = self._describe_match(cluster)

            if execute:
                result = merge_cluster(winner, losers, dry_run=False)
                deleted_pks = ", ".join(str(loser.pk) for loser in losers)
                self.stdout.write(
                    f'Merged cluster {index}: winner=pk{winner.pk} '
                    f'"{winner.name}", deleted {deleted_pks}, '
                    f're-pointed {result["events_repointed"]} event(s).'
                )
            else:
                result = merge_cluster(winner, losers, dry_run=True)
                self._print_dry_run_cluster(index, winner, losers, result, matched_on)

            total_clusters += 1
            total_freed += result["organizers_deleted"]
            total_repointed += result["events_repointed"]

        if execute:
            self.stdout.write(
                f"Done. {total_clusters} cluster(s) processed, "
                f"{total_freed} organizer row(s) freed, "
                f"{total_repointed} event(s) re-pointed."
            )
        else:
            self.stdout.write(
                f"[dry-run] {total_clusters} cluster(s) would be merged, "
                f"freeing {total_freed} organizer row(s) and "
                f"re-pointing {total_repointed} event(s)."
            )

        self._handle_fuzzy(source_filter, consumed_pks, fuzzy_output)

    # -- output helpers ----------------------------------------------------- #

    def _describe_match(self, cluster: list[Organizer]) -> str:
        """Return a human-readable identifier key shared within the cluster."""
        per_field: dict[str, set[str]] = {}
        for org in cluster:
            for field, value in _normalized_identifier_values(org).items():
                per_field.setdefault(field, set()).add(value)
        for field in _IDENTIFIER_FIELDS:
            for value in per_field.get(field, set()):
                shared = sum(
                    1
                    for org in cluster
                    if _normalized_identifier_values(org).get(field) == value
                )
                if shared >= 2:
                    return f"{field}={value}"
        return ""

    def _print_dry_run_cluster(self, index, winner, losers, result, matched_on):
        members = [winner] + losers
        self.stdout.write(
            f"Cluster {index} ({len(members)} organizers, "
            f'{result["events_repointed"]} events would be re-pointed):'
        )
        self.stdout.write(
            f"  WINNER  [pk={winner.pk}] {winner.name}  "
            f"(source={winner.source}, status={winner.status}, "
            f"events={getattr(winner, 'event_count', 0)})"
        )
        for loser in losers:
            self.stdout.write(
                f"  loser   [pk={loser.pk}] {loser.name}  "
                f"(source={loser.source}, status={loser.status}, "
                f"events={getattr(loser, 'event_count', 0)})"
            )
        if matched_on:
            self.stdout.write(f"  Matched on: {matched_on}")

    def _handle_fuzzy(self, source_filter, consumed_pks, fuzzy_output):
        fuzzy_clusters = find_fuzzy_clusters(
            source_filter=source_filter, exclude_pks=consumed_pks
        )
        if not fuzzy_clusters:
            return

        if not fuzzy_output:
            self.stdout.write(
                f"{len(fuzzy_clusters)} fuzzy name cluster(s) found. "
                f"Use --fuzzy-output FILE to write for review."
            )
            return

        total_orgs = 0
        with open(fuzzy_output, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                "cluster_id", "pk", "name", "source", "status",
                "website", "email", "similarity_to_cluster_representative",
            ])
            for cluster_id, cluster in enumerate(fuzzy_clusters, start=1):
                ranked = sorted(cluster, key=lambda o: _normalize_name(o.name))
                rep_name = _normalize_name(ranked[0].name)
                for org in ranked:
                    org_name = _normalize_name(org.name)
                    similarity = (
                        1.0
                        if org.pk == ranked[0].pk
                        else round(
                            SequenceMatcher(None, rep_name, org_name).ratio(), 4
                        )
                    )
                    writer.writerow([
                        cluster_id, org.pk, org.name, org.source, org.status,
                        org.website, org.email, similarity,
                    ])
                    total_orgs += 1

        self.stdout.write(
            f"Wrote {len(fuzzy_clusters)} fuzzy cluster(s) "
            f"({total_orgs} organizers) to {fuzzy_output}."
        )
