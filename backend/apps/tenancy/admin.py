from django.contrib import admin

from .models import Membership, Organization, Workspace


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ["user"]


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "created_at"]
    search_fields = ["name"]


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "status", "storage_backend", "created_at"]
    list_filter = ["status", "storage_backend"]
    search_fields = ["name", "slug"]
    inlines = [MembershipInline]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "workspace", "role", "created_at"]
    list_filter = ["role"]
    autocomplete_fields = ["user", "workspace"]
