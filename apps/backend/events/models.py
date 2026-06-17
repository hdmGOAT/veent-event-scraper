from django.db import models
from django.urls import reverse


class Venue(models.Model):
    """A physical place where events are held."""

    class VerificationStatus(models.TextChoices):
        PENDING = "pending", "Pending review"
        VERIFIED = "verified", "Verified — events venue"
        REJECTED = "rejected", "Rejected — not an events venue"

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    address = models.CharField(max_length=500, blank=True)
    city = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=120, blank=True)
    website = models.URLField(blank=True, max_length=2000)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    # Classification / descriptive metadata (from Places API "About" data).
    # primary_type is the raw Places type key (e.g. "lodging"); the *_display
    # field is the human label (e.g. "Hotel") used for UI grouping.
    primary_type = models.CharField(max_length=120, blank=True)
    primary_type_display = models.CharField(max_length=120, blank=True, db_index=True)
    # Full list of Places types for the venue, e.g. ["lodging", "point_of_interest"].
    types = models.JSONField(default=list, blank=True)
    # Editorial "about" summary text when the source provides one.
    about = models.TextField(blank=True)
    # Flat map of amenity flags the source returned, e.g. {"Serves breakfast": true}.
    amenities = models.JSONField(default=dict, blank=True)
    rating = models.FloatField(null=True, blank=True)
    # Source price level enum string (e.g. "PRICE_LEVEL_MODERATE").
    price_level = models.CharField(max_length=40, blank=True)

    # Manual admin review of whether this is genuinely an events venue.
    # Set only by staff in the admin; never written by the scraper upsert path,
    # so a reviewer's decision survives re-scrapes.
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
        db_index=True,
        help_text="Manual admin review state for whether this is a real events venue.",
    )

    # Provenance / scraping metadata
    source = models.CharField(
        max_length=120, blank=True,
        help_text="Identifier of the scraper/source this record came from.",
    )
    source_url = models.URLField(blank=True, max_length=2000)
    # Stable identifier from the source (e.g. Google Places place_id), used to
    # deduplicate venues on re-scrape.
    place_id = models.CharField(max_length=255, blank=True, db_index=True)
    scraped_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "place_id"],
                condition=models.Q(place_id__gt=""),
                name="unique_venue_source_place_id",
            )
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("events:venue_detail", args=[self.slug])


class Event(models.Model):
    """A scraped event, optionally tied to a venue."""

    name = models.CharField(max_length=300)
    slug = models.SlugField(max_length=300, unique=True)
    description = models.TextField(blank=True)
    venue = models.ForeignKey(
        Venue, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="events",
    )

    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    url = models.URLField(blank=True, max_length=2000)
    image_url = models.URLField(blank=True, max_length=2000)
    price = models.CharField(max_length=120, blank=True)
    category = models.CharField(max_length=120, blank=True)
    # AI-assigned canonical categories (1–2 labels from CANONICAL_CATEGORIES).
    # Empty list = not yet classified. Written only by categorize_events_by_ids;
    # never overwritten by the scraper upsert path (save_events).
    agent_categories = models.JSONField(default=list, blank=True)

    # Host / organizer info
    organizer = models.CharField(max_length=255, blank=True)
    organizer_url = models.URLField(blank=True, max_length=2000)
    # Normalized FK to a known Organizer record when one can be matched.
    # The denormalized `organizer` / `organizer_url` fields above are kept as a
    # fallback for events whose organizer has no matching Organizer row.
    organizer_ref = models.ForeignKey(
        "Organizer", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="events",
    )

    # Provenance / scraping metadata
    source = models.CharField(
        max_length=120, blank=True,
        help_text="Identifier of the scraper/source this record came from.",
    )
    source_url = models.URLField(blank=True, max_length=2000)
    # Stable identifier from the source, used to deduplicate on re-scrape.
    external_id = models.CharField(max_length=255, blank=True, db_index=True)
    scraped_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["starts_at", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id"],
                condition=models.Q(external_id__gt=""),
                name="unique_source_external_id",
            )
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("events:event_detail", args=[self.slug])

    @property
    def organizer_display_name(self):
        """Prefer the linked Organizer's name, falling back to the raw CharField."""
        if self.organizer_ref_id:
            return self.organizer_ref.name
        return self.organizer


class Organizer(models.Model):
    """An event organizer scraped from a partner directory."""

    STATUS_PENDING = "pending"
    STATUS_CONFIRMED = "confirmed"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending Review"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_REJECTED, "Rejected"),
    ]

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True,
    )
    website = models.URLField(blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=80, blank=True)
    address = models.CharField(max_length=500, blank=True)
    city = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=120, blank=True)
    facebook_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    description = models.TextField(blank=True)

    # Provenance / scraping metadata
    source = models.CharField(
        max_length=120, blank=True,
        help_text="Identifier of the scraper/source this record came from.",
    )
    source_url = models.URLField(blank=True)
    external_id = models.CharField(max_length=255, blank=True, db_index=True)
    scraped_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id"],
                condition=models.Q(external_id__gt=""),
                name="unique_organizer_source_external_id",
            )
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("events:organizer_detail", args=[self.slug])

    @property
    def is_public(self):
        """Whether this organizer is publicly visible. Mirrors the queryset
        filter used by the public organizer views: everything except rejected.
        Use this before rendering a link to the organizer's detail page so we
        never emit a link that would 404."""
        return self.status != self.STATUS_REJECTED
