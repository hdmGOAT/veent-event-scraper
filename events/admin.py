from django.contrib import admin

from .models import Event, Venue


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
    list_display = ("name", "venue", "starts_at", "category", "source", "updated_at")
    list_filter = ("category", "source", "starts_at")
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("venue",)
    date_hierarchy = "starts_at"
    readonly_fields = ("created_at", "updated_at")
