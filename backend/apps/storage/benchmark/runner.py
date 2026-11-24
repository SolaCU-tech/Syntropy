"""The JSONB vs physical-tables benchmark (spec section 9, "Selection gate").

Runs the same data and the same questions through both storage designs and reports:

* correctness checks, pass/fail: invalid references, unique-value races, delete policies,
  concurrent writes, and what the database itself refuses when the app is bypassed;
* a 10,000-row import, joins, monthly aggregation and lookups, single-tenant and again with
  many other workspaces present;
* schema changes on a loaded table;
* 100 simulated workspaces: provisioning time, catalog growth, disk and query latency.

Run it with ``python manage.py run_storage_benchmark`` (it uses a throwaway database).
"""

import os
import platform
import random
import statistics
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, transaction

from apps.schema_registry import registry
from apps.schema_registry.ssd import parse_ssd
from apps.tenancy.services import create_workspace

from .. import errors
from ..store import JsonbRecordStore, get_record_store
from ..testing import (
    CUSTOMERS,
    PAYMENTS,
    PRODUCTS,
    SALES,
    customer_values,
    product_values,
    retail_with_policies,
    sale_days,
    sale_values,
)
from .physical import PhysicalSchemaStore, q

JSONB = "jsonb"
PHYSICAL = "physical"


@dataclass
class Timing:
    name: str
    jsonb: float | None
    physical: float | None
    unit: str = "ms"
    note: str = ""


@dataclass
class Check:
    name: str
    jsonb: bool
    physical: bool
    note: str = ""


@dataclass
class Report:
    params: dict[str, Any]
    environment: dict[str, str] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    sections: dict[str, list[Timing]] = field(default_factory=dict)
    plans: dict[str, str] = field(default_factory=dict)

    def add(self, section: str, timing: Timing) -> None:
        self.sections.setdefault(section, []).append(timing)


def _ms(seconds: float) -> float:
    return round(seconds * 1000, 2)


def _time(fn: Callable[[], Any]) -> tuple[float, Any]:
    start = time.perf_counter()
    result = fn()
    return time.perf_counter() - start, result


def _median_ms(fn: Callable[[], Any], repeats: int) -> float:
    for _ in range(2):
        fn()
    samples = []
    for _ in range(repeats):
        elapsed, _result = _time(fn)
        samples.append(elapsed)
    return _ms(statistics.median(samples))


def _fetch(sql: str, params: list[Any] | None = None) -> list[tuple]:
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        return cur.fetchall()


def _race(n: int, fn: Callable[[int], Any]) -> list[Any]:
    barrier = threading.Barrier(n)
    results: list[Any] = [None] * n

    def run(i: int) -> None:
        try:
            barrier.wait()
            results[i] = fn(i)
        except Exception as exc:  # noqa: BLE001 - recorded and inspected by the caller
            results[i] = exc
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


class Dataset:
    """Deterministic rows for one workspace; references are filled per backend."""

    def __init__(self, customers: int, products: int, sales: int, seed: int):
        rng = random.Random(seed)  # noqa: S311 - reproducible test data, not security
        self.customers = [customer_values(i) for i in range(customers)]
        self.products = [product_values(i) for i in range(products)]
        days = sale_days(sales)
        self.sales = []
        for i in range(sales):
            c = rng.randrange(customers) if rng.random() < 0.8 else None
            p = rng.randrange(products)
            values = sale_values(None, uuid4(), day=days[i], rng=rng)
            values["fld_sale_notes"] = f"Receipt {seed:03d}-{i:06d}"
            self.sales.append((c, p, values))

    def sales_rows(self, customer_ids: list[UUID], product_ids: list[UUID]) -> list[dict]:
        rows = []
        for c, p, values in self.sales:
            row = dict(values)
            row["fld_sale_customer"] = str(customer_ids[c]) if c is not None else None
            row["fld_sale_product"] = str(product_ids[p])
            rows.append(row)
        return rows

    def expected_monthly(self) -> list[tuple[str, int, Decimal]]:
        months: dict[str, list[Decimal]] = {}
        for _c, _p, values in self.sales:
            month = values["fld_sale_date"][:7]
            months.setdefault(month, []).append(Decimal(values["fld_sale_total_amount"]))
        return [(m, len(v), sum(v)) for m, v in sorted(months.items())]


class Benchmark:
    def __init__(
        self,
        *,
        sales: int = 10_000,
        customers: int = 500,
        products: int = 200,
        workspaces: int = 100,
        tenant_sales: int = 500,
        repeats: int = 20,
        threads: int = 8,
        log: Callable[[str], None] = print,
    ):
        self.p = {
            "sales": sales,
            "customers": customers,
            "products": products,
            "workspaces": workspaces,
            "tenant_sales": tenant_sales,
            "repeats": repeats,
            "threads": threads,
        }
        self.log = log
        self.report = Report(params=dict(self.p))
        self.physical_stores: list[PhysicalSchemaStore] = []
        self.ssd_doc = retail_with_policies()
        self.ssd = parse_ssd(self.ssd_doc)

    # Setup helpers

    def _user(self):
        user, _ = get_user_model().objects.get_or_create(username="storage-benchmark")
        return user

    def _jsonb_workspace(self, name: str) -> JsonbRecordStore:
        workspace = create_workspace(self._user(), name)
        registry.publish(registry.create_draft(workspace, self.ssd_doc))
        return get_record_store(workspace)

    def _physical_workspace(self) -> PhysicalSchemaStore:
        store = PhysicalSchemaStore(self.ssd)
        self.physical_stores.append(store)
        store.create()
        return store

    def _load_jsonb(
        self, store: JsonbRecordStore, data: Dataset, *, analyze: bool = False
    ) -> dict[str, float]:
        t_c, customers = _time(lambda: store.import_records(CUSTOMERS, data.customers))
        t_p, products = _time(lambda: store.import_records(PRODUCTS, data.products))
        if analyze:
            _fetch_none("ANALYZE business_records")
            _fetch_none("ANALYZE record_relationships")
        rows = data.sales_rows(customers, products)
        t_s, _ = _time(lambda: store.import_records(SALES, rows))
        self._ids = (customers, products)
        return {"customers": t_c, "products": t_p, "sales": t_s}

    def _load_physical(
        self, store: PhysicalSchemaStore, data: Dataset, *, analyze: bool = False
    ) -> dict[str, float]:
        t_c, customers = _time(lambda: store.import_records(CUSTOMERS, data.customers))
        t_p, products = _time(lambda: store.import_records(PRODUCTS, data.products))
        if analyze:
            for table in (CUSTOMERS, PRODUCTS, SALES):
                _fetch_none(f"ANALYZE {store.t(table)}")
        rows = data.sales_rows(customers, products)
        t_s, _ = _time(lambda: store.import_records(SALES, rows))
        self._ids = (customers, products)
        return {"customers": t_c, "products": t_p, "sales": t_s}

    # The run

    def run(self) -> Report:
        try:
            self._environment()
            self._main_load()
            self._queries("Queries, one workspace")
            self._correctness()
            self._schema_changes()
            self._many_workspaces()
            self._queries(f"Queries, with {self.p['workspaces']} other workspaces present")
            self._plans()
        finally:
            for store in self.physical_stores:
                store.drop()
        return self.report

    def _environment(self) -> None:
        version = _fetch("SHOW server_version")[0][0]
        self.report.environment = {
            "Date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "PostgreSQL": version,
            "Python": platform.python_version(),
            "Machine": f"{platform.system()} {platform.machine()}, {os.cpu_count()} CPUs",
        }

    def _main_load(self) -> None:
        p = self.p
        self.log(f"Loading {p['sales']} sales into each backend...")
        self.data = Dataset(p["customers"], p["products"], p["sales"], seed=0)

        self.jsonb = self._jsonb_workspace("Benchmark main")
        jt = self._load_jsonb(self.jsonb, self.data, analyze=True)
        self.j_customers, self.j_products = self._ids

        t_ddl, self.phys = _time(self._physical_workspace)
        pt = self._load_physical(self.phys, self.data, analyze=True)
        self.p_customers, self.p_products = self._ids
        _fetch_none("ANALYZE")

        section = (
            f"Import ({p['sales']:,} sales, {p['customers']} customers, {p['products']} products)"
        )
        self.report.add(
            section,
            Timing(
                "Create the workspace's storage", None, _ms(t_ddl), note="JSONB: nothing to create"
            ),
        )
        for key in ("customers", "products", "sales"):
            self.report.add(section, Timing(f"Import {key}", _ms(jt[key]), _ms(pt[key])))
        rate_j = p["sales"] / jt["sales"]
        rate_p = p["sales"] / pt["sales"]
        self.report.add(
            section, Timing("Sales import rate", round(rate_j), round(rate_p), unit="rows/s")
        )
        self.report.add(
            section, Timing("Disk used", self._jsonb_bytes(), self._physical_bytes(), unit="MB")
        )

    def _jsonb_bytes(self) -> float:
        rows = _fetch(
            "SELECT sum(pg_total_relation_size(c)) FROM unnest(ARRAY['business_records',"
            "'record_relationships','unique_values']::regclass[]) AS c"
        )
        return round(rows[0][0] / 1_048_576, 2)

    def _physical_bytes(self, stores: list[PhysicalSchemaStore] | None = None) -> float:
        names = [s.schema for s in (stores or [self.phys])]
        rows = _fetch(
            "SELECT coalesce(sum(pg_total_relation_size(c.oid)), 0) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = ANY(%s) AND c.relkind = 'r'",
            [names],
        )
        return round(rows[0][0] / 1_048_576, 2)

    # Queries

    def _sql(self) -> dict[str, tuple[str, str]]:
        s = self.phys.t
        return {
            "monthly": (
                """SELECT to_char(date_trunc('month', (data->>'fld_sale_date')::date), 'YYYY-MM'),
                          count(*), sum((data->>'fld_sale_total_amount')::numeric)
                   FROM business_records WHERE workspace_id = %s AND table_id = 'tbl_sales'
                   GROUP BY 1 ORDER BY 1""",
                f"""SELECT to_char(date_trunc('month', fld_sale_date), 'YYYY-MM'), count(*),
                           sum(fld_sale_total_amount)
                    FROM {s(SALES)} GROUP BY 1 ORDER BY 1""",
            ),
            "owes": (
                """SELECT c.data->>'fld_customer_name',
                          sum((s.data->>'fld_sale_total_amount')::numeric
                              - (s.data->>'fld_sale_amount_paid')::numeric) AS owed
                   FROM business_records s
                   JOIN record_relationships l ON l.workspace_id = s.workspace_id
                        AND l.from_record_id = s.id AND l.relationship_id = 'rel_sale_customer'
                   JOIN business_records c ON c.workspace_id = l.workspace_id
                        AND c.table_id = l.to_table_id AND c.id = l.to_record_id
                   WHERE s.workspace_id = %s AND s.table_id = 'tbl_sales'
                   GROUP BY 1 ORDER BY owed DESC, 1 LIMIT 10""",
                f"""SELECT c.fld_customer_name,
                           sum(s.fld_sale_total_amount - s.fld_sale_amount_paid) AS owed
                    FROM {s(SALES)} s JOIN {s(CUSTOMERS)} c ON c.id = s.fld_sale_customer
                    GROUP BY 1 ORDER BY owed DESC, 1 LIMIT 10""",
            ),
            "top_products": (
                """SELECT p.data->>'fld_product_name', sum((s.data->>'fld_sale_quantity')::int) AS n
                   FROM business_records s
                   JOIN record_relationships l ON l.workspace_id = s.workspace_id
                        AND l.from_record_id = s.id AND l.relationship_id = 'rel_sale_product'
                   JOIN business_records p ON p.workspace_id = l.workspace_id
                        AND p.table_id = l.to_table_id AND p.id = l.to_record_id
                   WHERE s.workspace_id = %s AND s.table_id = 'tbl_sales'
                     AND (s.data->>'fld_sale_date')::date >= '2025-06-01'
                   GROUP BY 1 ORDER BY n DESC, 1 LIMIT 10""",
                f"""SELECT p.fld_product_name, sum(s.fld_sale_quantity) AS n
                    FROM {s(SALES)} s JOIN {s(PRODUCTS)} p ON p.id = s.fld_sale_product
                    WHERE s.fld_sale_date >= '2025-06-01'
                    GROUP BY 1 ORDER BY n DESC, 1 LIMIT 10""",
            ),
            "customer_sales": (
                """SELECT s.id FROM record_relationships l
                   JOIN business_records s ON s.workspace_id = l.workspace_id
                        AND s.table_id = l.from_table_id AND s.id = l.from_record_id
                   WHERE l.workspace_id = %s AND l.to_record_id = %s
                     AND l.relationship_id = 'rel_sale_customer'
                   ORDER BY s.created_at DESC LIMIT 50""",
                f"""SELECT id FROM {s(SALES)} WHERE fld_sale_customer = %s
                    ORDER BY created_at DESC LIMIT 50""",
            ),
            "by_phone": (
                """SELECT r.id FROM unique_values u JOIN business_records r
                        ON r.workspace_id = u.workspace_id AND r.table_id = u.table_id
                        AND r.id = u.record_id
                   WHERE u.workspace_id = %s AND u.table_id = 'tbl_customers'
                     AND u.field_id = 'fld_customer_phone' AND u.value_key = %s""",
                f"""SELECT id FROM {s(CUSTOMERS)}
                    WHERE lower(regexp_replace(btrim(fld_customer_phone), '\\s+', ' ', 'g'))
                          = %s""",
            ),
            "page": (
                """SELECT id, data FROM business_records
                   WHERE workspace_id = %s AND table_id = 'tbl_sales'
                   ORDER BY created_at DESC LIMIT 50 OFFSET 500""",
                f"""SELECT * FROM {s(SALES)} ORDER BY created_at DESC
                    LIMIT 50 OFFSET 500""",
            ),
        }

    def _queries(self, section: str) -> None:
        self.log(f"Timing queries ({section})...")
        ws = self.jsonb.workspace.pk
        sql = self._sql()
        phone = self.data.customers[7]["fld_customer_phone"]
        params = {
            "monthly": ([ws], []),
            "owes": ([ws], []),
            "top_products": ([ws], []),
            "customer_sales": ([ws, self.j_customers[3]], [self.p_customers[3]]),
            "by_phone": ([ws, phone], [phone]),
            "page": ([ws], []),
        }
        labels = {
            "monthly": "Monthly sales totals (aggregation)",
            "owes": "Who owes me the most (join + aggregation)",
            "top_products": "Top products since June (join + filter)",
            "customer_sales": "One customer's latest sales (incoming links)",
            "by_phone": "Find a customer by phone (unique lookup)",
            "page": "Page 11 of the sales table",
        }
        repeats = self.p["repeats"]
        for key, (j_sql, p_sql) in sql.items():
            jp, pp = params[key]
            j = _median_ms(lambda j_sql=j_sql, jp=jp: _fetch(j_sql, jp), repeats)
            p = _median_ms(lambda p_sql=p_sql, pp=pp: _fetch(p_sql, pp), repeats)
            self.report.add(section, Timing(labels[key], j, p, note="median"))

        if section.startswith("Queries, one"):
            monthly_j = _fetch(sql["monthly"][0], [ws])
            monthly_p = _fetch(sql["monthly"][1])
            expected = self.data.expected_monthly()
            owes_j = [row[1] for row in _fetch(sql["owes"][0], [ws])]
            owes_p = [row[1] for row in _fetch(sql["owes"][1])]
            self.report.checks.append(
                Check(
                    "Monthly totals match the source data exactly",
                    [tuple(r) for r in monthly_j] == expected,
                    [tuple(r) for r in monthly_p] == expected,
                    "exact decimal sums compared with Python's",
                )
            )
            self.report.checks.append(
                Check(
                    'Both designs give the same "who owes me" answer',
                    owes_j == owes_p,
                    owes_j == owes_p,
                )
            )

    # Correctness

    def _correctness(self) -> None:
        self.log("Correctness checks...")
        c = self.report.checks
        c.append(
            Check(
                "Link to a record that doesn't exist is refused",
                *self._both(self._bad_link_missing),
            )
        )
        c.append(
            Check(
                "Link to a record in the wrong table is refused",
                *self._both(self._bad_link_wrong_table),
            )
        )
        c.append(
            Check(
                "Link to another workspace's record is refused",
                *self._both(self._bad_link_other_workspace),
            )
        )
        c.append(
            Check(
                f"Unique-value race ({self.p['threads']} writers x 10 rounds): one winner",
                *self._both(self._unique_race),
            )
        )
        c.append(
            Check(
                "Delete restrict: a sold product can't be deleted",
                *self._both(self._delete_restrict),
            )
        )
        c.append(
            Check(
                "Delete set_null: deleting a customer unlinks their sales",
                *self._both(self._delete_set_null),
            )
        )
        c.append(
            Check(
                "Delete cascade: deleting a sale removes its payments",
                *self._both(self._delete_cascade),
            )
        )
        c.append(
            Check(
                f"Concurrent stock edits ({self.p['threads']} writers): no lost updates",
                *self._both(self._no_lost_updates),
            )
        )
        c.append(
            Check(
                "Database refuses a wrong type when the app is bypassed",
                *self._both(self._db_rejects_wrong_type),
                "JSONB: a trigger checks values against the published schema",
            )
        )
        c.append(
            Check(
                "Database refuses a missing required value when the app is bypassed",
                *self._both(self._db_rejects_missing_required),
            )
        )
        self._concurrent_inserts()

    def _both(self, fn: Callable[[str], bool]) -> tuple[bool, bool]:
        out = []
        for backend in (JSONB, PHYSICAL):
            try:
                out.append(bool(fn(backend)))
            except Exception as exc:  # noqa: BLE001 - an unexpected error is a failed check
                self.log(f"  {fn.__name__} [{backend}] raised {exc!r}")
                out.append(False)
        return out[0], out[1]

    def _sale(self, customer, product) -> dict[str, Any]:
        return {
            "fld_sale_date": "2026-11-24",
            "fld_sale_customer": str(customer) if customer else None,
            "fld_sale_product": str(product),
            "fld_sale_quantity": 1,
            "fld_sale_unit_price": "10.00",
            "fld_sale_total_amount": "10.00",
        }

    def _create(self, backend: str, table: str, values: dict, store=None):
        if backend == JSONB:
            return (store or self.jsonb).create(table, values).id
        return (store or self.phys).create_record(table, values)

    def _refused(self, fn: Callable[[], Any], *expected: type[Exception]) -> bool:
        try:
            fn()
        except expected:
            return True
        return False

    def _products(self, backend):
        return self.j_products if backend == JSONB else self.p_products

    def _customers(self, backend):
        return self.j_customers if backend == JSONB else self.p_customers

    def _bad_link_missing(self, backend: str) -> bool:
        values = self._sale(uuid4(), self._products(backend)[0])
        return self._refused(lambda: self._create(backend, SALES, values), errors.InvalidReference)

    def _bad_link_wrong_table(self, backend: str) -> bool:
        product = self._products(backend)[0]
        values = self._sale(product, product)  # a product posing as the customer
        return self._refused(lambda: self._create(backend, SALES, values), errors.InvalidReference)

    def _bad_link_other_workspace(self, backend: str) -> bool:
        if not hasattr(self, "_other"):
            self._other = {
                JSONB: self._jsonb_workspace("Benchmark other"),
                PHYSICAL: self._physical_workspace(),
            }
        other = self._other[backend]
        foreign = self._create(backend, CUSTOMERS, customer_values(99_999), store=other)
        values = self._sale(foreign, self._products(backend)[0])
        return self._refused(lambda: self._create(backend, SALES, values), errors.InvalidReference)

    def _store_for_thread(self, backend: str):
        if backend == JSONB:
            return get_record_store(self.jsonb.workspace)
        return PhysicalSchemaStore(self.ssd, self.phys.schema)

    def _unique_race(self, backend: str) -> bool:
        ok = True
        for round_ in range(10):
            phone = f"0700{round_:07d}"

            def attempt(i: int, phone=phone, round_=round_):
                values = customer_values(200_000 + round_ * 100 + i)
                values["fld_customer_phone"] = phone
                return self._create(
                    backend, CUSTOMERS, values, store=self._store_for_thread(backend)
                )

            results = _race(self.p["threads"], attempt)
            winners = [r for r in results if not isinstance(r, Exception)]
            losers = [r for r in results if isinstance(r, errors.DuplicateValue)]
            ok = ok and len(winners) == 1 and len(losers) == len(results) - 1
        return ok

    def _delete_restrict(self, backend: str) -> bool:
        product = self._create(backend, PRODUCTS, product_values(300_000))
        self._create(backend, SALES, self._sale(None, product))
        if backend == JSONB:
            refused = self._refused(
                lambda: self.jsonb.delete(PRODUCTS, product), errors.RecordInUse
            )
            return refused and self.jsonb.get(PRODUCTS, product) is not None
        refused = self._refused(lambda: self.phys.delete(PRODUCTS, product), errors.RecordInUse)
        return refused and self.phys.get(PRODUCTS, product) is not None

    def _delete_set_null(self, backend: str) -> bool:
        customer = self._create(backend, CUSTOMERS, customer_values(300_001))
        sale = self._create(backend, SALES, self._sale(customer, self._products(backend)[0]))
        if backend == JSONB:
            self.jsonb.delete(CUSTOMERS, customer)
            return self.jsonb.get(SALES, sale).values["fld_sale_customer"] is None
        self.phys.delete(CUSTOMERS, customer)
        return self.phys.get(SALES, sale)["fld_sale_customer"] is None

    def _delete_cascade(self, backend: str) -> bool:
        sale = self._create(backend, SALES, self._sale(None, self._products(backend)[0]))
        payment = {
            "fld_payment_date": "2026-11-24",
            "fld_payment_amount": "5.00",
            "fld_payment_sale": str(sale),
        }
        payments = [self._create(backend, PAYMENTS, payment) for _ in range(3)]
        store = self.jsonb if backend == JSONB else self.phys
        store.delete(SALES, sale)
        return all(
            self._refused(lambda pid=pid: store.get(PAYMENTS, pid), errors.RecordNotFound)
            for pid in payments
        )

    def _no_lost_updates(self, backend: str) -> bool:
        threads = self.p["threads"]
        product = self._create(
            backend, PRODUCTS, product_values(300_002) | {"fld_product_stock_quantity": 1000}
        )

        def take_five(_i: int):
            store = self._store_for_thread(backend)
            for _ in range(200):
                if backend == JSONB:
                    current = store.get(PRODUCTS, product)
                    stock, version = (current.values["fld_product_stock_quantity"], current.version)
                else:
                    row = store.get(PRODUCTS, product)
                    stock, version = row["fld_product_stock_quantity"], row["version"]
                try:
                    store.update(
                        PRODUCTS,
                        product,
                        {"fld_product_stock_quantity": stock - 5},
                        expected_version=version,
                    )
                    return True
                except errors.VersionConflict:
                    continue
            return False

        results = _race(threads, take_five)
        if not all(r is True for r in results):
            return False
        if backend == JSONB:
            final = self.jsonb.get(PRODUCTS, product).values["fld_product_stock_quantity"]
        else:
            final = self.phys.get(PRODUCTS, product)["fld_product_stock_quantity"]
        return final == 1000 - 5 * threads

    def _db_rejects_wrong_type(self, backend: str) -> bool:
        if backend == JSONB:
            sql = (
                'UPDATE business_records SET data = data || \'{"fld_sale_quantity": "lots"}\','
                " version = version + 1 WHERE id = %s"
            )
            target = self.jsonb.queryset(SALES).values_list("id", flat=True).first()
        else:
            sql = f"UPDATE {self.phys.t(SALES)} SET fld_sale_quantity = 'lots' WHERE id = %s"
            target = _fetch(f"SELECT id FROM {self.phys.t(SALES)} LIMIT 1")[0][0]
        return self._raw_refused(sql, [target])

    def _db_rejects_missing_required(self, backend: str) -> bool:
        if backend == JSONB:
            sql = (
                "UPDATE business_records SET data = data - 'fld_sale_date',"
                " version = version + 1 WHERE id = %s"
            )
            target = self.jsonb.queryset(SALES).values_list("id", flat=True).first()
        else:
            sql = f"UPDATE {self.phys.t(SALES)} SET fld_sale_date = NULL WHERE id = %s"
            target = _fetch(f"SELECT id FROM {self.phys.t(SALES)} LIMIT 1")[0][0]
        return self._raw_refused(sql, [target])

    def _raw_refused(self, sql: str, params: list[Any]) -> bool:
        """Run raw SQL in a transaction that is always rolled back; True if it failed."""

        class _Rollback(Exception):
            pass

        try:
            with transaction.atomic():
                _fetch_none(sql, params)
                raise _Rollback
        except _Rollback:
            return False
        except DatabaseError:
            return True

    def _concurrent_inserts(self) -> None:
        threads, per_thread = self.p["threads"], 50
        section = "Concurrent writes"
        timings = {}
        for backend in (JSONB, PHYSICAL):
            products, customers = self._products(backend), self._customers(backend)

            def insert(i: int, backend=backend, products=products, customers=customers):
                store = self._store_for_thread(backend)
                for n in range(per_thread):
                    self._create(
                        backend,
                        SALES,
                        self._sale(
                            customers[(i + n) % len(customers)], products[(i * n) % len(products)]
                        ),
                        store=store,
                    )
                return True

            elapsed, results = _time(lambda insert=insert: _race(threads, insert))
            if not all(r is True for r in results):
                raise RuntimeError(f"concurrent inserts failed: {results!r}")
            timings[backend] = threads * per_thread / elapsed
        self.report.add(
            section,
            Timing(
                f"Single-record creates, {threads} writers at once",
                round(timings[JSONB]),
                round(timings[PHYSICAL]),
                unit="rows/s",
                note="each create validates, checks links and writes in its own transaction",
            ),
        )

    # Schema changes

    def _schema_changes(self) -> None:
        self.log("Schema changes...")
        section = f"Schema changes on a table with {self.p['sales']:,} sales"
        workspace = self.jsonb.workspace

        def publish(mutate):
            doc = registry.to_document(registry.get_active_version(workspace))
            for key in ("workspace_id", "version", "status"):
                doc.pop(key)
            mutate(doc)
            return registry.publish(registry.create_draft(workspace, doc))

        def sales_table(doc):
            return next(t for t in doc["tables"] if t["id"] == SALES)

        # 1. Add an optional field.
        def add_optional(doc):
            sales_table(doc)["fields"].append(
                {
                    "id": "fld_sale_reference",
                    "key": "reference",
                    "label": "Reference",
                    "type": "text",
                }
            )

        t_j, _ = _time(lambda: publish(add_optional))
        t_p, _ = _time(
            lambda: _fetch_none(
                f"ALTER TABLE {self.phys.t(SALES)} ADD COLUMN {q('fld_sale_reference')} text"
            )
        )
        self.report.add(
            section,
            Timing(
                "Add an optional field",
                _ms(t_j),
                _ms(t_p),
                note="JSONB: publish a new version only",
            ),
        )

        # 2. Add a required field with a default, filling every existing row.
        def add_required(doc):
            sales_table(doc)["fields"].append(
                {
                    "id": "fld_sale_channel",
                    "key": "channel",
                    "label": "Channel",
                    "type": "enum",
                    "required": True,
                    "default": "shop",
                    "options": [
                        {"key": "shop", "label": "Shop"},
                        {"key": "online", "label": "Online"},
                    ],
                }
            )

        def jsonb_backfill():
            version = publish(add_required)
            # Records move to the new version as they're filled (the database checks each
            # row against the rules of the version it names).
            _fetch_none(
                'UPDATE business_records SET data = data || \'{"fld_sale_channel": "shop"}\','
                " version = version + 1, schema_version_id = %s"
                " WHERE workspace_id = %s AND table_id = 'tbl_sales'"
                " AND NOT data ? 'fld_sale_channel'",
                [version.pk, workspace.pk],
            )

        t_j, _ = _time(jsonb_backfill)
        t_p, _ = _time(
            lambda: _fetch_none(
                f"ALTER TABLE {self.phys.t(SALES)} ADD COLUMN {q('fld_sale_channel')} text "
                "NOT NULL DEFAULT 'shop' CHECK (fld_sale_channel IN ('shop', 'online'))"
            )
        )
        self.report.add(
            section,
            Timing(
                "Add a required field with a default (backfill)",
                _ms(t_j),
                _ms(t_p),
                note="JSONB rewrites every row; PostgreSQL stores the default in the catalog",
            ),
        )

        # 3. Make an existing field unique, checking the data already there.
        def jsonb_make_unique():
            publish(
                lambda doc: next(
                    f for f in sales_table(doc)["fields"] if f["id"] == "fld_sale_notes"
                ).update(unique=True)
            )
            _fetch_none(
                """INSERT INTO unique_values (workspace_id, table_id, field_id, value_key,
                                              record_id)
                   SELECT workspace_id, table_id, 'fld_sale_notes',
                          lower(regexp_replace(btrim(data->>'fld_sale_notes'), '\\s+', ' ', 'g')),
                          id
                   FROM business_records
                   WHERE workspace_id = %s AND table_id = 'tbl_sales'
                     AND data ? 'fld_sale_notes'""",
                [workspace.pk],
            )

        t_j, _ = _time(jsonb_make_unique)
        t_p, _ = _time(
            lambda: _fetch_none(
                f"CREATE UNIQUE INDEX ON {self.phys.t(SALES)} "
                "(lower(regexp_replace(btrim(fld_sale_notes), '\\s+', ' ', 'g')))"
            )
        )
        self.report.add(
            section,
            Timing(
                "Make an existing field unique",
                _ms(t_j),
                _ms(t_p),
                note="both fail on existing duplicates",
            ),
        )
        self.jsonb._schema = None  # pick up the new active version

    # Many workspaces

    def _many_workspaces(self) -> None:
        n, per = self.p["workspaces"], self.p["tenant_sales"]
        self.log(f"Creating {n} workspaces with {per} sales each in both backends...")
        section = f"{n} workspaces with {per:,} sales each"
        jsonb_stores, phys_stores = [], []
        datasets = [Dataset(30, 15, per, seed=i + 1) for i in range(n)]

        def provision_jsonb():
            for i in range(n):
                jsonb_stores.append(self._jsonb_workspace(f"Tenant {i}"))

        def provision_physical():
            for _ in range(n):
                phys_stores.append(self._physical_workspace())

        t_jp, _ = _time(provision_jsonb)
        t_pp, _ = _time(provision_physical)
        relations_before = _relation_count()
        t_ji, _ = _time(
            lambda: [self._load_jsonb(s, d) for s, d in zip(jsonb_stores, datasets, strict=True)]
        )
        t_pi, _ = _time(
            lambda: [self._load_physical(s, d) for s, d in zip(phys_stores, datasets, strict=True)]
        )
        _fetch_none("ANALYZE")

        self.report.add(
            section,
            Timing(
                "Provision all workspaces",
                _ms(t_jp),
                _ms(t_pp),
                note="JSONB: publish the schema; physical: also run DDL",
            ),
        )
        self.report.add(section, Timing("Import all workspaces' data", _ms(t_ji), _ms(t_pi)))
        phys_relations = _physical_relation_count([s.schema for s in phys_stores])
        self.report.add(
            section,
            Timing(
                "Database objects added",
                0,
                phys_relations,
                unit="relations",
                note=f"{phys_relations // max(n, 1)} per physical workspace (tables and "
                f"indexes); {relations_before} relations in the database before loading",
            ),
        )
        self.report.add(
            section,
            Timing(
                "Disk used by all record storage",
                self._jsonb_bytes(),
                self._physical_bytes([self.phys, *phys_stores]),
                unit="MB",
            ),
        )

        monthly_j, monthly_p = self._sql()["monthly"]
        sample = list(range(0, n, max(1, n // 20)))
        j_times, p_times = [], []
        for i in sample:
            ws = jsonb_stores[i].workspace.pk
            j_times.append(_median_ms(lambda ws=ws: _fetch(monthly_j, [ws]), 5))
            p_sql = monthly_p.replace(self.phys.t(SALES), phys_stores[i].t(SALES))
            p_times.append(_median_ms(lambda p_sql=p_sql: _fetch(p_sql), 5))
        self.report.add(
            section,
            Timing(
                f"Monthly totals in a small workspace ({len(sample)} sampled)",
                round(statistics.median(j_times), 2),
                round(statistics.median(p_times), 2),
                note="median",
            ),
        )

    def _plans(self) -> None:
        ws = self.jsonb.workspace.pk
        for key in ("monthly", "owes", "customer_sales"):
            j_sql = self._sql()[key][0]
            params = [ws] if key != "customer_sales" else [ws, self.j_customers[3]]
            rows = _fetch("EXPLAIN " + j_sql, params)
            self.report.plans[key] = "\n".join(r[0] for r in rows)
        uses_index = all(
            "business_record_scoped_key" in plan
            or "business_record_by_created" in plan
            or "business_records_pkey" in plan
            for plan in self.report.plans.values()
        )
        no_seq_scan = all(
            "Seq Scan on business_records" not in p for p in self.report.plans.values()
        )
        self.report.checks.append(
            Check(
                "JSONB query plans use the workspace/table-scoped indexes, no full scans",
                uses_index and no_seq_scan,
                True,
                "physical tables are per workspace already",
            )
        )


def _fetch_none(sql: str, params: list[Any] | None = None) -> None:
    with connection.cursor() as cur:
        cur.execute(sql, params or [])


def _relation_count() -> int:
    return _fetch("SELECT count(*) FROM pg_class")[0][0]


def _physical_relation_count(schemas: list[str]) -> int:
    return _fetch(
        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = ANY(%s)",
        [schemas],
    )[0][0]


def _fmt(value: float | None, unit: str) -> str:
    if value is None:
        return "–"
    if unit in ("rows/s", "relations"):
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def _ratio(t: Timing) -> str:
    """How many times faster or smaller the better side is, from JSONB's point of view."""
    if not t.jsonb or not t.physical:
        return ""
    higher_is_better = t.unit == "rows/s"
    ratio = t.jsonb / t.physical
    if higher_is_better:
        ratio = 1 / ratio
    if 0.9 <= ratio <= 1.11:
        return "about the same"
    if ratio > 1:
        return f"physical {ratio:.1f}x better"
    return f"JSONB {1 / ratio:.1f}x better"


def render_markdown(report: Report) -> str:
    lines = ["# Storage benchmark results: JSONB vs physical tables", ""]
    lines.append(
        "Generated by `python manage.py run_storage_benchmark`. The decision and its "
        "reasoning are in `docs/storage-decision.md`; this file is the raw evidence."
    )
    lines += ["", "## Environment", ""]
    lines += [f"- **{k}:** {v}" for k, v in report.environment.items()]
    params = ", ".join(f"{k}={v}" for k, v in report.params.items())
    lines += [f"- **Parameters:** {params}", ""]

    lines += ["## Correctness (pass/fail)", "", "| Check | JSONB | Physical | Note |"]
    lines += ["| --- | --- | --- | --- |"]
    for c in report.checks:
        mark = {True: "pass", False: "**FAIL**"}
        lines.append(f"| {c.name} | {mark[c.jsonb]} | {mark[c.physical]} | {c.note} |")
    lines.append("")

    for section, timings in report.sections.items():
        lines += [f"## {section}", "", "| Measure | JSONB | Physical | Unit | Comparison | Note |"]
        lines += ["| --- | --- | --- | --- | --- | --- |"]
        for t in timings:
            lines.append(
                f"| {t.name} | {_fmt(t.jsonb, t.unit)} | {_fmt(t.physical, t.unit)} | {t.unit} "
                f"| {_ratio(t)} | {t.note} |"
            )
        lines.append("")

    if report.plans:
        lines += ["## JSONB query plans (after loading every workspace)", ""]
        for key, plan in report.plans.items():
            lines += [f"**{key}**", "", "```", plan, "```", ""]
    return "\n".join(lines)
