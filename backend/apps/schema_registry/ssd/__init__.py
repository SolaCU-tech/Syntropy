"""Syntropy Schema Definition (SSD): models, validation, IDs and the published JSON Schema."""

import json
import secrets
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import (
    SPEC_VERSION,
    SSD,
    Cardinality,
    DeletePolicy,
    DisplayRole,
    FieldDef,
    LogicalType,
    Relationship,
    SourceMapping,
    Table,
    Transform,
)
from .naming import is_valid_machine_key, make_machine_key

__all__ = [
    "SPEC_VERSION",
    "SSD",
    "Cardinality",
    "DeletePolicy",
    "DisplayRole",
    "FieldDef",
    "LogicalType",
    "Relationship",
    "SSDValidationError",
    "SourceMapping",
    "Table",
    "Transform",
    "JSON_SCHEMA_PATH",
    "assign_missing_ids",
    "is_valid_machine_key",
    "json_schema",
    "make_machine_key",
    "new_id",
    "parse_ssd",
]

# The exported JSON Schema is committed so other tools (the frontend, the AI's structured
# output mode in Phase 4) can use it. A test fails if it drifts from the models.
JSON_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "ssd-v1.schema.json"


class SSDValidationError(Exception):
    """An SSD document failed validation. ``errors`` is a list of plain dicts."""

    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__(f"SSD is invalid ({len(errors)} problem(s)): {errors[0]['message']}")

    @property
    def codes(self) -> list[str]:
        return [e["code"] for e in self.errors]


def parse_ssd(data: dict[str, Any] | str | bytes) -> SSD:
    """Validate raw JSON (or an already-decoded dict) as an SSD, or raise SSDValidationError."""
    try:
        if isinstance(data, str | bytes):
            return SSD.model_validate_json(data)
        return SSD.model_validate(data)
    except ValidationError as exc:
        raise SSDValidationError(
            [
                {
                    "code": err["type"],
                    "message": err["msg"],
                    "location": ".".join(str(part) for part in err["loc"]),
                }
                for err in exc.errors(include_url=False, include_input=False)
            ]
        ) from exc


def json_schema() -> dict[str, Any]:
    return SSD.model_json_schema(mode="validation")


def json_schema_text() -> str:
    return json.dumps(json_schema(), indent=2, sort_keys=True) + "\n"


_ID_PREFIXES = {"table": "tbl", "field": "fld", "relationship": "rel", "mapping": "map"}


def new_id(kind: str) -> str:
    """A fresh immutable ID such as ``fld_3f9a1c2b7d4e``."""
    return f"{_ID_PREFIXES[kind]}_{secrets.token_hex(6)}"


def assign_missing_ids(document: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a raw draft with an ID on every table, field, relationship and mapping.

    The AI proposes drafts without IDs; the registry assigns them (spec section 8). Existing
    IDs are kept, so this is safe to run on a draft that already has some.
    """
    doc = json.loads(json.dumps(document))
    for table in doc.get("tables", []):
        table.setdefault("id", new_id("table"))
        for field in table.get("fields", []):
            field.setdefault("id", new_id("field"))
    for rel in doc.get("relationships", []):
        rel.setdefault("id", new_id("relationship"))
    for mapping in doc.get("source_mappings", []):
        mapping.setdefault("id", new_id("mapping"))
    return doc
