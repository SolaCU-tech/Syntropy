"""The active schema for storage: the published SchemaVersion and its parsed SSD.

Published versions are immutable (a database trigger guarantees it), so the parsed SSD can be
cached by version ID and checksum for the life of the process.
"""

from dataclasses import dataclass
from functools import cached_property

from apps.schema_registry import registry
from apps.schema_registry.models import SchemaVersion
from apps.schema_registry.ssd import SSD, Relationship, Table
from apps.tenancy.models import Workspace

from .errors import NoActiveSchema, UnknownTable

_MAX_CACHED = 256
_parsed: dict[tuple[object, str], SSD] = {}


@dataclass(frozen=True)
class ActiveSchema:
    version: SchemaVersion
    ssd: SSD

    def table(self, table_id: str) -> Table:
        table = self.ssd.table_by_id(table_id)
        if table is None:
            raise UnknownTable()
        return table

    @cached_property
    def relationship_by_field(self) -> dict[str, Relationship]:
        """The relationship each reference field belongs to, keyed by field ID."""
        return {r.from_field: r for r in self.ssd.relationships}

    @cached_property
    def relationships_by_id(self) -> dict[str, Relationship]:
        return {r.id: r for r in self.ssd.relationships}

    def incoming(self, table_id: str) -> list[Relationship]:
        """Relationships whose links point at records of ``table_id``."""
        return [r for r in self.ssd.relationships if r.to_table == table_id]


def active_schema(workspace: Workspace) -> ActiveSchema:
    version = registry.get_active_version(workspace)
    if version is None:
        raise NoActiveSchema()
    key = (version.pk, version.checksum)
    ssd = _parsed.get(key)
    if ssd is None:
        if len(_parsed) >= _MAX_CACHED:
            _parsed.clear()
        ssd = _parsed[key] = registry.to_ssd(version)
    return ActiveSchema(version=version, ssd=ssd)
