"""Adversarial offline tests: the Phase 3 exit gate (spec sections 13, 21 and 22).

Each test models phones that queued changes while offline and sync later. The guarantees:
no queued change is lost or duplicated, and conflicts and rejections are surfaced, never
silently resolved.
"""

import copy
import threading

import pytest
from django.db import connection
from rest_framework.test import APIClient

from apps.schema_registry import registry
from apps.storage.models import BusinessRecord, RecordRelationship
from apps.storage.testing import CUSTOMERS, PRODUCTS, SALES, customer_values, product_values
from apps.sync.models import SyncOperation

from .helpers import Device, sale


@pytest.fixture
def phones(store, client_for, owner, add_member, workspace):
    """Two staff phones in the same shop."""
    return (
        Device(client_for(owner), workspace),
        Device(client_for(add_member("editor", "bisi")), workspace),
    )


@pytest.mark.django_db
def test_the_same_record_edited_on_two_devices(phones, make_product):
    """The second edit is a conflict carrying the server's version; the user chooses."""
    first, second = phones
    product = make_product()
    first.edit(PRODUCTS, product.id, 1, {"fld_product_stock_quantity": 40})
    second.edit(PRODUCTS, product.id, 1, {"fld_product_stock_quantity": 35})

    assert first.sync()[0]["status"] == "applied"
    conflict = second.sync()[0]

    assert conflict["status"] == "conflict"
    assert conflict["error"]["code"] == "version_conflict"
    assert conflict["current"]["version"] == 2
    assert conflict["current"]["values"]["fld_product_stock_quantity"] == 40
    assert len(second.queue) == 1  # kept, not dropped

    # The user picks their own value: the app re-queues it on the current version.
    second.queue = []
    second.edit(PRODUCTS, product.id, 2, {"fld_product_stock_quantity": 35})
    assert second.sync()[0]["status"] == "applied"
    stored = BusinessRecord.objects.get(id=product.id)
    assert (stored.version, stored.data["fld_product_stock_quantity"]) == (3, 35)


@pytest.mark.django_db
def test_a_duplicate_unique_value_created_offline_on_two_devices(phones):
    """Both phones add a customer with the same phone number; exactly one wins."""
    first, second = phones
    first.create(CUSTOMERS, customer_values(1) | {"fld_customer_phone": "08031234567"})
    second.create(CUSTOMERS, customer_values(2) | {"fld_customer_phone": " 08031234567 "})

    assert first.sync()[0]["status"] == "applied"
    rejected = second.sync()[0]

    assert rejected["status"] == "rejected"
    assert rejected["error"]["code"] == "duplicate_value"
    assert BusinessRecord.objects.filter(table_id=CUSTOMERS).count() == 1


@pytest.mark.django_db
def test_a_linked_record_deleted_while_a_sale_waits_in_the_queue(
    store, phones, make_customer, make_product
):
    _, offline = phones
    customer = make_customer()
    product = make_product()
    offline.create(SALES, sale(product.id, customer.id))
    # Meanwhile, online, the owner deletes that customer (nothing links to them yet).
    store.delete(CUSTOMERS, customer.id)
    first = offline

    result = first.sync()[0]

    assert result["status"] == "rejected"
    assert result["error"]["code"] == "invalid_reference"
    assert "fld_sale_customer" in result["error"]["details"]
    assert not BusinessRecord.objects.filter(table_id=SALES).exists()
    assert len(first.queue) == 1


@pytest.mark.django_db
def test_a_sale_linked_to_a_customer_that_was_rejected_is_rejected_too(phones, make_product):
    """A new customer created inline fails (duplicate phone); the sale that links to it must
    not be saved pointing nowhere."""
    first, second = phones
    product = make_product()
    second.create(CUSTOMERS, customer_values(9) | {"fld_customer_phone": "08035550000"})
    second.sync()
    customer_id = first.create(
        CUSTOMERS, customer_values(1) | {"fld_customer_phone": "08035550000"}
    )
    first.create(SALES, sale(product.id, customer_id))

    statuses = [r["status"] for r in first.sync()]

    assert statuses == ["rejected", "rejected"]
    assert not BusinessRecord.objects.filter(table_id=SALES).exists()
    assert not RecordRelationship.objects.exists()


@pytest.mark.django_db
def test_changes_made_against_an_older_schema(store, phones, published_ssd, owner, make_customer):
    """A change that still fits the new structure applies; one that doesn't is flagged."""
    first, _ = phones
    customer = make_customer()
    first.create(CUSTOMERS, customer_values(5))  # fits v2
    first.create(CUSTOMERS, customer_values(6) | {"fld_customer_phone": None})  # does not
    first.edit(CUSTOMERS, customer.id, 1, {"fld_customer_area": "Lekki"})

    v2 = copy.deepcopy(published_ssd)
    phone = next(
        f
        for t in v2["tables"]
        if t["id"] == CUSTOMERS
        for f in t["fields"]
        if f["id"] == "fld_customer_phone"
    )
    phone["required"] = True
    registry.publish(registry.create_draft(store.workspace, v2), published_by=owner)

    response = first.upload().json()
    results = response["results"]

    assert response["schema_version"] == 2
    assert [r["status"] for r in results] == ["applied", "schema_changed", "applied"]
    assert "fld_customer_phone" in results[1]["error"]["details"]
    assert results[0]["record"]["schema_version"] == 2


# Retries racing each other: real threads, each with its own database connection.


def _race(n: int, fn) -> list:
    barrier = threading.Barrier(n)
    results: list = [None] * n

    def run(i: int) -> None:
        try:
            barrier.wait()
            results[i] = fn(i)
        except Exception as exc:  # noqa: BLE001
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
def test_the_same_batch_uploaded_concurrently_is_applied_once(store, owner, workspace):
    """A flaky connection fires the same upload several times at once."""
    make = Device(None, workspace)
    customer_id = make.create(CUSTOMERS, customer_values(1))
    make.create(PRODUCTS, product_values(1))
    make.edit(CUSTOMERS, customer_id, 1, {"fld_customer_area": "Yaba"})
    batch = make.queue

    def upload(_i: int):
        client = APIClient()
        client.force_authenticate(owner)
        return Device(client, workspace).upload(batch)

    responses = _race(5, upload)

    assert all(r.status_code == 200 for r in responses)
    for response in responses:
        assert [r["status"] for r in response.json()["results"]] == ["applied"] * 3
    assert sum(not r["replayed"] for resp in responses for r in resp.json()["results"]) == 3
    assert BusinessRecord.objects.filter(table_id=CUSTOMERS).count() == 1
    assert BusinessRecord.objects.get(id=customer_id).version == 2
    assert SyncOperation.objects.count() == 3


@pytest.mark.django_db(transaction=True)
def test_two_devices_racing_for_one_unique_value_offline(store, owner, add_member, workspace):
    users = [owner, add_member("editor", "bisi"), add_member("editor", "chidi")]

    def upload(i: int):
        client = APIClient()
        client.force_authenticate(users[i])
        device = Device(client, workspace)
        device.create(PRODUCTS, product_values(i) | {"fld_product_sku": "SKU-SAME"})
        return device.upload().json()["results"][0]

    results = _race(3, upload)

    statuses = sorted(r["status"] for r in results)
    assert statuses == ["applied", "rejected", "rejected"]
    assert {r["error"]["code"] for r in results if r["status"] == "rejected"} == {"duplicate_value"}
    assert BusinessRecord.objects.filter(table_id=PRODUCTS).count() == 1
