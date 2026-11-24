"""The Workspace Registry (spec section 6 and 8).

Maps each workspace to its active schema version and storage configuration, and is the only
code that creates or publishes schema versions. Every SSD is validated with Pydantic on the
way in and again at publication.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.tenancy.models import Workspace

from .models import SchemaVersion
from .ssd import SSD, SSDValidationError, parse_ssd

# Stored as columns on SchemaVersion rather than inside ``content``.
ENVELOPE_KEYS = ("spec_version", "workspace_id", "version", "status")


class RegistryError(Exception):
    code = "registry_error"


class NotADraft(RegistryError):
    code = "not_a_draft"


class StaleBaseVersion(RegistryError):
    """The draft was built on a version that is no longer the published one."""

    code = "stale_base_version"


class MachineKeyChanged(RegistryError):
    """A table or field kept its ID but changed its machine key, which must never happen."""

    code = "machine_key_changed"


class WrongWorkspace(RegistryError):
    code = "wrong_workspace"


@dataclass(frozen=True)
class RegistryEntry:
    workspace: Workspace
    schema_version: SchemaVersion | None
    storage_backend: str


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def checksum(content: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(content).encode()).hexdigest()


def _content_of(ssd: SSD) -> dict[str, Any]:
    return ssd.model_dump(mode="json", exclude=set(ENVELOPE_KEYS))


def validate_document(document: dict[str, Any] | str | bytes) -> SSD:
    """Parse and validate an SSD; raises SSDValidationError with every problem found."""
    return parse_ssd(document)


def create_draft(
    workspace: Workspace,
    document: dict[str, Any] | str | bytes,
    *,
    created_by=None,
    based_on: SchemaVersion | None = None,
) -> SchemaVersion:
    """Validate ``document`` and store it as the workspace's next draft version.

    ``based_on`` defaults to the currently published version, if there is one.
    """
    ssd = validate_document(document)
    if ssd.workspace_id is not None and ssd.workspace_id != workspace.id:
        raise WrongWorkspace("The document belongs to another workspace.")
    content = _content_of(ssd)
    with transaction.atomic():
        # Lock the workspace row so concurrent drafts get distinct numbers.
        Workspace.objects.select_for_update().get(pk=workspace.pk)
        if based_on is None:
            based_on = get_active_version(workspace)
        elif based_on.workspace_id != workspace.id:
            raise WrongWorkspace("The base version belongs to another workspace.")
        last = SchemaVersion.objects.filter(workspace=workspace).aggregate(n=Max("number"))["n"]
        return SchemaVersion.objects.create(
            workspace=workspace,
            number=(last or 0) + 1,
            status=SchemaVersion.Status.DRAFT,
            spec_version=ssd.spec_version,
            content=content,
            checksum=checksum(content),
            based_on=based_on,
            created_by=created_by,
        )


def publish(version: SchemaVersion, *, published_by=None) -> SchemaVersion:
    """Publish a draft atomically and supersede the previously published version."""
    with transaction.atomic():
        Workspace.objects.select_for_update().get(pk=version.workspace_id)
        version = SchemaVersion.objects.get(pk=version.pk)
        if version.status != SchemaVersion.Status.DRAFT:
            raise NotADraft(f"Version {version.number} is {version.status}, not a draft.")

        current = (
            SchemaVersion.objects.filter(
                workspace_id=version.workspace_id, status=SchemaVersion.Status.PUBLISHED
            )
            .exclude(pk=version.pk)
            .first()
        )
        if version.based_on_id != (current.pk if current else None):
            raise StaleBaseVersion(
                "This draft was built on an older version of the schema. "
                "Rebuild it on the current version and try again."
            )

        if checksum(version.content) != version.checksum:
            raise RegistryError("Draft content doesn't match its checksum.")
        ssd = to_ssd(version)
        if current is not None:
            _check_machine_keys_stable(to_ssd(current), ssd)
            current.status = SchemaVersion.Status.SUPERSEDED
            current.save(update_fields=["status"])

        version.status = SchemaVersion.Status.PUBLISHED
        version.published_at = timezone.now()
        version.published_by = published_by
        version.save(update_fields=["status", "published_at", "published_by"])
        return version


def _check_machine_keys_stable(old: SSD, new: SSD) -> None:
    old_keys: dict[str, str] = {}
    for table in old.tables:
        old_keys[table.id] = table.key
        old_keys.update({f.id: f.key for f in table.fields})
    for table in new.tables:
        for item_id, key in [(table.id, table.key), *((f.id, f.key) for f in table.fields)]:
            if item_id in old_keys and old_keys[item_id] != key:
                raise MachineKeyChanged(
                    f"'{item_id}' changed its machine key from '{old_keys[item_id]}' to '{key}'."
                )


def get_active_version(workspace: Workspace) -> SchemaVersion | None:
    return SchemaVersion.objects.filter(
        workspace=workspace, status=SchemaVersion.Status.PUBLISHED
    ).first()


def to_document(version: SchemaVersion) -> dict[str, Any]:
    """The full SSD document for a version: its content plus the envelope from the row."""
    return {
        "spec_version": version.spec_version,
        "workspace_id": str(version.workspace_id),
        "version": version.number,
        "status": version.status,
        **version.content,
    }


def to_ssd(version: SchemaVersion) -> SSD:
    return parse_ssd(to_document(version))


def get_registry_entry(workspace: Workspace) -> RegistryEntry:
    return RegistryEntry(
        workspace=workspace,
        schema_version=get_active_version(workspace),
        storage_backend=workspace.storage_backend,
    )


__all__ = [
    "MachineKeyChanged",
    "NotADraft",
    "RegistryEntry",
    "RegistryError",
    "SSDValidationError",
    "StaleBaseVersion",
    "WrongWorkspace",
    "create_draft",
    "get_active_version",
    "get_registry_entry",
    "publish",
    "to_document",
    "to_ssd",
    "validate_document",
]
