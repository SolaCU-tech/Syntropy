"""Adversarial integrity tests (spec sections 9 and 21, Integrity gate).

Two kinds: the database must refuse bad writes even when application code is bypassed, and
concurrent writers must not be able to break uniqueness, links or versions.
"""

import threading
import uuid

import pytest
from django.db import IntegrityError, connection, transaction

from apps.schema_registry import registry
from apps.storage import errors
from apps.storage.models import BusinessRecord, RecordRelationship, UniqueValue
from apps.storage.store import get_record_store
from apps.storage.testing import CUSTOMERS, PRODUCTS, SALES, customer_values, product_values
from apps.tenancy.services import create_workspace


@pytest.fixture
def other_store(make_user, published_ssd):
    """A second business with the same structure."""
    user = make_user("rival")
    workspace = create_workspace(user, "Rival Stores")
    registry.publish(registry.create_draft(workspace, published_ssd))
    return get_record_store(workspace)


def _raw_link(store, *, from_record, to_record, to_table=CUSTOMERS, workspace=None):
    return RecordRelationship.objects.create(
        workspace=workspace or store.workspace,
        relationship_id="rel_sale_customer",
        from_table_id=SALES,
        from_record_id=from_record,
        to_table_id=to_table,
        to_record_id=to_record,
    )


# The database refuses bad writes even when the store is bypassed.


@pytest.mark.django_db
class TestDatabaseSafeguards:
    def test_link_across_workspaces_is_impossible(self, store, other_store, make_sale):
        sale = make_sale()
        foreign = other_store.create(CUSTOMERS, customer_values(1))
        with pytest.raises(IntegrityError), transaction.atomic():
            _raw_link(store, from_record=sale.id, to_record=foreign.id)

    def test_link_to_a_record_in_the_wrong_table_is_impossible(self, store, make_sale):
        sale = make_sale()
        product_id = sale.values["fld_sale_product"]
        # Claiming the product is a customer: the composite key doesn't exist.
        with pytest.raises(IntegrityError), transaction.atomic():
            _raw_link(store, from_record=sale.id, to_record=product_id, to_table=CUSTOMERS)

    def test_link_to_a_missing_record_is_impossible(self, store, make_sale):
        sale = make_sale()
        with pytest.raises(IntegrityError), transaction.atomic():
            _raw_link(store, from_record=sale.id, to_record=uuid.uuid4())

    def test_deleting_a_referenced_record_directly_is_refused(self, make_sale):
        sale = make_sale()
        with pytest.raises(IntegrityError), transaction.atomic():
            BusinessRecord.objects.filter(pk=sale.values["fld_sale_product"]).delete()

    def test_a_second_link_for_the_same_relationship_is_refused(
        self, store, make_sale, make_customer
    ):
        sale = make_sale(customer=make_customer())
        with pytest.raises(IntegrityError), transaction.atomic():
            _raw_link(store, from_record=sale.id, to_record=make_customer().id)

    def test_duplicate_unique_value_rows_are_refused(self, store, make_customer):
        customer = make_customer(fld_customer_phone="08030000001")
        other = make_customer(fld_customer_phone=None)
        with pytest.raises(IntegrityError), transaction.atomic():
            UniqueValue.objects.create(
                workspace=store.workspace,
                table_id=CUSTOMERS,
                field_id="fld_customer_phone",
                value_key="08030000001",
                record_id=other.id,
            )
        assert customer

    @pytest.mark.parametrize(
        "sql",
        [
            "UPDATE business_records SET table_id = 'tbl_products' WHERE id = %s",
            "UPDATE business_records SET version = version WHERE id = %s",
            'UPDATE business_records SET data = \'{"fld_x": {"nested": 1}}\' WHERE id = %s',
            'UPDATE business_records SET data = \'{"name": "no field id"}\' WHERE id = %s',
            "UPDATE business_records SET data = '[1, 2]' WHERE id = %s",
        ],
    )
    def test_record_identity_and_shape_are_guarded(self, make_customer, sql):
        customer = make_customer()
        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cur:
            cur.execute(sql, [customer.id])


@pytest.mark.django_db
def test_a_store_never_sees_another_workspaces_records(store, other_store):
    theirs = other_store.create(CUSTOMERS, customer_values(1))
    with pytest.raises(errors.RecordNotFound):
        store.get(CUSTOMERS, theirs.id)
    with pytest.raises(errors.RecordNotFound):
        store.update(CUSTOMERS, theirs.id, {"fld_customer_area": "x"}, expected_version=1)
    with pytest.raises(errors.RecordNotFound):
        store.delete(CUSTOMERS, theirs.id)
    # Linking to another business's record fails the friendly check first.
    with pytest.raises(errors.InvalidReference):
        store.create(
            SALES,
            {
                "fld_sale_date": "2026-11-24",
                "fld_sale_product": str(uuid.uuid4()),
                "fld_sale_customer": str(theirs.id),
                "fld_sale_quantity": 1,
                "fld_sale_unit_price": "1.00",
                "fld_sale_total_amount": "1.00",
            },
        )
    assert store.queryset(CUSTOMERS).count() == 0


@pytest.mark.django_db
def test_the_same_unique_value_in_two_workspaces_is_fine(store, other_store):
    store.create(CUSTOMERS, customer_values(1))
    other_store.create(CUSTOMERS, customer_values(1))


# Concurrency: real threads, each on its own database connection.


def _race(n: int, fn) -> list:
    """Run ``fn(i)`` in ``n`` threads released together; return results or exceptions."""
    barrier = threading.Barrier(n)
    results: list = [None] * n

    def run(i: int) -> None:
        try:
            barrier.wait()
            results[i] = fn(i)
        except Exception as exc:  # noqa: BLE001 - the test inspects what each thread got
            results[i] = exc
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


@pytest.mark.django_db(transaction=True)
def test_concurrent_creates_of_one_unique_value_let_exactly_one_win(store):
    def create(i: int):
        values = customer_values(i) | {"fld_customer_phone": "08039999999"}
        return get_record_store(store.workspace).create(CUSTOMERS, values)

    results = _race(8, create)

    winners = [r for r in results if not isinstance(r, Exception)]
    assert len(winners) == 1
    assert all(isinstance(r, errors.DuplicateValue) for r in results if r not in winners)
    assert BusinessRecord.objects.filter(table_id=CUSTOMERS).count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_edits_of_one_version_let_exactly_one_win(store):
    product = store.create(PRODUCTS, product_values(1))

    def edit(i: int):
        return get_record_store(store.workspace).update(
            PRODUCTS, product.id, {"fld_product_stock_quantity": i}, expected_version=1
        )

    results = _race(6, edit)

    winners = [r for r in results if not isinstance(r, Exception)]
    assert len(winners) == 1
    assert all(isinstance(r, errors.VersionConflict) for r in results if r not in winners)
    assert store.get(PRODUCTS, product.id).version == 2


@pytest.mark.django_db(transaction=True)
def test_no_lost_updates_when_writers_retry_on_conflict(store):
    """Eight writers each take 5 from stock, re-reading on every conflict."""
    product = store.create(PRODUCTS, product_values(1) | {"fld_product_stock_quantity": 100})

    def take_five(_i: int):
        s = get_record_store(store.workspace)
        for _ in range(50):
            current = s.get(PRODUCTS, product.id)
            stock = current.values["fld_product_stock_quantity"] - 5
            try:
                return s.update(
                    PRODUCTS,
                    product.id,
                    {"fld_product_stock_quantity": stock},
                    expected_version=current.version,
                )
            except errors.VersionConflict:
                continue
        raise AssertionError("gave up")

    results = _race(8, take_five)

    assert not [r for r in results if isinstance(r, Exception)]
    final = store.get(PRODUCTS, product.id)
    assert final.values["fld_product_stock_quantity"] == 60
    assert final.version == 9


@pytest.mark.django_db(transaction=True)
def test_linking_to_a_record_while_it_is_deleted_never_leaves_a_dangling_link(store):
    """A sale referencing a customer races the customer's deletion, many times over.

    Whatever the interleaving, the end state is consistent: either the sale exists and links
    to a live customer, or the customer was deleted and the sale was refused or unlinked.
    """
    product = store.create(PRODUCTS, product_values(1))
    for round_ in range(15):
        customer = store.create(CUSTOMERS, customer_values(round_))

        def act(i: int, customer=customer):
            s = get_record_store(store.workspace)
            if i == 0:
                return s.delete(CUSTOMERS, customer.id)
            return s.create(
                SALES,
                {
                    "fld_sale_date": "2026-11-24",
                    "fld_sale_product": str(product.id),
                    "fld_sale_customer": str(customer.id),
                    "fld_sale_quantity": 1,
                    "fld_sale_unit_price": "1.00",
                    "fld_sale_total_amount": "1.00",
                },
            )

        results = _race(2, act)
        for r in results:
            if isinstance(r, Exception):
                assert isinstance(r, errors.InvalidReference), repr(r)

    dangling = RecordRelationship.objects.exclude(
        to_record_id__in=BusinessRecord.objects.values("id")
    )
    assert not dangling.exists()


@pytest.mark.django_db(transaction=True)
def test_restrict_holds_when_a_link_and_a_delete_race(store):
    """A product being sold can never be deleted out from under the sale."""
    for i in range(15):
        product = store.create(PRODUCTS, product_values(i))

        def act(n: int, product=product):
            s = get_record_store(store.workspace)
            if n == 0:
                return s.delete(PRODUCTS, product.id)
            return s.create(
                SALES,
                {
                    "fld_sale_date": "2026-11-24",
                    "fld_sale_product": str(product.id),
                    "fld_sale_quantity": 1,
                    "fld_sale_unit_price": "1.00",
                    "fld_sale_total_amount": "1.00",
                },
            )

        deleted, sold = _race(2, act)
        # Exactly one of them can win.
        assert isinstance(deleted, Exception) != isinstance(sold, Exception), (deleted, sold)
        if isinstance(deleted, Exception):
            assert isinstance(deleted, errors.RecordInUse)
        else:
            assert isinstance(sold, errors.InvalidReference)
