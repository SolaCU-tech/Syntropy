"""The idempotency ledger for offline sync (spec section 13, ADR-27).

Every operation a device uploads carries an idempotency key. The first time a key arrives, the
operation runs and its outcome is stored here in the same transaction as any record write, so
an outcome is recorded if and only if its effect committed. A retry with the same key gets the
stored outcome back and never writes twice, even when two retries race (the unique constraint
makes the second wait for the first, then see its row).
"""

from django.conf import settings
from django.db import models

from apps.storage.models import ID_LENGTH
from apps.tenancy.models import Workspace


class SyncOperation(models.Model):
    class Kind(models.TextChoices):
        CREATE = "create"
        UPDATE = "update"

    class Status(models.TextChoices):
        APPLIED = "applied"
        CONFLICT = "conflict"
        REJECTED = "rejected"
        SCHEMA_CHANGED = "schema_changed"

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="+", db_index=False
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    idempotency_key = models.UUIDField()
    # SHA-256 of the operation without its key: reusing a key for a different change is refused.
    request_hash = models.CharField(max_length=64)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    table_id = models.CharField(max_length=ID_LENGTH)
    record_id = models.UUIDField()
    status = models.CharField(max_length=16, choices=Status.choices)
    # The per-operation result returned to the device, replayed verbatim on a retry.
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sync_operations"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user", "idempotency_key"], name="sync_operation_key"
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "record_id"], name="sync_operation_by_record"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.table_id}/{self.record_id}: {self.status}"
