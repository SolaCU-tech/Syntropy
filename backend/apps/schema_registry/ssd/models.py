"""Syntropy Schema Definition (SSD) v1 as Pydantic models.

The SSD is the canonical, versioned JSON description of a workspace's structure: logical
tables, fields, relationships and source mappings (spec section 8). It never contains SQL and
is independent of how records are stored (ADR-07).

Every rule the backend relies on is checked here, so an SSD that parses is safe to publish.
Rule violations raise errors with stable ``ssd_*`` codes, which tests and (later) the AI QA
pass can match on.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)
from pydantic_core import PydanticCustomError

from .naming import MACHINE_KEY_PATTERN, MAX_KEY_LENGTH, RESERVED_KEYS

SPEC_VERSION = "1.0"

# Limits keep a single schema reviewable and every query plan bounded.
MAX_TABLES = 100
MAX_FIELDS_PER_TABLE = 200
MAX_RELATIONSHIPS = 500
MAX_ENUM_OPTIONS = 100
MAX_SOURCE_MAPPINGS = 5000
MAX_DECIMAL_PRECISION = 28
MAX_DECIMAL_SCALE = 10

# Immutable IDs. The registry generates them as prefix + hex; hand-written examples may use
# readable ones such as ``tbl_customers``.
TableId = Annotated[str, StringConstraints(pattern=r"^tbl_[a-z0-9_]{3,48}$")]
FieldId = Annotated[str, StringConstraints(pattern=r"^fld_[a-z0-9_]{3,48}$")]
RelationshipId = Annotated[str, StringConstraints(pattern=r"^rel_[a-z0-9_]{3,48}$")]
MappingId = Annotated[str, StringConstraints(pattern=r"^map_[a-z0-9_]{3,48}$")]

MachineKey = Annotated[
    str, StringConstraints(pattern=MACHINE_KEY_PATTERN, max_length=MAX_KEY_LENGTH)
]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
IconName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=64)]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
# Decimals travel as strings, never floats (ADR-25).
DecimalString = Annotated[str, StringConstraints(pattern=r"^-?\d{1,28}(\.\d{1,10})?$")]


class LogicalType(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    ENUM = "enum"
    REFERENCE = "reference"


class DisplayRole(StrEnum):
    """How the UI, reports and insights should treat a field."""

    TITLE = "title"  # the record's name in lists and link pickers; text, one per table
    MONEY = "money"  # a decimal with a currency
    QUANTITY = "quantity"  # an integer or decimal count of things
    STATUS = "status"  # an enum shown as a badge
    DATE = "date"  # the date that places a record in time (for period reports)


class Cardinality(StrEnum):
    MANY_TO_ONE = "many_to_one"  # many sales -> one customer
    ONE_TO_ONE = "one_to_one"  # requires the reference field to be unique


class DeletePolicy(StrEnum):
    RESTRICT = "restrict"  # the default: a referenced record can't be deleted
    CASCADE = "cascade"
    SET_NULL = "set_null"  # only for optional relationships


class Transform(StrEnum):
    """Deterministic transforms applied to a source value during import (Phase 4)."""

    NONE = "none"
    TRIM = "trim"
    PARSE_INTEGER = "parse_integer"
    PARSE_DECIMAL = "parse_decimal"
    PARSE_MONEY = "parse_money"
    PARSE_DATE_DAY_FIRST = "parse_date_day_first"
    PARSE_DATE_MONTH_FIRST = "parse_date_month_first"
    PARSE_DATETIME = "parse_datetime"
    PARSE_BOOLEAN = "parse_boolean"
    ENUM_LOOKUP = "enum_lookup"
    LINK_LOOKUP = "link_lookup"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _error(code: str, message: str, **ctx: object) -> PydanticCustomError:
    return PydanticCustomError(f"ssd_{code}", message, ctx or None)


def _reserved_key_check(key: str, where: str) -> None:
    if key in RESERVED_KEYS:
        raise _error("reserved_key", "{where} key '{key}' is a reserved word", where=where, key=key)


class EnumOption(_Model):
    key: MachineKey
    label: Label


class Provenance(_Model):
    """Where a field came from: who proposed it and from which source column."""

    origin: Literal["manual", "ai", "import"] = "manual"
    source_file: Description | None = None
    source_column: Description | None = None
    note: Description | None = None


class FieldDef(_Model):
    id: FieldId
    key: MachineKey
    label: Label
    description: Description | None = None
    type: LogicalType
    required: bool = False
    unique: bool = False
    default: StrictStr | StrictBool | StrictInt | None = None
    min_value: DecimalString | None = None
    max_value: DecimalString | None = None
    max_length: Annotated[int, Field(ge=1, le=10_000)] | None = None
    precision: Annotated[int, Field(ge=1, le=MAX_DECIMAL_PRECISION)] | None = None
    scale: Annotated[int, Field(ge=0, le=MAX_DECIMAL_SCALE)] | None = None
    currency: CurrencyCode | None = None
    options: Annotated[list[EnumOption], Field(max_length=MAX_ENUM_OPTIONS)] | None = None
    display_role: DisplayRole | None = None
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def _check_type_rules(self) -> "FieldDef":
        _reserved_key_check(self.key, "Field")
        t = self.type
        where = f"Field '{self.key}'"

        allowed_extras = {
            LogicalType.TEXT: {"max_length"},
            LogicalType.INTEGER: {"min_value", "max_value"},
            LogicalType.DECIMAL: {"min_value", "max_value", "precision", "scale", "currency"},
            LogicalType.ENUM: {"options"},
        }.get(t, set())
        for extra in ("max_length", "min_value", "max_value", "precision", "scale", "currency"):
            if getattr(self, extra) is not None and extra not in allowed_extras:
                raise _error(
                    "constraint_not_allowed",
                    "{where}: '{extra}' does not apply to type '{type}'",
                    where=where,
                    extra=extra,
                    type=t.value,
                )
        if self.options is not None and t != LogicalType.ENUM:
            raise _error(
                "constraint_not_allowed",
                "{where}: 'options' only apply to enum fields",
                where=where,
            )

        if t == LogicalType.ENUM:
            if not self.options:
                raise _error("enum_without_options", "{where}: enum needs options", where=where)
            keys = [o.key for o in self.options]
            if len(keys) != len(set(keys)):
                raise _error(
                    "duplicate_option", "{where}: enum option keys must be unique", where=where
                )

        if t == LogicalType.DECIMAL:
            if self.scale is None:
                raise _error("decimal_without_scale", "{where}: decimal needs a scale", where=where)
            if self.precision is not None and self.precision < self.scale:
                raise _error(
                    "invalid_precision",
                    "{where}: precision must be at least the scale",
                    where=where,
                )

        if t == LogicalType.INTEGER:
            for bound in (self.min_value, self.max_value):
                if bound is not None and "." in bound:
                    raise _error(
                        "invalid_range", "{where}: integer bounds must be whole", where=where
                    )

        if (
            self.min_value is not None
            and self.max_value is not None
            and Decimal(self.min_value) > Decimal(self.max_value)
        ):
            raise _error("invalid_range", "{where}: min_value is above max_value", where=where)

        if t == LogicalType.REFERENCE and self.default is not None:
            raise _error(
                "invalid_default", "{where}: a reference field can't have a default", where=where
            )
        if self.default is not None:
            self._check_default(where)

        self._check_display_role(where)
        return self

    def _check_default(self, where: str) -> None:
        value, t = self.default, self.type
        ok = False
        if t == LogicalType.TEXT:
            ok = isinstance(value, str) and (
                self.max_length is None or len(value) <= self.max_length
            )
        elif t == LogicalType.INTEGER:
            ok = isinstance(value, int) and not isinstance(value, bool)
            ok = ok and self._within_range(Decimal(value))
        elif t == LogicalType.DECIMAL:
            ok = isinstance(value, str) and self._decimal_fits(value)
        elif t == LogicalType.BOOLEAN:
            ok = isinstance(value, bool)
        elif t == LogicalType.DATE:
            ok = isinstance(value, str) and _parses(date.fromisoformat, value)
        elif t == LogicalType.DATETIME:
            ok = isinstance(value, str) and _parses(datetime.fromisoformat, value)
        elif t == LogicalType.ENUM:
            ok = isinstance(value, str) and value in {o.key for o in self.options or []}
        if not ok:
            raise _error(
                "invalid_default",
                "{where}: default {value!r} is not a valid {type}",
                where=where,
                value=value,
                type=t.value,
            )

    def _decimal_fits(self, value: str) -> bool:
        if not re.fullmatch(r"-?\d+(\.\d+)?", value):
            return False
        try:
            d = Decimal(value)
        except InvalidOperation:
            return False
        exponent = d.as_tuple().exponent
        decimals = -exponent if isinstance(exponent, int) and exponent < 0 else 0
        if self.scale is not None and decimals > self.scale:
            return False
        digits = len(d.as_tuple().digits)
        if self.precision is not None and digits > self.precision:
            return False
        return self._within_range(d)

    def _within_range(self, d: Decimal) -> bool:
        if self.min_value is not None and d < Decimal(self.min_value):
            return False
        return not (self.max_value is not None and d > Decimal(self.max_value))

    def _check_display_role(self, where: str) -> None:
        role, t = self.display_role, self.type
        if role is None:
            return
        fits = {
            DisplayRole.TITLE: t == LogicalType.TEXT,
            DisplayRole.MONEY: t == LogicalType.DECIMAL and self.currency is not None,
            DisplayRole.QUANTITY: t in (LogicalType.INTEGER, LogicalType.DECIMAL),
            DisplayRole.STATUS: t == LogicalType.ENUM,
            DisplayRole.DATE: t in (LogicalType.DATE, LogicalType.DATETIME),
        }[role]
        if not fits:
            raise _error(
                "invalid_display_role",
                "{where}: display role '{role}' doesn't fit type '{type}'",
                where=where,
                role=role.value,
                type=t.value,
            )


class Table(_Model):
    id: TableId
    key: MachineKey
    label: Label
    description: Description | None = None
    icon: IconName | None = None  # a Lucide icon name, e.g. "users"
    fields: Annotated[list[FieldDef], Field(min_length=1, max_length=MAX_FIELDS_PER_TABLE)]

    @model_validator(mode="after")
    def _check_fields(self) -> "Table":
        _reserved_key_check(self.key, "Table")
        keys = [f.key for f in self.fields]
        duplicates = sorted({k for k in keys if keys.count(k) > 1})
        if duplicates:
            raise _error(
                "duplicate_key",
                "Table '{table}' has duplicate field keys: {keys}",
                table=self.key,
                keys=", ".join(duplicates),
            )
        titles = [f.key for f in self.fields if f.display_role == DisplayRole.TITLE]
        if len(titles) > 1:
            raise _error(
                "multiple_title_fields",
                "Table '{table}' has more than one title field",
                table=self.key,
            )
        return self

    def field_by_id(self, field_id: str) -> FieldDef | None:
        return next((f for f in self.fields if f.id == field_id), None)


class Relationship(_Model):
    """A link from a reference field on one table to a record in another.

    ``to_field`` is omitted when the link points at the target record itself (the usual
    case); when set, it must be a unique field on the target table.
    """

    id: RelationshipId
    from_table: TableId
    from_field: FieldId
    to_table: TableId
    to_field: FieldId | None = None
    cardinality: Cardinality = Cardinality.MANY_TO_ONE
    optional: bool
    on_delete: DeletePolicy = DeletePolicy.RESTRICT
    description: Label  # a plain sentence: "Each sale belongs to one customer"

    @model_validator(mode="after")
    def _check_policy(self) -> "Relationship":
        if self.on_delete == DeletePolicy.SET_NULL and not self.optional:
            raise _error(
                "invalid_delete_policy",
                "Relationship '{id}': set_null needs an optional relationship",
                id=self.id,
            )
        return self


class SourceMapping(_Model):
    """Links one column of an uploaded file to a field (spec section 8)."""

    id: MappingId
    source_file: Label
    sheet: Label | None = None
    column: Label
    table: TableId
    field: FieldId
    transform: Transform = Transform.NONE


class SSD(_Model):
    """A complete Syntropy Schema Definition document."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        title="SSD",
    )

    spec_version: Literal["1.0"]
    # The envelope below is stamped by the registry; hand-written drafts may leave it out.
    workspace_id: UUID | None = None
    version: Annotated[int, Field(ge=1)] | None = None
    status: Literal["draft", "published", "superseded"] = "draft"
    tables: Annotated[list[Table], Field(min_length=1, max_length=MAX_TABLES)]
    relationships: Annotated[list[Relationship], Field(max_length=MAX_RELATIONSHIPS)] = []
    source_mappings: Annotated[list[SourceMapping], Field(max_length=MAX_SOURCE_MAPPINGS)] = []

    @model_validator(mode="after")
    def _check_document(self) -> "SSD":
        self._check_unique_ids()
        tables = {t.id: t for t in self.tables}
        self._check_unique_table_keys()
        self._check_relationships(tables)
        self._check_mappings(tables)
        return self

    def _check_unique_ids(self) -> None:
        ids: list[str] = []
        for t in self.tables:
            ids.append(t.id)
            ids.extend(f.id for f in t.fields)
        ids.extend(r.id for r in self.relationships)
        ids.extend(m.id for m in self.source_mappings)
        seen: set[str] = set()
        for i in ids:
            if i in seen:
                raise _error("duplicate_id", "ID '{id}' is used more than once", id=i)
            seen.add(i)

    def _check_unique_table_keys(self) -> None:
        keys = [t.key for t in self.tables]
        duplicates = sorted({k for k in keys if keys.count(k) > 1})
        if duplicates:
            raise _error(
                "duplicate_key", "Duplicate table keys: {keys}", keys=", ".join(duplicates)
            )

    def _check_relationships(self, tables: dict[str, Table]) -> None:
        linked_fields: set[str] = set()
        for rel in self.relationships:
            source = tables.get(rel.from_table)
            target = tables.get(rel.to_table)
            if source is None or target is None:
                raise _error(
                    "unknown_reference",
                    "Relationship '{id}' points at a table that doesn't exist",
                    id=rel.id,
                )
            field = source.field_by_id(rel.from_field)
            if field is None:
                raise _error(
                    "unknown_reference",
                    "Relationship '{id}': field '{field}' is not on table '{table}'",
                    id=rel.id,
                    field=rel.from_field,
                    table=source.key,
                )
            if field.type != LogicalType.REFERENCE:
                raise _error(
                    "invalid_relationship",
                    "Relationship '{id}': '{field}' must be a reference field",
                    id=rel.id,
                    field=field.key,
                )
            if rel.from_field in linked_fields:
                raise _error(
                    "invalid_relationship",
                    "Field '{field}' is used by more than one relationship",
                    field=field.key,
                )
            linked_fields.add(rel.from_field)
            if rel.optional == field.required:
                raise _error(
                    "invalid_relationship",
                    "Relationship '{id}': optional must be the opposite of '{field}'.required",
                    id=rel.id,
                    field=field.key,
                )
            if rel.cardinality == Cardinality.ONE_TO_ONE and not field.unique:
                raise _error(
                    "invalid_relationship",
                    "Relationship '{id}': one_to_one needs '{field}' to be unique",
                    id=rel.id,
                    field=field.key,
                )
            if rel.to_field is not None:
                target_field = target.field_by_id(rel.to_field)
                if target_field is None:
                    raise _error(
                        "unknown_reference",
                        "Relationship '{id}': field '{field}' is not on table '{table}'",
                        id=rel.id,
                        field=rel.to_field,
                        table=target.key,
                    )
                if not target_field.unique:
                    raise _error(
                        "invalid_relationship",
                        "Relationship '{id}': target field '{field}' must be unique",
                        id=rel.id,
                        field=target_field.key,
                    )

        for table in self.tables:
            for field in table.fields:
                if field.type == LogicalType.REFERENCE and field.id not in linked_fields:
                    raise _error(
                        "orphan_reference_field",
                        "Reference field '{table}.{field}' has no relationship",
                        table=table.key,
                        field=field.key,
                    )

    def _check_mappings(self, tables: dict[str, Table]) -> None:
        for mapping in self.source_mappings:
            table = tables.get(mapping.table)
            if table is None or table.field_by_id(mapping.field) is None:
                raise _error(
                    "unknown_reference",
                    "Source mapping '{id}' points at a table or field that doesn't exist",
                    id=mapping.id,
                )

    # Lookups used by the registry and, later, the storage and query engines.

    def table_by_id(self, table_id: str) -> Table | None:
        return next((t for t in self.tables if t.id == table_id), None)

    def table_by_key(self, key: str) -> Table | None:
        return next((t for t in self.tables if t.key == key), None)


def _parses(parser, value: str) -> bool:
    try:
        parser(value)
    except ValueError:
        return False
    return True
