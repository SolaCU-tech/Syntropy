"""The JSONB record store: create, read, edit, delete, links, uniqueness and import."""

import uuid

import pytest

from apps.storage import errors
from apps.storage.models import BusinessRecord, RecordRelationship, UniqueValue
from apps.storage.store import get_record_store
from apps.storage.testing import CUSTOMERS, PAYMENTS, PRODUCTS, SALES, customer_values

pytestmark = pytest.mark.django_db


def test_create_stores_scalars_in_jsonb_and_links_in_the_link_table(make_customer, make_sale):
    customer = make_customer()
    sale = make_sale(customer=customer)

    row = BusinessRecord.objects.get(pk=sale.id)
    assert "fld_sale_customer" not in row.data  # links never live in the JSONB
    assert row.data["fld_sale_total_amount"] == "1000.00"
    assert row.data["fld_sale_payment_status"] == "unpaid"  # default applied
    assert row.data["fld_sale_amount_paid"] == "0.00"
    assert sale.values["fld_sale_customer"] == str(customer.id)
    assert sale.version == 1
    assert sale.schema_version == 1
    assert RecordRelationship.objects.filter(from_record_id=sale.id).count() == 2


def test_record_without_a_published_schema_is_refused(make_user):
    from apps.tenancy.services import create_workspace

    workspace = create_workspace(make_user("new"), "Empty")
    with pytest.raises(errors.NoActiveSchema):
        get_record_store(workspace).create(CUSTOMERS, {})


def test_unknown_table_and_record(store):
    with pytest.raises(errors.UnknownTable):
        store.create("tbl_nothing", {})
    with pytest.raises(errors.RecordNotFound):
        store.get(CUSTOMERS, uuid.uuid4())
    with pytest.raises(errors.RecordNotFound):
        store.get(CUSTOMERS, "not-a-uuid")


def test_invalid_values_write_nothing(store):
    with pytest.raises(errors.RecordValidationError) as exc:
        store.create(PRODUCTS, {"fld_product_name": "Rice", "fld_product_unit_price": 1.5})
    assert set(exc.value.details) == {"fld_product_unit_price"}
    assert not BusinessRecord.objects.exists()


def test_client_generated_ids_are_kept_and_cannot_be_reused(store):
    record_id = uuid.uuid4()
    created = store.create(CUSTOMERS, customer_values(1), record_id=record_id)
    assert created.id == record_id
    with pytest.raises(errors.RecordExists):
        store.create(CUSTOMERS, customer_values(2), record_id=record_id)


def test_update_merges_bumps_version_and_rejects_stale_versions(store, make_customer):
    customer = make_customer(fld_customer_area="Yaba")

    updated = store.update(
        CUSTOMERS,
        customer.id,
        {"fld_customer_area": None, "fld_customer_credit_limit": "5000"},
        expected_version=1,
    )
    assert updated.version == 2
    assert updated.values["fld_customer_area"] is None
    assert updated.values["fld_customer_credit_limit"] == "5000.00"
    assert updated.values["fld_customer_name"] == customer.values["fld_customer_name"]

    with pytest.raises(errors.VersionConflict) as exc:
        store.update(CUSTOMERS, customer.id, {"fld_customer_area": "Ikeja"}, expected_version=1)
    assert exc.value.current.version == 2


def test_update_can_move_and_clear_links(store, make_customer, make_sale):
    first, second = make_customer(), make_customer()
    sale = make_sale(customer=first)

    moved = store.update(SALES, sale.id, {"fld_sale_customer": str(second.id)}, expected_version=1)
    assert moved.values["fld_sale_customer"] == str(second.id)
    cleared = store.update(SALES, sale.id, {"fld_sale_customer": None}, expected_version=2)
    assert cleared.values["fld_sale_customer"] is None

    with pytest.raises(errors.RecordValidationError):
        store.update(SALES, sale.id, {"fld_sale_product": None}, expected_version=3)


def test_unique_values_are_enforced_on_create_and_update(store, make_customer, make_product):
    make_product(fld_product_name="Indomie Noodles")
    with pytest.raises(errors.DuplicateValue) as exc:
        make_product(fld_product_name="  indomie noodles ")
    assert set(exc.value.details) == {"fld_product_name"}

    a = make_customer(fld_customer_phone="08030000001")
    b = make_customer(fld_customer_phone="08030000002")
    with pytest.raises(errors.DuplicateValue):
        store.update(CUSTOMERS, b.id, {"fld_customer_phone": "08030000001"}, expected_version=1)
    # Releasing a value lets another record take it.
    store.update(CUSTOMERS, a.id, {"fld_customer_phone": None}, expected_version=1)
    store.update(CUSTOMERS, b.id, {"fld_customer_phone": "08030000001"}, expected_version=1)
    assert UniqueValue.objects.filter(field_id="fld_customer_phone").count() == 1


def test_optional_unique_fields_allow_many_blanks(make_customer):
    make_customer(fld_customer_phone=None)
    make_customer(fld_customer_phone=None)


def test_delete_restrict_blocks_and_leaves_everything(store, make_sale):
    sale = make_sale()
    product_id = sale.values["fld_sale_product"]

    with pytest.raises(errors.RecordInUse) as exc:
        store.delete(PRODUCTS, product_id)
    assert "rel_sale_product" in exc.value.details
    assert BusinessRecord.objects.filter(pk=product_id).exists()


def test_delete_set_null_unlinks_and_bumps_the_source_version(store, make_customer, make_sale):
    customer = make_customer()
    sale = make_sale(customer=customer)

    assert store.delete(CUSTOMERS, customer.id) == [customer.id]

    after = store.get(SALES, sale.id)
    assert after.values["fld_sale_customer"] is None
    assert after.version == 2


def test_delete_cascade_removes_dependents_and_their_links(store, make_sale):
    sale = make_sale()
    payments = [
        store.create(
            PAYMENTS,
            {
                "fld_payment_date": "2026-11-24",
                "fld_payment_amount": "500.00",
                "fld_payment_sale": str(sale.id),
            },
        )
        for _ in range(2)
    ]

    deleted = store.delete(SALES, sale.id)

    assert set(deleted) == {sale.id, *(p.id for p in payments)}
    assert not BusinessRecord.objects.filter(table_id__in=[SALES, PAYMENTS]).exists()
    assert not RecordRelationship.objects.exists()


def test_delete_frees_unique_values_and_checks_the_version(store, make_customer):
    customer = make_customer(fld_customer_phone="08030000009")
    with pytest.raises(errors.VersionConflict):
        store.delete(CUSTOMERS, customer.id, expected_version=7)
    store.delete(CUSTOMERS, customer.id, expected_version=1)
    assert not UniqueValue.objects.exists()
    store.create(CUSTOMERS, customer_values(1) | {"fld_customer_phone": "08030000009"})


def test_import_is_all_or_nothing_and_reports_rows(store, make_product):
    product = make_product()
    good = {
        "fld_sale_date": "2026-01-05",
        "fld_sale_product": str(product.id),
        "fld_sale_quantity": 1,
        "fld_sale_unit_price": "10.00",
        "fld_sale_total_amount": "10.00",
    }
    rows = [good, {**good, "fld_sale_quantity": 0}, {**good, "fld_sale_product": str(uuid.uuid4())}]

    with pytest.raises(errors.ImportValidationError) as exc:
        store.import_records(SALES, rows)
    assert set(exc.value.row_errors) == {1, 2}
    assert not BusinessRecord.objects.filter(table_id=SALES).exists()

    ids = store.import_records(SALES, [good] * 3)
    assert len(ids) == 3
    assert RecordRelationship.objects.filter(relationship_id="rel_sale_product").count() == 3


def test_import_catches_duplicates_in_the_batch_and_against_existing(store, make_customer):
    make_customer(fld_customer_phone="08030000001")
    rows = [customer_values(i) for i in range(2, 5)]
    rows[1]["fld_customer_phone"] = rows[0]["fld_customer_phone"]

    with pytest.raises(errors.ImportValidationError) as exc:
        store.import_records(CUSTOMERS, rows)
    assert set(exc.value.row_errors) == {1}

    rows = [customer_values(i) for i in range(2, 5)]
    rows[2]["fld_customer_phone"] = "08030000001"
    with pytest.raises(errors.ImportValidationError) as exc:
        store.import_records(CUSTOMERS, rows)
    assert set(exc.value.row_errors) == {2}
    assert BusinessRecord.objects.filter(table_id=CUSTOMERS).count() == 1
