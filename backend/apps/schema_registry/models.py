"""Schema versions: the registry's immutable snapshots of a workspace's SSD (spec section 8).

A workspace has any number of versions. Drafts can change; once published, a version's
content never changes again (a PostgreSQL trigger enforces this, so not even a raw UPDATE
can alter it). Publishing a new version marks the previous one superseded. At most one
version per workspace is published, and that one is the workspace's active schema.
"""

import uuid

from django.conf import settings
from django.db import models

from apps.tenancy.models import Workspace


class SchemaVersion(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        SUPERSEDED = "superseded", "Superseded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace, on_delete=models.PROTECT, related_name="schema_versions"
    )
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    spec_version = models.CharField(max_length=16)
    # The SSD without its envelope (workspace_id, version, status), which comes from this row.
    content = models.JSONField()
    # SHA-256 of the canonical JSON of ``content``, to detect tampering and compare versions.
    checksum = models.CharField(max_length=64)
    # The published version this draft was built on; publishing fails if that has moved.
    based_on = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["workspace", "-number"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "number"], name="schema_version_number_unique"
            ),
            models.UniqueConstraint(
                fields=["workspace"],
                condition=models.Q(status="published"),
                name="schema_version_one_published",
            ),
            models.CheckConstraint(
                condition=models.Q(number__gte=1), name="schema_version_number_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["draft", "published", "superseded"]),
                name="schema_version_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status="draft") | models.Q(published_at__isnull=False),
                name="schema_version_published_has_timestamp",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.workspace} v{self.number} ({self.status})"
