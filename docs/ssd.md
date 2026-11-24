# Syntropy Schema Definition (SSD) v1

The SSD is the canonical, versioned JSON description of one workspace's structure: its
tables, fields, relationships and source mappings (spec section 8). This page explains how
Phase 1 implements it. The spec stays the source of truth for *what*; this is the *how*.

| Piece | Where |
| --- | --- |
| Pydantic models and every validation rule | `backend/apps/schema_registry/ssd/models.py` |
| Machine-key generation (`make_machine_key`) | `backend/apps/schema_registry/ssd/naming.py` |
| Exported JSON Schema (committed) | `backend/schemas/ssd-v1.schema.json` |
| Hand-written retail example | `backend/apps/schema_registry/examples/retail.ssd.json` |
| Registry (drafts, publish, active version) | `backend/apps/schema_registry/registry.py` |
| Workspace resolver and role matrix | `backend/apps/tenancy/resolver.py`, `permissions.py` |

## Document shape

```jsonc
{
  "spec_version": "1.0",
  "workspace_id": "…",        // stamped by the registry
  "version": 3,                // stamped by the registry
  "status": "published",       // draft | published | superseded
  "tables": [{ "id": "tbl_…", "key": "sales", "label": "Sales", "fields": [ … ] }],
  "relationships": [{ "id": "rel_…", "from_table": "tbl_…", "from_field": "fld_…",
                      "to_table": "tbl_…", "cardinality": "many_to_one",
                      "optional": false, "on_delete": "restrict",
                      "description": "Each sale is for one product" }],
  "source_mappings": [{ "id": "map_…", "source_file": "sales.xlsx", "column": "Qty",
                        "table": "tbl_…", "field": "fld_…", "transform": "parse_integer" }]
}
```

- **IDs** are immutable and prefixed (`tbl_`, `fld_`, `rel_`, `map_`). Everything that refers
  to a table or field (relationships, mappings and, later, forms, reports and queries) uses
  IDs, never labels.
- **Machine keys** are safe snake_case, at most 63 characters, never SQL/Python reserved
  words or system columns (`id`, `created_at`, …), and never change once published (the
  registry refuses a new version that changes a key for an existing ID).
- **Logical types:** `text`, `integer`, `decimal`, `boolean`, `date`, `datetime`, `enum`,
  `reference`. Each type allows only its own constraints (for example `scale` and
  `currency` on decimals, `options` on enums), and defaults must fit the type and range.
- **Money** is a `decimal` with a `currency` and a `scale`; bounds and defaults are decimal
  strings, never JSON numbers (ADR-25).
- **Display roles** tell the UI, reports and insights how to treat a field: `title` (text,
  one per table), `money`, `quantity`, `status` (enum) and `date`. `date` is an addition to
  the spec's examples, for the date that places a record in time.
- **Relationships** start from a `reference` field. Every reference field has exactly one
  relationship, `optional` must match the field's `required`, `one_to_one` needs a unique
  field, and `set_null` needs an optional link. Deletes are `restrict` by default.

Errors from rule checks carry stable `ssd_*` codes (for example `ssd_duplicate_id`,
`ssd_invalid_relationship`) plus a plain message and a location, so tests and the Phase 4 QA
pass can match on them.

## Versions

- The registry is the only code that creates or publishes versions. A draft is validated on
  the way in and again when it's published.
- A draft records the published version it was built on. Publishing fails with
  `stale_base_version` if another version has been published since.
- Publishing supersedes the previous version in the same transaction. At most one version
  per workspace is published (a partial unique index), and that one is the active schema.
- Published and superseded versions are immutable in PostgreSQL itself: a trigger refuses
  any change to their content and any delete, allowing only `published → superseded`.

## Commands

```powershell
python manage.py export_ssd_schema           # rewrite backend/schemas/ssd-v1.schema.json
python manage.py export_ssd_schema --check   # fail if it's stale (a test does this too)
python manage.py seed_retail_example <username>   # example workspace with the retail SSD
```
