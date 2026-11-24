from django.contrib import admin

from .models import SchemaVersion


@admin.register(SchemaVersion)
class SchemaVersionAdmin(admin.ModelAdmin):
    """Read-only: schema versions change only through the registry."""

    list_display = ["workspace", "number", "status", "spec_version", "created_at", "published_at"]
    list_filter = ["status"]
    search_fields = ["workspace__name"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
