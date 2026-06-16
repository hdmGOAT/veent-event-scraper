from django.contrib import admin

from .models import Event, Venue


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ("name", "primary_type_display", "city", "country", "source", "updated_at")
    list_filter = ("primary_type_display", "country", "city", "source")
    search_fields = ("name", "address", "city")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at", "updated_at")


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("name", "organizer", "venue", "starts_at", "category", "source", "updated_at")
    list_filter = ("category", "source", "starts_at")
    search_fields = ("name", "description", "organizer")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("venue",)
    date_hierarchy = "starts_at"
    readonly_fields = ("source_url", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("name", "slug", "description", "venue")}),
        ("Schedule", {"fields": ("starts_at", "ends_at")}),
        ("Details", {"fields": ("url", "image_url", "price", "category")}),
        ("Host / Organizer", {"fields": ("organizer", "organizer_url")}),
        ("Provenance", {"fields": ("source", "source_url", "external_id", "scraped_at")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )
