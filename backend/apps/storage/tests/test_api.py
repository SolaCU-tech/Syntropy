"""Record endpoints: membership, roles, error shapes, optimistic concurrency, pagination."""

import uuid

import pytest
from django.urls import reverse

from apps.storage.testing import CUSTOMERS, PRODUCTS, SALES, customer_values, product_values

pytestmark = pytest.mark.django_db


def list_url(workspace, table_id=CUSTOMERS) -> str:
    return reverse("record-list", kwargs={"workspace_id": workspace.id, "table_id": table_id})


def detail_url(workspace, record_id, table_id=CUSTOMERS) -> str:
    return reverse(
        "record-detail",
        kwargs={"workspace_id": workspace.id, "table_id": table_id, "record_id": record_id},
    )


def test_create_read_edit_delete_round_trip(store, client_for, owner, workspace):
    client = client_for(owner)

    created = client.post(list_url(workspace), {"values": customer_values(1)}, format="json")
    assert created.status_code == 201, created.json()
    record = created.json()
    assert record["version"] == 1
    assert record["values"]["fld_customer_credit_limit"] is None
    assert record["created_by"] == owner.pk

    url = detail_url(workspace, record["id"])
    assert client.get(url).json() == record

    edited = client.patch(
        url, {"version": 1, "values": {"fld_customer_credit_limit": "2500"}}, format="json"
    )
    assert edited.status_code == 200
    assert edited.json()["values"]["fld_customer_credit_limit"] == "2500.00"

    stale = client.patch(url, {"version": 1, "values": {"fld_customer_area": "x"}}, format="json")
    assert stale.status_code == 409
    assert stale.json()["code"] == "version_conflict"
    assert stale.json()["current"]["version"] == 2

    deleted = client.delete(url + "?version=2")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": [record["id"]]}
    assert client.get(url).status_code == 404


def test_errors_use_the_standard_shape(store, client_for, owner, workspace):
    client = client_for(owner)

    bad = client.post(
        list_url(workspace, PRODUCTS), {"values": {"fld_product_name": ""}}, format="json"
    )
    assert bad.status_code == 400
    assert bad.json()["code"] == "invalid"
    assert "fld_product_name" in bad.json()["details"]
    assert "fld_product_unit_price" in bad.json()["details"]

    client.post(list_url(workspace, PRODUCTS), {"values": product_values(1)}, format="json")
    dup = client.post(list_url(workspace, PRODUCTS), {"values": product_values(1)}, format="json")
    assert dup.status_code == 409
    assert dup.json()["code"] == "duplicate_value"

    missing = client.get(list_url(workspace, "tbl_nothing"))
    assert missing.status_code == 404
    assert missing.json()["code"] == "unknown_table"

    no_body = client.post(list_url(workspace), {}, format="json")
    assert no_body.status_code == 400


def test_restricted_delete_returns_409(store, client_for, owner, workspace, make_sale):
    sale = make_sale()
    response = client_for(owner).delete(
        detail_url(workspace, sale.values["fld_sale_product"], PRODUCTS)
    )
    assert response.status_code == 409
    assert response.json()["code"] == "record_in_use"


def test_non_members_get_the_same_404_as_missing_workspaces(store, client_for, make_user):
    stranger = make_user("stranger")
    response = client_for(stranger).get(list_url(store.workspace))
    assert response.status_code == 404
    assert response.json()["code"] == "workspace_not_found"


def test_records_are_found_only_through_their_own_table(store, client_for, owner, make_sale):
    sale = make_sale()
    # The right ID under the wrong table is not found.
    response = client_for(owner).get(detail_url(store.workspace, sale.id, CUSTOMERS))
    assert response.status_code == 404


def test_viewers_read_but_cannot_write(store, client_for, add_member, make_customer):
    customer = make_customer()
    viewer = client_for(add_member("viewer"))

    assert viewer.get(list_url(store.workspace)).status_code == 200
    assert viewer.get(detail_url(store.workspace, customer.id)).status_code == 200
    denied = viewer.post(list_url(store.workspace), {"values": customer_values(9)}, format="json")
    assert denied.status_code == 403
    assert denied.json()["code"] == "workspace_permission_denied"
    assert viewer.delete(detail_url(store.workspace, customer.id)).status_code == 403


def test_editors_delete_only_their_own_records(store, client_for, add_member, make_customer):
    someone_elses = make_customer()
    editor_user = add_member("editor")
    editor = client_for(editor_user)

    own = editor.post(list_url(store.workspace), {"values": customer_values(5)}, format="json")
    assert own.status_code == 201

    assert editor.delete(detail_url(store.workspace, someone_elses.id)).status_code == 403
    assert editor.delete(detail_url(store.workspace, own.json()["id"])).status_code == 200


def test_client_generated_ids(store, client_for, owner, workspace):
    record_id = str(uuid.uuid4())
    client = client_for(owner)
    body = {"id": record_id, "values": customer_values(1)}

    assert client.post(list_url(workspace), body, format="json").json()["id"] == record_id
    again = client.post(list_url(workspace), body, format="json")
    assert again.status_code == 409
    assert again.json()["code"] == "record_exists"


def test_list_pages_newest_first_with_links(store, client_for, owner, workspace, make_sale):
    customer = store.create(CUSTOMERS, customer_values(1))
    for _ in range(3):
        make_sale(customer=customer)

    client = client_for(owner)
    first = client.get(list_url(workspace, SALES) + "?page_size=2").json()
    assert len(first["results"]) == 2
    assert first["results"][0]["values"]["fld_sale_customer"] == str(customer.id)
    second = client.get(first["next"]).json()
    assert len(second["results"]) == 1
    assert second["next"] is None
