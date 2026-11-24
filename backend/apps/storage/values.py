"""Validate and canonicalize record values against an SSD table (spec section 9).

Pure Python with no database access, so the JSONB store and the physical-table benchmark
prototype validate identically. Values are keyed by SSD field ID, never by label or machine
key. Each logical type has one canonical stored form:

    text      str (as typed; a required text can't be blank)
    integer   int within +/-(2^53 - 1), so it survives JSON and JavaScript unchanged
    decimal   str with exactly the field's scale, e.g. "1500.00" (ADR-25: never a float)
    boolean   bool
    date      "YYYY-MM-DD"
    datetime  "YYYY-MM-DDTHH:MM:SS[.ffffff]Z", always UTC
    enum      the option key
    reference a record UUID string; stored as a link row, never in the JSONB values

Nothing is rounded or coerced silently: a decimal with too many places is rejected, not
rounded, because wrong totals cost owners real money.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from apps.schema_registry.ssd import FieldDef, LogicalType, Table

MAX_SAFE_INTEGER = 2**53 - 1
DEFAULT_MAX_TEXT_LENGTH = 10_000
DEFAULT_DECIMAL_PRECISION = 28

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INT_RE = re.compile(r"^-?\d{1,16}$")
_DECIMAL_RE = re.compile(r"^-?\d{1,28}(\.\d{1,10})?$")
# Longest canonical value stored as-is in the unique-value registry; longer ones are hashed
# so the B-tree index entry stays small.
MAX_PLAIN_UNIQUE_KEY = 200

REQUIRED = "This field is required."


@dataclass
class CleanedValues:
    """The result of validating one record's input against its table."""

    # Scalar values to store in JSONB, keyed by field ID. ``None`` means "clear this field".
    scalars: dict[str, Any] = field(default_factory=dict)
    # Reference fields: field ID -> target record UUID, or None to remove the link.
    links: dict[str, UUID | None] = field(default_factory=dict)
    errors: dict[str, list[str]] = field(default_factory=dict)

    def add_error(self, field_id: str, message: str) -> None:
        self.errors.setdefault(field_id, []).append(message)


class _Invalid(Exception):
    pass


def clean_values(table: Table, incoming: Any, *, creating: bool) -> CleanedValues:
    """Validate ``incoming`` for a create or a partial update.

    For a create, missing fields take their default and required fields must be present.
    For an update, only the fields in ``incoming`` change, and a required field can't be
    cleared. The caller decides what to do with ``errors``.
    """
    result = CleanedValues()
    if not isinstance(incoming, dict):
        result.add_error("non_field", "Values must be an object keyed by field ID.")
        return result

    fields = {f.id: f for f in table.fields}
    for key in incoming:
        if key not in fields:
            result.add_error(str(key)[:60], "This field doesn't exist in this table.")

    for f in table.fields:
        present = f.id in incoming
        if not present and not creating:
            continue
        raw = incoming[f.id] if present else f.default
        blank = raw is None or (
            f.type == LogicalType.TEXT and isinstance(raw, str) and not raw.strip()
        )
        if blank and f.required:
            result.add_error(f.id, REQUIRED)
            continue
        try:
            value = None if raw is None else canonicalize(f, raw)
        except _Invalid as exc:
            result.add_error(f.id, str(exc))
            continue
        if f.type == LogicalType.REFERENCE:
            result.links[f.id] = value
        else:
            result.scalars[f.id] = value
    return result


def canonicalize(f: FieldDef, raw: Any) -> Any:
    """Return the canonical stored form of ``raw`` for field ``f`` or raise _Invalid."""
    t = f.type
    if t == LogicalType.TEXT:
        return _text(f, raw)
    if t == LogicalType.INTEGER:
        return _integer(f, raw)
    if t == LogicalType.DECIMAL:
        return _decimal(f, raw)
    if t == LogicalType.BOOLEAN:
        if not isinstance(raw, bool):
            raise _Invalid("Must be true or false.")
        return raw
    if t == LogicalType.DATE:
        return _date(raw)
    if t == LogicalType.DATETIME:
        return _datetime(raw)
    if t == LogicalType.ENUM:
        keys = [o.key for o in f.options or []]
        if not isinstance(raw, str) or raw not in keys:
            raise _Invalid(f"Must be one of: {', '.join(keys)}.")
        return raw
    if t == LogicalType.REFERENCE:
        if not isinstance(raw, str):
            raise _Invalid("Must be the ID of a linked record.")
        try:
            return UUID(raw)
        except ValueError:
            raise _Invalid("Must be the ID of a linked record.") from None
    raise _Invalid(f"Unsupported type '{t}'.")  # pragma: no cover


def _text(f: FieldDef, raw: Any) -> str:
    if not isinstance(raw, str):
        raise _Invalid("Must be text.")
    if "\x00" in raw:
        raise _Invalid("Contains a character that can't be stored.")
    limit = f.max_length or DEFAULT_MAX_TEXT_LENGTH
    if len(raw) > limit:
        raise _Invalid(f"Must be at most {limit} characters.")
    return raw


def _in_range(f: FieldDef, d: Decimal) -> None:
    if f.min_value is not None and d < Decimal(f.min_value):
        raise _Invalid(f"Must be at least {f.min_value}.")
    if f.max_value is not None and d > Decimal(f.max_value):
        raise _Invalid(f"Must be at most {f.max_value}.")


def _integer(f: FieldDef, raw: Any) -> int:
    if isinstance(raw, bool):
        raise _Invalid("Must be a whole number.")
    if isinstance(raw, str) and _INT_RE.match(raw.strip()):
        raw = int(raw.strip())
    if not isinstance(raw, int):
        raise _Invalid("Must be a whole number.")
    if abs(raw) > MAX_SAFE_INTEGER:
        raise _Invalid("Is too large.")
    _in_range(f, Decimal(raw))
    return raw


def _decimal(f: FieldDef, raw: Any) -> str:
    # Floats are refused outright: 0.1 + 0.2 is not 0.3 in binary (ADR-25).
    if isinstance(raw, bool | float):
        raise _Invalid('Must be a number written as text, such as "1500.00".')
    if isinstance(raw, int):
        raw = str(raw)
    if not isinstance(raw, str) or not _DECIMAL_RE.match(raw.strip()):
        raise _Invalid('Must be a number such as "1500.00".')
    try:
        d = Decimal(raw.strip())
    except InvalidOperation:  # pragma: no cover - the regex already guards this
        raise _Invalid("Must be a number.") from None
    scale = f.scale if f.scale is not None else 0
    exponent = d.as_tuple().exponent
    places = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    if places > scale:
        raise _Invalid(f"Can have at most {scale} decimal places.")
    q = d.quantize(Decimal(1).scaleb(-scale))
    precision = f.precision or DEFAULT_DECIMAL_PRECISION
    if len(q.as_tuple().digits) > precision:
        raise _Invalid(f"Has more than {precision} digits.")
    _in_range(f, q)
    if q.is_zero():
        q = abs(q)  # never store "-0.00"
    return format(q, "f")


def _date(raw: Any) -> str:
    if not isinstance(raw, str) or not _DATE_RE.match(raw):
        raise _Invalid("Must be a date such as 2026-11-24.")
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        raise _Invalid("Must be a real date.") from None


def _datetime(raw: Any) -> str:
    if not isinstance(raw, str):
        raise _Invalid("Must be a date and time.")
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        raise _Invalid("Must be a date and time such as 2026-11-24T09:30:00Z.") from None
    if value.tzinfo is None:
        raise _Invalid("Must include a time zone, such as Z or +01:00.")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def unique_key(f: FieldDef, value: Any) -> str:
    """The key a value occupies in the unique-value registry.

    Text compares case-insensitively and ignoring surrounding spaces, so "Indomie" and
    " indomie" count as the same product. Other types compare by their canonical form.
    """
    if f.type == LogicalType.TEXT:
        key = " ".join(str(value).split()).casefold()
    elif isinstance(value, bool):
        key = "true" if value else "false"
    else:
        key = str(value)
    if len(key) > MAX_PLAIN_UNIQUE_KEY:
        key = "sha256:" + hashlib.sha256(key.encode()).hexdigest()
    return key


def unique_fields(table: Table) -> list[FieldDef]:
    """Scalar fields with a uniqueness rule. Unique references are one_to_one links, which
    the link table enforces itself."""
    return [f for f in table.fields if f.unique and f.type != LogicalType.REFERENCE]


def reference_fields(table: Table) -> list[FieldDef]:
    return [f for f in table.fields if f.type == LogicalType.REFERENCE]
