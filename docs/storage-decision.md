# Storage decision: JSONB records vs physical tables (ADR-08 / ADR-09)

Phase 2 exit gate ("Benchmark done"), 24 November 2026. Raw numbers:
[benchmarks/storage-benchmark.md](benchmarks/storage-benchmark.md). Re-run any time with
`python manage.py run_storage_benchmark` (about a minute; it uses a throwaway database).

## Recommendation

**Keep JSONB records for the MVP** (ADR-08 → Agreed for the MVP), keep schema-per-workspace
tables (ADR-09) as the fallback behind the storage adapter, and re-run the benchmark in
Phase 5 with real data volumes.

Status: **recommended, awaiting Sola's decision.** The spec's decision register is updated
in this PR to match; it changes if the decision goes the other way.

## What was compared

Both designs ran the same data (10,000 sales, 500 customers, 200 products, plus 100 extra
workspaces of 500 sales each) through the same validation code on PostgreSQL 16:

* **JSONB (built):** one shared `business_records` table, links in `record_relationships`
  with composite `(workspace_id, table_id, record_id)` foreign keys, uniqueness through a
  `unique_values` registry. This is the production store in `apps/storage`.
* **Physical (prototype):** a PostgreSQL schema per workspace, one real table per logical
  table, typed columns, native NOT NULL/CHECK/UNIQUE and foreign keys, DDL compiled from the
  SSD. Benchmark-only, in `apps/storage/benchmark/physical.py`.

## Results in one table

| Question | JSONB | Physical | Who wins |
| --- | --- | --- | --- |
| Correctness through the app (links, cross-workspace, wrong table, unique races, delete policies, concurrent edits, exact totals) | all pass | all pass | tie |
| Database refuses a wrong type or missing required value when the app is bypassed | no | yes | physical |
| Reports on one 10k-sale workspace (monthly totals, who owes me, top products) | 13–24 ms | 3–7 ms | physical, 2–9x |
| Lookups (by phone, a customer's sales, a table page) | under 1 ms | under 1 ms | tie in practice |
| Import 10,000 sales | 3.0 s | 1.1 s | physical, about 3x |
| Single creates, 8 writers at once | about 310/s | about 1,100/s | physical (partly Django ORM vs raw SQL) |
| Add a field / make a field unique on 10k rows | 16–370 ms | 1–21 ms | physical |
| Provision 100 workspaces | 1.6 s | 3.0 s | JSONB |
| Database objects per workspace | 0 | 18 | JSONB |
| Disk for the same data | about 2–4x more | less | physical |

## Why JSONB anyway, for now

1. **Both designs pass every correctness gate that goes through the app**, which is the only
   write path (spec section 9: "all writes go through authorized backend services").
2. **Physical is faster, but JSONB is fast enough at MVP scale.** The slowest report is
   24 ms for a 10,000-sale workspace with 100 other workspaces present. A Lagos shop in the
   demo target has hundreds to low thousands of sales.
3. **The AI-adaptive schema (ADR-06) changes structure often.** With JSONB a schema change is
   a new registry version and no DDL. With physical tables every approved change becomes DDL
   run per workspace, with locks, failure recovery and N copies of every migration.
4. **Catalog growth.** 18 relations per workspace is fine at 100 workspaces and heavy at
   10,000 (180,000 relations, slow `pg_dump`, per-tenant migrations).
5. **It is built and tested; switching now costs a production DDL compiler, schema
   migrations and a second record path, against the biggest risk in the spec: scope.**

## What JSONB costs us, and the mitigations

* **No database-side type or required-field checks.** The app validates every write, and
  the database already enforces the shape (flat object, `fld_` keys, scalars only), identity,
  links, cardinality and uniqueness. Follow-up option: a validation trigger compiled from each
  published schema version, which closes the gap at some write cost.
* **Reports are 2–9x slower.** Add expression indexes on hot JSONB fields only when query
  plans justify them (spec section 9), and revisit at Phase 5.
* **Stale planner statistics hurt more on one big shared table.** The benchmark found that
  foreign-key checks planned before `business_records` had statistics scanned the table and
  made a 5,000-row import about 3x slower. It also found a redundant `workspace_id` index that
  the planner preferred over the scoped key; that index is now removed. Production relies on
  autovacuum's ANALYZE; run `ANALYZE business_records` after the first large imports.

## What would change the decision

Re-open ADR-09 if, at Phase 5 or later: report latency for real workspaces exceeds the p95
targets set under "Metrics" (spec section 23), a single workspace grows past roughly 100,000
records, or database-side type enforcement becomes a hard requirement. The storage adapter
(`get_record_store`) is the switch point; the API doesn't change.

## Also decided in Phase 2 (open decisions, spec section 23)

* **Relationship representation:** link rows keyed by `(workspace_id, relationship_id,
  from_record_id)`, one link per source record per relationship (many_to_one), a partial
  unique index for one_to_one, composite foreign keys for both ends, RESTRICT on the target
  side in the database, cascade and set-null applied by the store in the same transaction.
* **Unique constraints:** a unique-value registry (`unique_values`) with a unique index;
  claims use `INSERT ... ON CONFLICT DO NOTHING`, so concurrent and offline-synced writes
  can't both win. Text compares ignoring case and extra spaces ("Indomie" = " indomie").
