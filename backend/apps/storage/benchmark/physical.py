"""Benchmark-only prototype of the alternative: real tables per workspace (ADR-09).

Each workspace gets its own PostgreSQL schema (``ws_<hex>``), and each logical table becomes a
real table with typed columns, NOT NULL, CHECK, UNIQUE and native foreign keys with the SSD's
delete policy. DDL is compiled from the SSD by trusted code (spec section 9); no Django models
are generated at runtime.

This exists only so the benchmark compares like with like. It is not wired into the API, and
values are validated by the same ``clean_values`` as the JSONB store.
"""

import re
from typing import Any
from uuid import UUID, uuid4

import psycopg.errors
from django.db import IntegrityError, connection, transaction

from apps.schema_registry.ssd import SSD, DeletePolicy, FieldDef, LogicalType, Table

from .. import errors
from ..values import clean_values

_IDENT = re.compile(r"^(ws_[0-9a-f]{32}|(tbl|fld)_[a-z0-9_]{3,48})$")


def q(ident: str) -> str:
    """Quote an identifier. Only SSD IDs and workspace schema names are ever accepted."""
    if not _IDENT.match(ident):
        raise ValueError(f"unsafe identifier {ident!r}")
    return f'"{ident}"'


def _column_type(f: FieldDef) -> str:
    return {
        LogicalType.TEXT: "text",
        LogicalType.INTEGER: "bigint",
        LogicalType.DECIMAL: f"numeric({f.precision or 28},{f.scale or 0})",
        LogicalType.BOOLEAN: "boolean",
        LogicalType.DATE: "date",
        LogicalType.DATETIME: "timestamptz",
        LogicalType.ENUM: "text",
        LogicalType.REFERENCE: "uuid",
    }[f.type]


def _literal(value: str) -> str:
    # Values come from a validated SSD (enum keys, decimal strings), never from users.
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", value):
        raise ValueError(f"unsafe literal {value!r}")
    return f"'{value}'"


def _unique_expr(f: FieldDef) -> str:
    col = q(f.id)
    if f.type == LogicalType.TEXT:
        # Same rule as the JSONB registry: ignore case and surrounding/repeated spaces.
        return f"(lower(regexp_replace(btrim({col}), '\\s+', ' ', 'g')))"
    return f"({col})"


class PhysicalSchemaStore:
    def __init__(self, ssd: SSD, schema_name: str | None = None):
        self.ssd = ssd
        self.schema = schema_name or f"ws_{uuid4().hex}"
        q(self.schema)
        self._rel_by_field = {r.from_field: r for r in ssd.relationships}

    def t(self, table_id: str) -> str:
        return f"{q(self.schema)}.{q(table_id)}"

    # DDL

    def ddl(self) -> list[str]:
        statements = [f"CREATE SCHEMA {q(self.schema)}"]
        for table in self.ssd.tables:
            columns = [
                "id uuid PRIMARY KEY",
                "version integer NOT NULL DEFAULT 1 CHECK (version >= 1)",
                "created_at timestamptz NOT NULL DEFAULT now()",
                "updated_at timestamptz NOT NULL DEFAULT now()",
            ]
            columns += [self._column_ddl(f) for f in table.fields]
            statements.append(f"CREATE TABLE {self.t(table.id)} ({', '.join(columns)})")
            statements.append(f"CREATE INDEX ON {self.t(table.id)} (created_at)")
            for f in table.fields:
                if f.unique:
                    statements.append(
                        f"CREATE UNIQUE INDEX ON {self.t(table.id)} {_unique_expr(f)}"
                    )
        for rel in self.ssd.relationships:
            action = {
                DeletePolicy.RESTRICT: "RESTRICT",
                DeletePolicy.CASCADE: "CASCADE",
                DeletePolicy.SET_NULL: "SET NULL",
            }[rel.on_delete]
            statements.append(
                f"ALTER TABLE {self.t(rel.from_table)} ADD FOREIGN KEY ({q(rel.from_field)}) "
                f"REFERENCES {self.t(rel.to_table)} (id) ON DELETE {action}"
            )
            statements.append(f"CREATE INDEX ON {self.t(rel.from_table)} ({q(rel.from_field)})")
        return statements

    def _column_ddl(self, f: FieldDef) -> str:
        parts = [q(f.id), _column_type(f)]
        if f.required:
            parts.append("NOT NULL")
        checks = []
        col = q(f.id)
        if f.type == LogicalType.TEXT:
            checks.append(f"char_length({col}) <= {int(f.max_length or 10_000)}")
        if f.type == LogicalType.ENUM:
            keys = ", ".join(_literal(o.key) for o in f.options or [])
            checks.append(f"{col} IN ({keys})")
        if f.min_value is not None:
            checks.append(f"{col} >= {_literal(f.min_value)}")
        if f.max_value is not None:
            checks.append(f"{col} <= {_literal(f.max_value)}")
        parts += [f"CHECK ({c})" for c in checks]
        return " ".join(parts)

    def create(self) -> None:
        with transaction.atomic(), connection.cursor() as cur:
            for statement in self.ddl():
                cur.execute(statement)

    def drop(self) -> None:
        with connection.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {q(self.schema)} CASCADE")

    # Writes

    def _table(self, table_id: str) -> Table:
        table = self.ssd.table_by_id(table_id)
        if table is None:
            raise errors.UnknownTable()
        return table

    def _row(self, table: Table, values: dict[str, Any], *, creating: bool) -> dict[str, Any]:
        cleaned = clean_values(table, values, creating=creating)
        if cleaned.errors:
            raise errors.RecordValidationError(details=cleaned.errors)
        return {**cleaned.scalars, **cleaned.links}

    def _placeholders(self, table: Table, columns: list[str]) -> str:
        types = {f.id: _column_type(f) for f in table.fields}
        return ", ".join(f"%s::{types[c]}" if c in types else "%s" for c in columns)

    def create_record(
        self, table_id: str, values: dict[str, Any], record_id: UUID | None = None
    ) -> UUID:
        table = self._table(table_id)
        row = self._row(table, values, creating=True)
        record_id = record_id or uuid4()
        columns = ["id", *row]
        cols = ", ".join(q(c) if c != "id" else c for c in columns)
        sql = (
            f"INSERT INTO {self.t(table_id)} ({cols}) VALUES ({self._placeholders(table, columns)})"
        )
        self._execute(sql, [record_id, *row.values()])
        return record_id

    def import_records(self, table_id: str, rows: list[dict[str, Any]]) -> list[UUID]:
        table = self._table(table_id)
        cleaned, row_errors = [], {}
        for i, values in enumerate(rows):
            try:
                cleaned.append(self._row(table, values, creating=True))
            except errors.RecordValidationError as exc:
                row_errors[i] = exc.details
        if row_errors:
            raise errors.ImportValidationError(row_errors)
        columns = ["id", *[f.id for f in table.fields]]
        placeholders = f"({self._placeholders(table, columns)})"
        ids = [uuid4() for _ in cleaned]
        with transaction.atomic():
            for start in range(0, len(cleaned), 1000):
                chunk = cleaned[start : start + 1000]
                params: list[Any] = []
                for rid, row in zip(ids[start : start + 1000], chunk, strict=True):
                    params.append(rid)
                    params.extend(row.get(f.id) for f in table.fields)
                cols = ", ".join(q(c) if c != "id" else c for c in columns)
                sql = f"INSERT INTO {self.t(table_id)} ({cols}) VALUES " + ", ".join(
                    [placeholders] * len(chunk)
                )
                self._execute(sql, params)
        return ids

    def update(
        self, table_id: str, record_id: UUID, values: dict[str, Any], *, expected_version: int
    ) -> int:
        table = self._table(table_id)
        row = self._row(table, values, creating=False)
        sets = ", ".join(f"{q(c)} = {self._placeholders(table, [c])}" for c in row)
        sql = (
            f"UPDATE {self.t(table_id)} SET {sets}, version = version + 1, updated_at = now() "
            "WHERE id = %s AND version = %s RETURNING version"
        )
        with connection.cursor() as cur:
            try:
                with transaction.atomic():
                    cur.execute(sql, [*row.values(), record_id, expected_version])
                    result = cur.fetchone()
            except IntegrityError as exc:
                raise self._translate(exc) from None
        if result is None:
            raise errors.VersionConflict(current=None)
        return result[0]

    def get(self, table_id: str, record_id: UUID) -> dict[str, Any]:
        self._table(table_id)
        with connection.cursor() as cur:
            cur.execute(f"SELECT * FROM {self.t(table_id)} WHERE id = %s", [record_id])
            row = cur.fetchone()
            if row is None:
                raise errors.RecordNotFound()
            return dict(zip([c.name for c in cur.description], row, strict=True))

    def delete(self, table_id: str, record_id: UUID) -> None:
        self._table(table_id)
        self._execute(f"DELETE FROM {self.t(table_id)} WHERE id = %s", [record_id])

    def _execute(self, sql: str, params: list[Any]) -> None:
        try:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(sql, params)
        except IntegrityError as exc:
            raise self._translate(exc) from None

    @staticmethod
    def _translate(exc: IntegrityError) -> errors.StorageError:
        cause = exc.__cause__
        if isinstance(cause, psycopg.errors.UniqueViolation):
            return errors.DuplicateValue()
        if isinstance(cause, psycopg.errors.ForeignKeyViolation):
            if "still referenced" in str(cause) or "is still referenced" in str(cause):
                return errors.RecordInUse()
            return errors.InvalidReference()
        if isinstance(cause, psycopg.errors.NotNullViolation | psycopg.errors.CheckViolation):
            return errors.RecordValidationError()
        return errors.StorageError(str(cause))
