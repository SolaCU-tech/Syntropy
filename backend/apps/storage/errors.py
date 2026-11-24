"""Errors raised by the record store, each with a stable code the API passes through.

``details`` maps a field ID (or ``"non_field"``) to a list of plain-language messages, which
is the same shape as every other API error (spec section 11).
"""

from typing import Any


class StorageError(Exception):
    code = "storage_error"
    message = "We couldn't save that."

    def __init__(self, message: str | None = None, details: dict[str, list[str]] | None = None):
        self.message = message or self.message
        self.details = details or {}
        super().__init__(self.message)


class NoActiveSchema(StorageError):
    code = "no_active_schema"
    message = "This workspace doesn't have a published structure yet."


class UnknownTable(StorageError):
    code = "unknown_table"
    message = "We couldn't find that table."


class RecordNotFound(StorageError):
    code = "record_not_found"
    message = "We couldn't find that record."


class RecordValidationError(StorageError):
    """One or more values are invalid. Nothing was written."""

    code = "invalid"
    message = "Some fields need attention."


class ImportValidationError(StorageError):
    """Some rows of a bulk import are invalid. Nothing was written.

    ``row_errors`` maps the row's index in the input to that row's field details.
    """

    code = "invalid_rows"
    message = "Some rows need attention. Nothing was imported."

    def __init__(self, row_errors: dict[int, dict[str, list[str]]]):
        self.row_errors = row_errors
        super().__init__(details={str(i): _flatten(d) for i, d in row_errors.items()})


class DuplicateValue(StorageError):
    code = "duplicate_value"
    message = "Another record already has this value."


class InvalidReference(StorageError):
    """A link points at a record that doesn't exist, is in another table or workspace, or
    was deleted while this write was in flight."""

    code = "invalid_reference"
    message = "A linked record doesn't exist."


class VersionConflict(StorageError):
    """The record changed since the client read it (optimistic concurrency, ADR-27)."""

    code = "version_conflict"
    message = "Someone else changed this record. Review the latest version and try again."

    def __init__(self, current: Any):
        self.current = current
        super().__init__()


class RecordExists(StorageError):
    """A create used a record ID that is already taken."""

    code = "record_exists"
    message = "A record with this ID already exists."


class RecordInUse(StorageError):
    """A delete was refused because other records link to this one (delete policy restrict)."""

    code = "record_in_use"
    message = "Other records link to this one, so it can't be deleted."


def _flatten(details: dict[str, list[str]]) -> list[str]:
    return [f"{field}: {msg}" for field, msgs in details.items() for msg in msgs]
