"""Filters, sorting and search for browsing a table (spec sections 10 and 18).

The table view's filter chips produce a small filter tree, the same shape the Phase 5 query
AST uses for its ``where`` clause, so filters built here carry over unchanged:

    {"all": [{"field": "fld_sale_total_amount", "op": "gte", "value": "1000"},
             {"field": "fld_sale_payment_status", "op": "in", "value": ["unpaid", "part_paid"]}]}

Every filter names an SSD field ID and an operator allowed for that field's type. Values are
canonicalized with the same code that validates writes, then compared with type-aware SQL:
numbers as numeric, dates as dates, text ignoring case. Nothing from the request is ever put
into SQL text; field IDs are checked against the schema and values are bound parameters.
"""

import json
from typing import Any

from django.db.models import (
    BooleanField,
    DateField,
    DateTimeField,
    DecimalField,
    Exists,
    F,
    Func,
    OuterRef,
    Q,
    QuerySet,
    TextField,
    Value,
)
from django.db.models.fields.json import KT
from django.db.models.functions import Lower

from apps.schema_registry.ssd import FieldDef, LogicalType, Table

from .models import RecordRelationship
from .schema import ActiveSchema
from .values import _Invalid, canonicalize

MAX_FILTERS = 20
MAX_IN_VALUES = 100
MAX_SEARCH_LENGTH = 200

EMPTINESS = {"is_empty", "not_empty"}
COMPARISON = {"eq", "neq", "gt", "gte", "lt", "lte"}
OPERATORS: dict[LogicalType, set[str]] = {
    LogicalType.TEXT: {"eq", "neq", "contains", "starts_with"} | EMPTINESS,
    LogicalType.INTEGER: COMPARISON | EMPTINESS,
    LogicalType.DECIMAL: COMPARISON | EMPTINESS,
    LogicalType.DATE: COMPARISON | EMPTINESS,
    LogicalType.DATETIME: {"gt", "gte", "lt", "lte"} | EMPTINESS,
    LogicalType.BOOLEAN: {"eq"} | EMPTINESS,
    LogicalType.ENUM: {"eq", "neq", "in"} | EMPTINESS,
    LogicalType.REFERENCE: {"eq"} | EMPTINESS,
}
# Fields every record has, besides its SSD fields.
SYSTEM_SORTS = {"created_at", "updated_at"}


class FilterError(Exception):
    def __init__(self, details: dict[str, list[str]]):
        self.details = details
        super().__init__(str(details))


def parse_filter_param(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        tree = json.loads(raw)
    except ValueError:
        raise FilterError({"filter": ["Must be JSON."]}) from None
    if not isinstance(tree, dict) or set(tree) != {"all"} or not isinstance(tree["all"], list):
        raise FilterError({"filter": ['Must be {"all": [...]}.']})
    if len(tree["all"]) > MAX_FILTERS:
        raise FilterError({"filter": [f"At most {MAX_FILTERS} filters."]})
    return tree["all"]


def _typed(field: FieldDef, value_sql) -> Any:
    """The JSONB text value cast to a comparable SQL type."""
    t = field.type
    if t in (LogicalType.INTEGER, LogicalType.DECIMAL):
        return Func(value_sql, template="(%(expressions)s)::numeric", output_field=DecimalField())
    if t == LogicalType.DATE:
        return Func(value_sql, template="(%(expressions)s)::date", output_field=DateField())
    if t == LogicalType.DATETIME:
        return Func(
            value_sql, template="(%(expressions)s)::timestamptz", output_field=DateTimeField()
        )
    if t == LogicalType.BOOLEAN:
        return Func(value_sql, template="(%(expressions)s)::boolean", output_field=BooleanField())
    if t == LogicalType.TEXT:
        return Lower(value_sql)
    return value_sql


def _literal(field: FieldDef, value: Any) -> Any:
    t = field.type
    if t in (LogicalType.INTEGER, LogicalType.DECIMAL):
        return Func(
            Value(str(value)), template="(%(expressions)s)::numeric", output_field=DecimalField()
        )
    if t == LogicalType.DATE:
        return Func(Value(value), template="(%(expressions)s)::date", output_field=DateField())
    if t == LogicalType.DATETIME:
        return Func(
            Value(value), template="(%(expressions)s)::timestamptz", output_field=DateTimeField()
        )
    if t == LogicalType.BOOLEAN:
        return Value(value, output_field=BooleanField())
    if t == LogicalType.TEXT:
        return Value(str(value).lower(), output_field=TextField())
    return Value(value, output_field=TextField())


def _clean_value(field: FieldDef, raw: Any) -> Any:
    if field.type == LogicalType.TEXT:
        if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_SEARCH_LENGTH:
            raise _Invalid("Must be some text.")
        return raw.strip()
    # Range checks don't apply to filters ("more than 1,000,000" is a fine question).
    loose = field.model_copy(update={"min_value": None, "max_value": None, "max_length": None})
    return canonicalize(loose, raw)


def _condition(schema: ActiveSchema, table: Table, spec: Any, index: int) -> Q:
    where = f"filter.{index}"
    if not isinstance(spec, dict):
        raise FilterError({where: ["Must be an object with field, op and value."]})
    field = table.field_by_id(spec.get("field", ""))
    if field is None:
        raise FilterError({where: ["This field doesn't exist in this table."]})
    op = spec.get("op")
    if op not in OPERATORS[field.type]:
        allowed = ", ".join(sorted(OPERATORS[field.type]))
        raise FilterError({where: [f"Use one of: {allowed}."]})

    if field.type == LogicalType.REFERENCE:
        rel = schema.relationship_by_field[field.id]
        links = RecordRelationship.objects.filter(
            workspace_id=OuterRef("workspace_id"),
            from_record_id=OuterRef("id"),
            relationship_id=rel.id,
        )
        if op == "eq":
            try:
                target = _clean_value(field, spec.get("value"))
            except _Invalid as exc:
                raise FilterError({where: [str(exc)]}) from None
            links = links.filter(to_record_id=target)
            return Q(Exists(links))
        return Q(Exists(links)) if op == "not_empty" else ~Q(Exists(links))

    raw_text = KT(f"data__{field.id}")
    present = Q(**{"data__has_key": field.id})
    if op == "is_empty":
        return ~present
    if op == "not_empty":
        return present

    try:
        if op == "in":
            values = spec.get("value")
            if not isinstance(values, list) or not values or len(values) > MAX_IN_VALUES:
                raise _Invalid(f"Must be a list of 1 to {MAX_IN_VALUES} values.")
            cleaned = [_clean_value(field, v) for v in values]
            return Q(**{f"data__{field.id}__in": cleaned})
        value = _clean_value(field, spec.get("value"))
    except _Invalid as exc:
        raise FilterError({where: [str(exc)]}) from None

    lhs = _typed(field, raw_text)
    if op == "contains":
        return present & Q(_Match(lhs, Value(f"%{_escape_like(value.lower())}%")))
    if op == "starts_with":
        return present & Q(_Match(lhs, Value(f"{_escape_like(value.lower())}%")))
    rhs = _literal(field, value)
    sql_op = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
    compared = Q(_Compare(lhs, rhs, op=sql_op))
    # "Not equal" includes records where the field is empty, as owners expect.
    return compared | ~present if op == "neq" else present & compared


class _Compare(Func):
    output_field = BooleanField()

    def __init__(self, lhs, rhs, *, op: str):
        super().__init__(lhs, rhs, template="(%(expressions)s)", arg_joiner=f" {op} ")


class _Match(Func):
    output_field = BooleanField()
    template = "(%(expressions)s)"
    arg_joiner = " LIKE "


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def apply_filters(schema: ActiveSchema, table: Table, qs: QuerySet, filters: list) -> QuerySet:
    for i, spec in enumerate(filters):
        qs = qs.filter(_condition(schema, table, spec, i))
    return qs


def apply_search(table: Table, qs: QuerySet, search: str | None) -> QuerySet:
    """Case-insensitive search over the table's text fields (title first in the UI)."""
    if not search:
        return qs
    search = search.strip()[:MAX_SEARCH_LENGTH]
    if not search:
        return qs
    pattern = Value(f"%{_escape_like(search.lower())}%")
    match = Q()
    for f in table.fields:
        if f.type == LogicalType.TEXT:
            match |= Q(_Match(Lower(KT(f"data__{f.id}")), pattern))
    return qs.filter(match) if match else qs.none()


def apply_ordering(table: Table, qs: QuerySet, ordering: str | None) -> QuerySet:
    if not ordering:
        return qs.order_by("-created_at", "-id")
    descending = ordering.startswith("-")
    name = ordering.lstrip("-")
    if name in SYSTEM_SORTS:
        expr = F(name)
    else:
        field = table.field_by_id(name)
        if field is None or field.type == LogicalType.REFERENCE:
            raise FilterError({"ordering": ["Sort by a field of this table (not a link)."]})
        expr = _typed(field, KT(f"data__{field.id}"))
    key = expr.desc(nulls_last=True) if descending else expr.asc(nulls_last=True)
    return qs.order_by(key, "-created_at", "-id")
