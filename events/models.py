from django.db import models
from django.urls import reverse


class Venue(models.Model):
    """A physical place where events are held."""

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    address = models.CharField(max_length=500, blank=True)
    city = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=120, blank=True)
    website = models.URLField(blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    # Provenance / scraping metadata
    source = models.CharField(
        max_length=120, blank=True,
        help_text="Identifier of the scraper/source this record came from.",
    )
    source_url = models.URLField(blank=True)
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
    url = models.URLField(blank=True)
    image_url = models.URLField(blank=True)
    price = models.CharField(max_length=120, blank=True)
    category = models.CharField(max_length=120, blank=True)

    # Provenance / scraping metadata
    source = models.CharField(
        max_length=120, blank=True,
        help_text="Identifier of the scraper/source this record came from.",
    )
    source_url = models.URLField(blank=True)
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
