"""The sync endpoint: per-operation results, idempotency, permissions and request shape."""

import uuid

import pytest

from apps.storage.models import BusinessRecord
from apps.storage.testing import CUSTOMERS, PRODUCTS, SALES, customer_values
from apps.sync.models import SyncOperation

from .helpers import Device, sale

pytestmark = pytest.mark.django_db


@pytest.fixture
def device(store, client_for, owner, workspace):
    return Device(client_for(owner), workspace)


def test_creates_and_edits_apply_in_queue_order(device, make_product):
    product = make_product()
    customer_id = device.create(CUSTOMERS, customer_values(1))
    # A sale linking to a customer created offline in the same batch (client UUIDs, ADR-27).
    sale_id = device.create(SALES, sale(product.id, customer_id))
    device.edit(CUSTOMERS, customer_id, 1, {"fld_customer_area": "Yaba"})

    results = device.sync()

    assert [r["status"] for r in results] == ["applied", "applied", "applied"]
    assert results[0]["record"]["id"] == customer_id
    assert results[1]["record"]["values"]["fld_sale_customer"] == customer_id
    assert results[1]["record"]["id"] == sale_id
    assert results[2]["record"]["version"] == 2
    assert device.queue == []


def test_a_retried_batch_never_writes_twice(device):
    device.create(CUSTOMERS, customer_values(1))
    first = device.upload().json()["results"]
    # The response was lost; the phone sends the same batch again.
    second = device.upload().json()["results"]

    assert first[0]["status"] == second[0]["status"] == "applied"
    assert second[0]["replayed"] is True
    assert second[0]["record"] == first[0]["record"]
    assert BusinessRecord.objects.filter(table_id=CUSTOMERS).count() == 1


def test_reusing_a_key_for_a_different_change_is_refused(device):
    device.create(CUSTOMERS, customer_values(1))
    device.sync()
    op = {**device._op("create", CUSTOMERS, str(uuid.uuid4()), customer_values(2))}
    op["idempotency_key"] = SyncOperation.objects.get().idempotency_key.hex

    result = device.upload([op]).json()["results"][0]

    assert result["status"] == "rejected"
    assert result["error"]["code"] == "idempotency_key_reused"
    assert BusinessRecord.objects.filter(table_id=CUSTOMERS).count() == 1


def test_idempotency_keys_are_per_user(store, client_for, owner, add_member, workspace):
    key = str(uuid.uuid4())
    for user, i in ((owner, 1), (add_member("editor"), 2)):
        device = Device(client_for(user), workspace)
        device.create(CUSTOMERS, customer_values(i))
        device.queue[0]["idempotency_key"] = key
        assert device.sync()[0]["replayed"] is False
    assert BusinessRecord.objects.filter(table_id=CUSTOMERS).count() == 2


def test_invalid_values_are_rejected_with_field_details(device):
    device.create(PRODUCTS, {"fld_product_name": ""})
    result = device.sync()[0]
    assert result["status"] == "rejected"
    assert result["error"]["code"] == "invalid"
    assert "fld_product_name" in result["error"]["details"]
    assert len(device.queue) == 1  # nothing leaves the queue until the server confirms it


def test_one_failure_does_not_block_the_rest(device):
    device.create(PRODUCTS, {"fld_product_name": ""})
    device.create(CUSTOMERS, customer_values(1))
    assert [r["status"] for r in device.sync()] == ["rejected", "applied"]


def test_editing_a_record_deleted_on_the_server_is_rejected(device, make_customer):
    customer = make_customer()
    device.edit(CUSTOMERS, customer.id, 1, {"fld_customer_area": "Ikeja"})
    customer_store_delete = device.client.delete(
        f"/api/workspaces/{device.workspace.id}/tables/{CUSTOMERS}/records/{customer.id}/"
    )
    assert customer_store_delete.status_code == 200

    result = device.sync()[0]
    assert result["status"] == "rejected"
    assert result["error"]["code"] == "record_not_found"


def test_viewers_cannot_sync(store, client_for, add_member, workspace):
    device = Device(client_for(add_member("viewer")), workspace)
    device.create(CUSTOMERS, customer_values(1))
    response = device.upload()
    assert response.status_code == 403
    assert response.json()["code"] == "workspace_permission_denied"


def test_strangers_get_404(store, client_for, make_user, workspace):
    device = Device(client_for(make_user("stranger")), workspace)
    device.create(CUSTOMERS, customer_values(1))
    assert device.upload().status_code == 404


@pytest.mark.parametrize(
    ("change", "field"),
    [
        (lambda op: op.update(op="delete"), "op"),
        (lambda op: op.update(op="update"), "base_version"),
        (lambda op: op.update(table_id="DROP TABLE"), "table_id"),
        (lambda op: op.pop("idempotency_key"), "idempotency_key"),
    ],
)
def test_bad_operations_are_refused_before_anything_runs(device, change, field):
    device.create(CUSTOMERS, customer_values(1))
    change(device.queue[0])
    response = device.upload()
    assert response.status_code == 400
    assert field in str(response.json()["details"])
    assert not BusinessRecord.objects.exists()


def test_duplicate_keys_in_one_batch_are_refused(device):
    device.create(CUSTOMERS, customer_values(1))
    device.create(CUSTOMERS, customer_values(2))
    device.queue[1]["idempotency_key"] = device.queue[0]["idempotency_key"]
    assert device.upload().status_code == 400


def test_batches_are_bounded(device):
    for i in range(101):
        device.create(CUSTOMERS, customer_values(i))
    assert device.upload().status_code == 400
    assert device.upload([]).status_code == 400


def test_no_published_schema_returns_404(client_for, owner, workspace):
    device = Device(client_for(owner), workspace)
    device.create(CUSTOMERS, customer_values(1))
    response = device.upload()
    assert response.status_code == 404
    assert response.json()["code"] == "no_active_schema"
