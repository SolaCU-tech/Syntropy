"""Business records, their links and the unique-value registry (spec section 9, ADR-08).

The first prototype stores every business record as one row of a shared ``business_records``
table with its scalar values in JSONB. Links live only in ``record_relationships``, never in
the JSONB, so values and links can't drift apart. Uniqueness lives in ``unique_values``.

Django can't declare composite foreign keys, so migration 0002 adds them in SQL:

* a link's source and target are ``(workspace_id, table_id, record_id)``, so a link can never
  cross workspaces or point at a record in the wrong table (a FK to the UUID alone can't
  guarantee that);
* deleting a linked-to record is refused by the database (RESTRICT) unless the store has
  already applied the relationship's delete policy;
* a record's ID, workspace and table can never change, and its JSONB must be a flat object
  of scalars keyed by field ID.

The workspace foreign keys have no single-column index on purpose: every composite index here
starts with workspace_id, and a separate workspace-only index tempted the planner into
scanning a whole workspace for each foreign-key check (found by the Phase 2 benchmark).
"""

import uuid

from django.conf import settings
from django.db import models

from apps.schema_registry.models import SchemaVersion
from apps.tenancy.models import Workspace

ID_LENGTH = 52  # "tbl_"/"fld_"/"rel_" + up to 48 characters (see the SSD models)


class BusinessRecord(models.Model):
    # Client-generated UUIDs (UUIDv7 from offline devices, ADR-27) are accepted as-is.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace, on_delete=models.PROTECT, related_name="+", db_index=False
    )
    table_id = models.CharField(max_length=ID_LENGTH)
    # The published schema version this record was last written against.
    schema_version = models.ForeignKey(SchemaVersion, on_delete=models.PROTECT, related_name="+")
    data = models.JSONField(default=dict)
    # Incremented on every change; edits must name the version they were based on.
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "business_records"
        constraints = [
            # Also the baseline (workspace_id, table_id, id) index from spec section 9, and
            # the target of the composite foreign keys added in migration 0002.
            models.UniqueConstraint(
                fields=["workspace", "table_id", "id"], name="business_record_scoped_key"
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="business_record_version_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(table_id__regex=r"^tbl_[a-z0-9_]{3,48}$"),
                name="business_record_table_id_format",
            ),
        ]
        indexes = [
            models.Index(
                fields=["workspace", "table_id", "created_at"], name="business_record_by_created"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.table_id}/{self.id} v{self.version}"


class RecordRelationship(models.Model):
    """One link from a source record's reference field to a target record."""

    workspace = models.ForeignKey(
        Workspace, on_delete=models.PROTECT, related_name="+", db_index=False
    )
    relationship_id = models.CharField(max_length=ID_LENGTH)
    from_table_id = models.CharField(max_length=ID_LENGTH)
    from_record_id = models.UUIDField()
    to_table_id = models.CharField(max_length=ID_LENGTH)
    to_record_id = models.UUIDField()
    # Copied from the SSD so the database can enforce one_to_one with a partial index.
    one_to_one = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "record_relationships"
        constraints = [
            # Every relationship is many_to_one or one_to_one: a source record has at most
            # one link per relationship. Also the outgoing-traversal index.
            models.UniqueConstraint(
                fields=["workspace", "from_record_id", "relationship_id"],
                name="record_link_one_per_source",
            ),
            models.UniqueConstraint(
                fields=["workspace", "relationship_id", "to_record_id"],
                condition=models.Q(one_to_one=True),
                name="record_link_one_to_one",
            ),
        ]
        indexes = [
            # Incoming traversal: "which sales link to this customer?"
            models.Index(
                fields=["workspace", "to_record_id", "relationship_id"],
                name="record_link_incoming",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.relationship_id}: {self.from_record_id} -> {self.to_record_id}"


class UniqueValue(models.Model):
    """The unique-value registry: one row per (unique field, value) in a workspace.

    A unique index on this table enforces uniqueness under concurrent writes; the store
    never relies on check-then-insert (spec section 9). The registry works the same for
    records synced from offline devices, which is why it was chosen over per-workspace
    expression indexes on the shared table.
    """

    workspace = models.ForeignKey(
        Workspace, on_delete=models.PROTECT, related_name="+", db_index=False
    )
    table_id = models.CharField(max_length=ID_LENGTH)
    field_id = models.CharField(max_length=ID_LENGTH)
    value_key = models.CharField(max_length=255)
    record_id = models.UUIDField()

    class Meta:
        db_table = "unique_values"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "table_id", "field_id", "value_key"],
                name="unique_value_taken",
            ),
            models.UniqueConstraint(
                fields=["workspace", "record_id", "field_id"],
                name="unique_value_one_per_record_field",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.table_id}.{self.field_id} = {self.value_key}"
