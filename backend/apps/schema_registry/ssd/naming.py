"""Machine keys: safe, stable identifiers generated from display labels.

Display labels can be anything the owner types ("Customer's Phone No."); machine keys are
snake_case identifiers that are safe in SQL, Python and URLs, deduplicated, never reserved
words, and never change once created (spec section 8, naming rule).
"""

import keyword
import re
import unicodedata

MAX_KEY_LENGTH = 63  # PostgreSQL's identifier limit, so a key can become a column name.

MACHINE_KEY_PATTERN = r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$"
_MACHINE_KEY_RE = re.compile(MACHINE_KEY_PATTERN)

# Columns every record has in storage; a business field may not reuse these names.
SYSTEM_KEYS = frozenset(
    {"id", "workspace_id", "table_id", "version", "created_at", "updated_at", "created_by"}
)

# SQL words that are reserved in PostgreSQL or the SQL standard (plus a few that are merely
# confusing as column names). Keys must avoid them so storage can map a key to a real column
# if ADR-09 (physical tables) wins the Phase 2 benchmark.
SQL_RESERVED = frozenset(
    {
        "all",
        "alter",
        "analyse",
        "analyze",
        "and",
        "any",
        "array",
        "as",
        "asc",
        "asymmetric",
        "authorization",
        "between",
        "binary",
        "both",
        "case",
        "cast",
        "check",
        "collate",
        "collation",
        "column",
        "concurrently",
        "constraint",
        "create",
        "cross",
        "current_catalog",
        "current_date",
        "current_role",
        "current_schema",
        "current_time",
        "current_timestamp",
        "current_user",
        "database",
        "default",
        "deferrable",
        "delete",
        "desc",
        "distinct",
        "do",
        "drop",
        "else",
        "end",
        "except",
        "false",
        "fetch",
        "for",
        "foreign",
        "freeze",
        "from",
        "full",
        "grant",
        "group",
        "having",
        "ilike",
        "in",
        "index",
        "initially",
        "inner",
        "insert",
        "intersect",
        "into",
        "is",
        "isnull",
        "join",
        "lateral",
        "leading",
        "left",
        "like",
        "limit",
        "localtime",
        "localtimestamp",
        "natural",
        "not",
        "notnull",
        "null",
        "offset",
        "on",
        "only",
        "or",
        "order",
        "outer",
        "overlaps",
        "placing",
        "primary",
        "references",
        "returning",
        "revoke",
        "right",
        "schema",
        "select",
        "session_user",
        "similar",
        "some",
        "symmetric",
        "system_user",
        "table",
        "tablesample",
        "then",
        "to",
        "trailing",
        "true",
        "truncate",
        "union",
        "unique",
        "update",
        "user",
        "using",
        "variadic",
        "verbose",
        "view",
        "when",
        "where",
        "window",
        "with",
    }
)

PYTHON_RESERVED = frozenset(keyword.kwlist) | frozenset(k.lower() for k in keyword.kwlist)

RESERVED_KEYS = SYSTEM_KEYS | SQL_RESERVED | PYTHON_RESERVED


def is_valid_machine_key(key: str) -> bool:
    return (
        len(key) <= MAX_KEY_LENGTH
        and _MACHINE_KEY_RE.fullmatch(key) is not None
        and key not in RESERVED_KEYS
    )


def make_machine_key(label: str, taken: set[str] | frozenset[str] = frozenset()) -> str:
    """Turn a display label into a machine key that is not in ``taken``.

    >>> make_machine_key("Customer's Phone No.")
    'customer_s_phone_no'
    >>> make_machine_key("Name", {"name"})
    'name_2'
    """
    ascii_label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    key = re.sub(r"[^a-z0-9]+", "_", ascii_label.lower()).strip("_")
    if not key:
        key = "field"
    if key[0].isdigit():
        key = f"f_{key}"
    if key in RESERVED_KEYS:
        key = f"{key}_value"
    key = key[:MAX_KEY_LENGTH].rstrip("_")

    candidate, n = key, 2
    while candidate in taken:
        suffix = f"_{n}"
        candidate = key[: MAX_KEY_LENGTH - len(suffix)].rstrip("_") + suffix
        n += 1
    return candidate
