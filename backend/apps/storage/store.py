"""The JSONB record store: the only code that writes business records (ADR-08, ADR-12).

Every write validates against the workspace's active SSD, runs in one transaction, and relies
on database constraints rather than check-then-insert for anything another writer could race:

* uniqueness through ``unique_values`` (INSERT ... ON CONFLICT DO NOTHING);
* links through composite foreign keys, so a target deleted mid-write fails the write;
* edits through the record version (optimistic concurrency, ADR-27), with the row locked.

The friendly checks done before writing (does the linked record exist?) only produce better
error messages; the database has the final say.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import F, Q, QuerySet
from django.utils import timezone

from apps.schema_registry.models import SchemaVersion
from apps.schema_registry.ssd import (
    Cardinality,
    DeletePolicy,
    FieldDef,
    LogicalType,
    Relationship,
    Table,
)
from apps.tenancy.models import Workspace

from .errors import (
    DuplicateValue,
    ImportValidationError,
    InvalidReference,
    RecordExists,
    RecordInUse,
    RecordNotFound,
    RecordValidationError,
    VersionConflict,
)
from .models import BusinessRecord, RecordRelationship, UniqueValue
from .schema import ActiveSchema, active_schema
from .values import CleanedValues, clean_values, reference_fields, unique_fields, unique_key

IMPORT_BATCH_SIZE = 1000


@dataclass(frozen=True)
class StoredRecord:
    """A record as the API and engines see it: scalars and links merged, keyed by field ID."""

    id: UUID
    table_id: str
    version: int
    schema_version: int
    values: dict[str, Any]
    created_by_id: int | None
    created_at: datetime
    updated_at: datetime


def _constraint_name(exc: IntegrityError) -> str | None:
    diag = getattr(exc.__cause__, "diag", None)
    return getattr(diag, "constraint_name", None)


class JsonbRecordStore:
    """Workspace-scoped record operations. Build one per request with ``get_record_store``;
    the workspace must come from the resolver, never from client input."""

    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self._schema: ActiveSchema | None = None

    @property
    def schema(self) -> ActiveSchema:
        if self._schema is None:
            self._schema = active_schema(self.workspace)
        return self._schema

    # Reading

    def queryset(self, table_id: str) -> QuerySet[BusinessRecord]:
        self.schema.table(table_id)
        return BusinessRecord.objects.filter(workspace=self.workspace, table_id=table_id)

    def get(self, table_id: str, record_id: UUID | str) -> StoredRecord:
        row = self._get_row(table_id, record_id)
        return self.hydrate(table_id, [row])[0]

    def hydrate(self, table_id: str, rows: Sequence[BusinessRecord]) -> list[StoredRecord]:
        """Turn rows into StoredRecords, attaching links with one query."""
        table = self.schema.table(table_id)
        ref_fields = {
            self.schema.relationship_by_field[f.id].id: f.id for f in reference_fields(table)
        }
        links: dict[UUID, dict[str, str]] = defaultdict(dict)
        if ref_fields and rows:
            for link in RecordRelationship.objects.filter(
                workspace=self.workspace,
                from_record_id__in=[r.id for r in rows],
                relationship_id__in=list(ref_fields),
            ).values("from_record_id", "relationship_id", "to_record_id"):
                field_id = ref_fields[link["relationship_id"]]
                links[link["from_record_id"]][field_id] = str(link["to_record_id"])
        versions = {self.schema.version.pk: self.schema.version.number}
        missing = {r.schema_version_id for r in rows} - set(versions)
        if missing:
            versions.update(
                SchemaVersion.objects.filter(pk__in=missing).values_list("pk", "number")
            )
        return [
            self._stored(table, row, links[row.id], versions[row.schema_version_id]) for row in rows
        ]

    @staticmethod
    def _stored(
        table: Table, row: BusinessRecord, links: dict[str, str], schema_number: int
    ) -> StoredRecord:
        values = {
            f.id: links.get(f.id) if f.type == LogicalType.REFERENCE else row.data.get(f.id)
            for f in table.fields
        }
        return StoredRecord(
            id=row.id,
            table_id=row.table_id,
            version=row.version,
            schema_version=schema_number,
            values=values,
            created_by_id=row.created_by_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _get_row(self, table_id: str, record_id: UUID | str, *, lock: bool = False):
        qs = self.queryset(table_id)
        if lock:
            qs = qs.select_for_update()
        try:
            return qs.get(id=record_id)
        except (BusinessRecord.DoesNotExist, DjangoValidationError, ValueError, TypeError):
            raise RecordNotFound() from None

    # Creating

    def create(
        self,
        table_id: str,
        values: dict[str, Any],
        *,
        record_id: UUID | None = None,
        actor=None,
    ) -> StoredRecord:
        table = self.schema.table(table_id)
        cleaned = clean_values(table, values, creating=True)
        if cleaned.errors:
            raise RecordValidationError(details=cleaned.errors)
        self._check_link_targets(cleaned)

        data = {k: v for k, v in cleaned.scalars.items() if v is not None}
        try:
            with transaction.atomic():
                row = BusinessRecord(
                    workspace=self.workspace,
                    table_id=table_id,
                    schema_version=self.schema.version,
                    data=data,
                    created_by=actor,
                    updated_by=actor,
                )
                if record_id is not None:
                    row.id = record_id
                row.save(force_insert=True)
                self._claim_unique_values(table_id, unique_fields(table), [(row.id, data)])
                self._write_links(table, row.id, cleaned.links)
        except IntegrityError as exc:
            raise self._translate(exc, cleaned) from None
        links = {f: str(t) for f, t in cleaned.links.items() if t is not None}
        return self._stored(table, row, links, self.schema.version.number)

    # Editing

    def update(
        self,
        table_id: str,
        record_id: UUID | str,
        values: dict[str, Any],
        *,
        expected_version: int,
        actor=None,
    ) -> StoredRecord:
        table = self.schema.table(table_id)
        cleaned = clean_values(table, values, creating=False)
        try:
            with transaction.atomic():
                row = self._update_locked(table, record_id, cleaned, expected_version, actor)
        except IntegrityError as exc:
            raise self._translate(exc, cleaned) from None
        return self.hydrate(table_id, [row])[0]

    def _update_locked(
        self,
        table: Table,
        record_id: UUID | str,
        cleaned: CleanedValues,
        expected_version: int,
        actor,
    ) -> BusinessRecord:
        table_id = table.id
        row = self._get_row(table_id, record_id, lock=True)
        if row.version != expected_version:
            raise VersionConflict(self.hydrate(table_id, [row])[0])
        if cleaned.errors:
            raise RecordValidationError(details=cleaned.errors)
        self._check_link_targets(cleaned)

        data = dict(row.data)
        for field_id, value in cleaned.scalars.items():
            if value is None:
                data.pop(field_id, None)
            else:
                data[field_id] = value
        changed_unique = [f for f in unique_fields(table) if row.data.get(f.id) != data.get(f.id)]
        if changed_unique:
            UniqueValue.objects.filter(
                workspace=self.workspace,
                record_id=row.id,
                field_id__in=[f.id for f in changed_unique],
            ).delete()
            self._claim_unique_values(table_id, changed_unique, [(row.id, data)])
        self._write_links(table, row.id, cleaned.links, replace=True)

        row.data = data
        row.version = row.version + 1
        row.schema_version = self.schema.version
        row.updated_by = actor
        row.save(update_fields=["data", "version", "schema_version", "updated_by", "updated_at"])
        return row

    # Deleting

    def delete(
        self,
        table_id: str,
        record_id: UUID | str,
        *,
        expected_version: int | None = None,
        actor=None,
    ) -> list[UUID]:
        """Delete a record, applying each incoming relationship's delete policy.

        Returns the IDs of every record deleted (more than one when a cascade applies).
        Raises RecordInUse if a restrict relationship still has links; nothing is deleted.
        """
        with transaction.atomic():
            row = self._get_row(table_id, record_id, lock=True)
            if expected_version is not None and row.version != expected_version:
                raise VersionConflict(self.hydrate(table_id, [row])[0])
            deleted: list[UUID] = []
            self._delete_row(row, deleted, actor, seen=set())
            return deleted

    def _delete_row(self, row: BusinessRecord, deleted: list[UUID], actor, seen: set) -> None:
        if row.id in seen:
            return
        seen.add(row.id)
        links = list(
            RecordRelationship.objects.select_for_update()
            .filter(workspace=self.workspace, to_record_id=row.id)
            .exclude(from_record_id=row.id)
        )
        by_rel: dict[str, list[RecordRelationship]] = defaultdict(list)
        for link in links:
            by_rel[link.relationship_id].append(link)

        blocking: dict[str, list[str]] = {}
        for rel_id, rel_links in by_rel.items():
            rel = self.schema.relationships_by_id.get(rel_id)
            # Links from a relationship the current schema no longer has are kept safe.
            policy = rel.on_delete if rel is not None else DeletePolicy.RESTRICT
            if policy == DeletePolicy.RESTRICT:
                label = rel.description if rel is not None else rel_id
                blocking[rel_id] = [f"{len(rel_links)} linked record(s): {label}"]
        if blocking:
            raise RecordInUse(details=blocking)

        for rel_id, rel_links in by_rel.items():
            rel = self.schema.relationships_by_id[rel_id]
            source_ids = [link.from_record_id for link in rel_links]
            if rel.on_delete == DeletePolicy.SET_NULL:
                RecordRelationship.objects.filter(pk__in=[link.pk for link in rel_links]).delete()
                BusinessRecord.objects.filter(workspace=self.workspace, id__in=source_ids).update(
                    version=F("version") + 1, updated_by=actor, updated_at=timezone.now()
                )
            elif rel.on_delete == DeletePolicy.CASCADE:
                sources = BusinessRecord.objects.select_for_update().filter(
                    workspace=self.workspace, table_id=rel.from_table, id__in=source_ids
                )
                for source in sources:
                    self._delete_row(source, deleted, actor, seen)

        BusinessRecord.objects.filter(pk=row.pk).delete()
        deleted.append(row.id)

    # Bulk import (Phase 5 activation and the benchmark use this)

    def import_records(
        self,
        table_id: str,
        rows: Sequence[dict[str, Any]],
        *,
        record_ids: Sequence[UUID] | None = None,
        actor=None,
    ) -> list[UUID]:
        """Validate every row, then insert them all in one transaction or none at all."""
        table = self.schema.table(table_id)
        row_errors: dict[int, dict[str, list[str]]] = {}
        cleaned_rows: list[CleanedValues] = []
        for i, values in enumerate(rows):
            cleaned = clean_values(table, values, creating=True)
            if cleaned.errors:
                row_errors[i] = cleaned.errors
            cleaned_rows.append(cleaned)

        # Duplicates inside the batch itself.
        for f in unique_fields(table):
            first_seen: dict[str, int] = {}
            for i, cleaned in enumerate(cleaned_rows):
                value = cleaned.scalars.get(f.id)
                if value is None:
                    continue
                key = unique_key(f, value)
                if key in first_seen:
                    row_errors.setdefault(i, {}).setdefault(f.id, []).append(
                        f"Same value as row {first_seen[key]}."
                    )
                else:
                    first_seen[key] = i

        # Links to records that don't exist (in this workspace and the right table).
        for f in reference_fields(table):
            rel = self.schema.relationship_by_field[f.id]
            targets = {c.links[f.id] for c in cleaned_rows if c.links.get(f.id)}
            existing = self._existing_ids(rel.to_table, targets)
            for i, cleaned in enumerate(cleaned_rows):
                target = cleaned.links.get(f.id)
                if target is not None and target not in existing:
                    row_errors.setdefault(i, {}).setdefault(f.id, []).append(
                        InvalidReference.message
                    )
        if row_errors:
            raise ImportValidationError(row_errors)

        records = []
        for i, cleaned in enumerate(cleaned_rows):
            record = BusinessRecord(
                workspace=self.workspace,
                table_id=table_id,
                schema_version=self.schema.version,
                data={k: v for k, v in cleaned.scalars.items() if v is not None},
                created_by=actor,
                updated_by=actor,
            )
            if record_ids is not None:
                record.id = record_ids[i]
            records.append(record)

        try:
            with transaction.atomic():
                BusinessRecord.objects.bulk_create(records, batch_size=IMPORT_BATCH_SIZE)
                index_of = {r.id: i for i, r in enumerate(records)}
                try:
                    self._claim_unique_values(
                        table_id, unique_fields(table), [(r.id, r.data) for r in records]
                    )
                except DuplicateValue as exc:
                    raise ImportValidationError(
                        {
                            index_of[rid]: {fid: [DuplicateValue.message]}
                            for rid, fid in exc.conflicts
                        }
                    ) from None
                links = [
                    self._link(table_id, records[i].id, self.schema.relationship_by_field[fid], t)
                    for i, cleaned in enumerate(cleaned_rows)
                    for fid, t in cleaned.links.items()
                    if t is not None
                ]
                RecordRelationship.objects.bulk_create(links, batch_size=IMPORT_BATCH_SIZE)
        except IntegrityError as exc:
            name = _constraint_name(exc)
            if name == "business_records_pkey":
                raise RecordExists() from None
            if name == "record_link_to_record":
                raise InvalidReference(
                    "A linked record was deleted during the import. Nothing was imported."
                ) from None
            if name == "record_link_one_to_one":
                raise DuplicateValue(
                    "Two records link to the same record where only one may."
                ) from None
            raise
        return [r.id for r in records]

    # Internals

    def _existing_ids(self, table_id: str, ids: Iterable[UUID]) -> set[UUID]:
        ids = list(ids)
        found: set[UUID] = set()
        for start in range(0, len(ids), 5000):
            found.update(
                BusinessRecord.objects.filter(
                    workspace=self.workspace, table_id=table_id, id__in=ids[start : start + 5000]
                ).values_list("id", flat=True)
            )
        return found

    def _missing_link_targets(self, cleaned: CleanedValues) -> dict[str, list[str]]:
        """Reference fields whose target isn't a record of the right table in this workspace,
        checked with one query."""
        wanted = {
            field_id: (self.schema.relationship_by_field[field_id].to_table, target)
            for field_id, target in cleaned.links.items()
            if target is not None
        }
        if not wanted:
            return {}
        match = Q()
        for to_table, target in wanted.values():
            match |= Q(table_id=to_table, id=target)
        found = set(
            BusinessRecord.objects.filter(match, workspace=self.workspace).values_list(
                "table_id", "id"
            )
        )
        return {f: [InvalidReference.message] for f, key in wanted.items() if key not in found}

    def _check_link_targets(self, cleaned: CleanedValues) -> None:
        missing = self._missing_link_targets(cleaned)
        if missing:
            raise InvalidReference(details=missing)

    def _translate(self, exc: IntegrityError, cleaned: CleanedValues) -> Exception:
        """Turn a constraint violation from a concurrent writer into a store error."""
        name = _constraint_name(exc)
        if name == "business_records_pkey":
            return RecordExists()
        if name == "record_link_to_record":
            # A linked record was deleted after the friendly check; say which one.
            return InvalidReference(details=self._missing_link_targets(cleaned) or None)
        if name == "record_link_one_to_one":
            fields = [f for f, t in cleaned.links.items() if t is not None]
            return DuplicateValue(
                details={f: ["Another record already links to this one."] for f in fields}
            )
        return exc

    def _link(
        self, from_table: str, from_id: UUID, rel: Relationship, to_id: UUID
    ) -> RecordRelationship:
        return RecordRelationship(
            workspace=self.workspace,
            relationship_id=rel.id,
            from_table_id=from_table,
            from_record_id=from_id,
            to_table_id=rel.to_table,
            to_record_id=to_id,
            one_to_one=rel.cardinality == Cardinality.ONE_TO_ONE,
        )

    def _write_links(
        self,
        table: Table,
        record_id: UUID,
        links: dict[str, UUID | None],
        *,
        replace: bool = False,
    ) -> None:
        """Write a record's links. Constraint violations propagate to ``_translate``."""
        rels = {f: self.schema.relationship_by_field[f] for f in links}
        if replace and rels:
            RecordRelationship.objects.filter(
                workspace=self.workspace,
                from_record_id=record_id,
                relationship_id__in=[r.id for r in rels.values()],
            ).delete()
        new = [
            self._link(table.id, record_id, rels[f], target)
            for f, target in links.items()
            if target is not None
        ]
        if new:
            RecordRelationship.objects.bulk_create(new)

    def _claim_unique_values(
        self,
        table_id: str,
        fields: list[FieldDef],
        records: list[tuple[UUID, dict[str, Any]]],
    ) -> None:
        """Insert unique-value rows; raise DuplicateValue naming every value already taken.

        ON CONFLICT DO NOTHING waits for any concurrent transaction holding the same value
        and then sees its outcome, so two writers racing for one value can't both win.
        """
        wanted: list[tuple[str, str, UUID]] = []
        for f in fields:
            for rid, data in records:
                value = data.get(f.id)
                if value is not None:
                    wanted.append((f.id, unique_key(f, value), rid))
        if not wanted:
            return
        claimed: set[tuple[UUID, str]] = set()
        with connection.cursor() as cursor:
            for start in range(0, len(wanted), 5000):
                chunk = wanted[start : start + 5000]
                cursor.execute(
                    """
                    INSERT INTO unique_values
                        (workspace_id, table_id, field_id, value_key, record_id)
                    SELECT %s, %s, item.field_id, item.value_key, item.record_id
                    FROM unnest(%s::text[], %s::text[], %s::uuid[])
                        AS item(field_id, value_key, record_id)
                    ON CONFLICT DO NOTHING
                    RETURNING record_id, field_id
                    """,
                    [
                        self.workspace.pk,
                        table_id,
                        [w[0] for w in chunk],
                        [w[1] for w in chunk],
                        [w[2] for w in chunk],
                    ],
                )
                claimed.update((rid, fid) for rid, fid in cursor.fetchall())
        conflicts = [(rid, fid) for fid, _key, rid in wanted if (rid, fid) not in claimed]
        if conflicts:
            exc = DuplicateValue(details={fid: [DuplicateValue.message] for _rid, fid in conflicts})
            exc.conflicts = conflicts
            raise exc


def get_record_store(workspace: Workspace) -> JsonbRecordStore:
    """The storage adapter for a workspace, chosen by the Workspace Registry (ADR-12).

    Only the shared JSONB backend exists today; a per-workspace physical backend (ADR-09)
    would be returned here without the API changing.
    """
    if workspace.storage_backend != "shared_jsonb":  # pragma: no cover
        raise NotImplementedError(f"Unknown storage backend {workspace.storage_backend!r}")
    return JsonbRecordStore(workspace)
