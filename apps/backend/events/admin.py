from django.contrib import admin

from .models import Event, Organizer, ScraperRun, Venue


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = (
        "name", "verification_status", "primary_type_display",
        "city", "country", "source", "updated_at",
    )
    list_filter = ("verification_status", "primary_type_display", "country", "city", "source")
    list_editable = ("verification_status",)
    search_fields = ("name", "address", "city")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at", "updated_at")
    actions = ("mark_verified", "mark_rejected")

    @admin.action(description="Mark selected venues as VERIFIED (real events venue)")
    def mark_verified(self, request, queryset):
        updated = queryset.update(verification_status=Venue.VerificationStatus.VERIFIED)
        self.message_user(request, f"{updated} venue(s) marked verified.")

    @admin.action(description="Mark selected venues as REJECTED (not an events venue)")
    def mark_rejected(self, request, queryset):
        updated = queryset.update(verification_status=Venue.VerificationStatus.REJECTED)
        self.message_user(request, f"{updated} venue(s) marked rejected.")


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("name", "organizer", "venue", "starts_at", "category", "source", "updated_at")
    list_filter = ("category", "source", "starts_at")
    search_fields = ("name", "description", "organizer")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("venue",)
    raw_id_fields = ("organizer_ref",)
    date_hierarchy = "starts_at"
    readonly_fields = ("source_url", "organizer", "organizer_url", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("name", "slug", "description", "venue")}),
        ("Schedule", {"fields": ("starts_at", "ends_at")}),
        ("Details", {"fields": ("url", "image_url", "price", "category")}),
        ("Host / Organizer", {"fields": ("organizer_ref", "organizer", "organizer_url")}),
        ("Provenance", {"fields": ("source", "source_url", "external_id", "scraped_at")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(Organizer)
class OrganizerAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "email", "phone", "website", "facebook_url", "source", "updated_at")
    list_filter = ("status", "source")
    list_editable = ("status",)
    search_fields = ("name", "email", "website", "phone")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at", "updated_at", "scraped_at")
    actions = ["confirm_organizers", "reject_organizers"]

    @admin.action(description="Mark selected organizers as Confirmed")
    def confirm_organizers(self, request, queryset):
        queryset.update(status=Organizer.STATUS_CONFIRMED)

    @admin.action(description="Mark selected organizers as Rejected")
    def reject_organizers(self, request, queryset):
        queryset.update(status=Organizer.STATUS_REJECTED)


@admin.register(ScraperRun)
class ScraperRunAdmin(admin.ModelAdmin):
    list_display = (
        "scraper_key", "status", "started_at", "finished_at",
        "created_count", "updated_count", "triggered_by", "created_at",
    )
    list_filter = ("status", "scraper_key")
    readonly_fields = (
        "scraper_key", "status", "pid", "started_at", "finished_at",
        "created_count", "updated_count", "extra_counts", "error_message",
        "triggered_by", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
