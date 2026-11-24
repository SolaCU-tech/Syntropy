"""Organizations, workspaces and memberships (FR-01).

An organization owns workspaces (and, later, billing). A workspace is one business's
isolated space. A membership gives one user one role in one workspace; it is the only thing
that grants access to a workspace's data (spec section 6).
"""

import uuid

from django.conf import settings
from django.db import models


class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class StorageBackend(models.TextChoices):
    # ADR-08 (Provisional): JSONB records in shared tables. The registry keeps this per
    # workspace so a workspace can later move to its own schema or database (ADR-09).
    SHARED_JSONB = "shared_jsonb", "Shared JSONB tables"


class Workspace(models.Model):
    class Status(models.TextChoices):
        SETUP = "setup", "Being set up"
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    # UUIDs, so workspace IDs in URLs can't be guessed or counted.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="workspaces"
    )
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=60)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SETUP)
    timezone = models.CharField(max_length=64, default="Africa/Lagos")
    currency = models.CharField(max_length=3, default="NGN")
    storage_backend = models.CharField(
        max_length=32, choices=StorageBackend.choices, default=StorageBackend.SHARED_JSONB
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "slug"], name="workspace_slug_unique_in_org"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["setup", "active", "archived"]),
                name="workspace_status_valid",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Role(models.TextChoices):
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    EDITOR = "editor", "Editor"
    VIEWER = "viewer", "Viewer"


class Membership(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "workspace"], name="membership_unique"),
            models.CheckConstraint(
                condition=models.Q(role__in=["owner", "admin", "editor", "viewer"]),
                name="membership_role_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} · {self.workspace} ({self.role})"
