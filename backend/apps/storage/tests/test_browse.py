"""Browsing a table: filters, search, sorting, counts, lookups and the tables index."""

import json

import pytest
from django.urls import reverse

from apps.storage.testing import CUSTOMERS, PRODUCTS, SALES

pytestmark = pytest.mark.django_db


def browse(client, workspace, table_id, **params):
    if "filter" in params:
        params["filter"] = json.dumps({"all": params["filter"]})
    url = reverse("record-list", kwargs={"workspace_id": workspace.id, "table_id": table_id})
    return client.get(url, params)


def ids(response) -> set[str]:
    assert response.status_code == 200, response.json()
    return {r["id"] for r in response.json()["results"]}


@pytest.fixture
def shop(make_customer, make_product, make_sale):
    ada = make_customer(fld_customer_name="Adaeze Okafor", fld_customer_area="Yaba")
    bayo = make_customer(fld_customer_name="Bayo 50% Stores", fld_customer_area=None)
    rice = make_product(fld_product_name="Rice 50kg", fld_product_unit_price="45000.00")
    soap = make_product(fld_product_name="Soap", fld_product_unit_price="900.00")
    sales = {
        "big": make_sale(
            product=rice,
            customer=ada,
            fld_sale_total_amount="90000.00",
            fld_sale_date="2026-11-01",
            fld_sale_payment_status="unpaid",
        ),
        "small": make_sale(
            product=soap,
            customer=bayo,
            fld_sale_total_amount="900.00",
            fld_sale_date="2026-11-20",
            fld_sale_payment_status="paid",
        ),
        "anon": make_sale(
            product=soap,
            fld_sale_total_amount="9000.00",
            fld_sale_date="2026-10-05",
            fld_sale_payment_status="part_paid",
        ),
    }
    return {"ada": ada, "bayo": bayo, "rice": rice, "soap": soap, **sales}


def sid(shop, *names):
    return {str(shop[n].id) for n in names}


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        # Money compares as a number, not as text ("9000.00" > "90000.00" as text).
        ([{"field": "fld_sale_total_amount", "op": "gt", "value": "8999"}], ("big", "anon")),
        ([{"field": "fld_sale_total_amount", "op": "lte", "value": 900}], ("small",)),
        ([{"field": "fld_sale_date", "op": "gte", "value": "2026-11-01"}], ("big", "small")),
        (
            [{"field": "fld_sale_payment_status", "op": "in", "value": ["unpaid", "part_paid"]}],
            ("big", "anon"),
        ),
        ([{"field": "fld_sale_payment_status", "op": "neq", "value": "paid"}], ("big", "anon")),
        ([{"field": "fld_sale_customer", "op": "is_empty"}], ("anon",)),
        ([{"field": "fld_sale_customer", "op": "not_empty"}], ("big", "small")),
        ([{"field": "fld_sale_notes", "op": "is_empty"}], ("big", "small", "anon")),
        (
            [
                {"field": "fld_sale_date", "op": "lt", "value": "2026-11-15"},
                {"field": "fld_sale_total_amount", "op": "gte", "value": "9000.00"},
            ],
            ("big", "anon"),
        ),
    ],
)
def test_sale_filters(shop, client_for, owner, workspace, spec, expected):
    assert ids(browse(client_for(owner), workspace, SALES, filter=spec)) == sid(shop, *expected)


def test_filter_by_linked_record(shop, client_for, owner, workspace):
    spec = [{"field": "fld_sale_customer", "op": "eq", "value": str(shop["ada"].id)}]
    assert ids(browse(client_for(owner), workspace, SALES, filter=spec)) == sid(shop, "big")


def test_text_filters_ignore_case_and_treat_wildcards_literally(shop, client_for, owner, workspace):
    client = client_for(owner)
    contains = [{"field": "fld_customer_name", "op": "contains", "value": "50%"}]
    assert ids(browse(client, workspace, CUSTOMERS, filter=contains)) == sid(shop, "bayo")
    starts = [{"field": "fld_customer_name", "op": "starts_with", "value": "ADA"}]
    assert ids(browse(client, workspace, CUSTOMERS, filter=starts)) == sid(shop, "ada")
    eq = [{"field": "fld_customer_area", "op": "eq", "value": "yaba"}]
    assert ids(browse(client, workspace, CUSTOMERS, filter=eq)) == sid(shop, "ada")
    neq = [{"field": "fld_customer_area", "op": "neq", "value": "yaba"}]
    assert ids(browse(client, workspace, CUSTOMERS, filter=neq)) == sid(shop, "bayo")


def test_search_looks_in_text_fields(shop, client_for, owner, workspace):
    client = client_for(owner)
    assert ids(browse(client, workspace, PRODUCTS, search="rice")) == sid(shop, "rice")
    assert ids(browse(client, workspace, PRODUCTS, search="_")) == set()


def test_sorting_by_money_is_numeric_with_empties_last(shop, client_for, owner, workspace):
    client = client_for(owner)
    response = browse(client, workspace, SALES, ordering="-fld_sale_total_amount")
    totals = [r["values"]["fld_sale_total_amount"] for r in response.json()["results"]]
    assert totals == ["90000.00", "9000.00", "900.00"]
    response = browse(client, workspace, CUSTOMERS, ordering="fld_customer_area")
    assert [r["values"]["fld_customer_area"] for r in response.json()["results"]] == ["Yaba", None]


def test_pages_report_the_total_count(shop, client_for, owner, workspace):
    body = browse(client_for(owner), workspace, SALES, page_size=2).json()
    assert body["count"] == 3
    assert len(body["results"]) == 2


@pytest.mark.parametrize(
    ("params", "where"),
    [
        ({"filter": [{"field": "fld_nope", "op": "eq", "value": 1}]}, "filter.0"),
        (
            {"filter": [{"field": "fld_sale_total_amount", "op": "contains", "value": "1"}]},
            "filter.0",
        ),
        ({"filter": [{"field": "fld_sale_total_amount", "op": "gt", "value": 1.5}]}, "filter.0"),
        ({"filter": [{"field": "fld_sale_date", "op": "gt", "value": "26/11/2026"}]}, "filter.0"),
        ({"filter": [{"field": "fld_sale_customer", "op": "eq", "value": "x"}]}, "filter.0"),
        ({"filter": [{"field": "fld_sale_payment_status", "op": "in", "value": []}]}, "filter.0"),
        ({"filter": ["oops"]}, "filter.0"),
        ({"ordering": "fld_sale_customer"}, "ordering"),
        ({"ordering": "data; drop table x"}, "ordering"),
    ],
)
def test_bad_filters_are_refused_plainly(shop, client_for, owner, workspace, params, where):
    response = browse(client_for(owner), workspace, SALES, **params)
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_filter"
    assert where in response.json()["details"]


def test_malformed_filter_json(store, client_for, owner, workspace):
    url = reverse("record-list", kwargs={"workspace_id": workspace.id, "table_id": SALES})
    client = client_for(owner)
    assert client.get(url, {"filter": "{"}).status_code == 400
    assert client.get(url, {"filter": '{"any": []}'}).status_code == 400
    many = json.dumps({"all": [{"field": "fld_sale_notes", "op": "is_empty"}] * 21})
    assert client.get(url, {"filter": many}).status_code == 400


def test_lookup_lists_titles_for_link_pickers(shop, client_for, owner, workspace):
    url = reverse("record-lookup", kwargs={"workspace_id": workspace.id, "table_id": CUSTOMERS})
    client = client_for(owner)
    items = client.get(url).json()
    assert [i["title"] for i in items] == ["Adaeze Okafor", "Bayo 50% Stores"]
    assert items[0] == {"id": str(shop["ada"].id), "title": "Adaeze Okafor", "version": 1}
    assert [i["title"] for i in client.get(url, {"search": "bayo"}).json()] == ["Bayo 50% Stores"]
    assert len(client.get(url, {"limit": "1"}).json()) == 1
    assert len(client.get(url, {"limit": "nope"}).json()) == 2


def test_lookup_without_a_title_field(shop, client_for, owner, workspace):
    url = reverse("record-lookup", kwargs={"workspace_id": workspace.id, "table_id": SALES})
    assert {i["title"] for i in client_for(owner).get(url).json()} == {None}


def test_tables_index_counts_records(shop, client_for, owner, workspace):
    url = reverse("table-list", kwargs={"workspace_id": workspace.id})
    rows = {r["table_id"]: r for r in client_for(owner).get(url).json()}
    assert rows[SALES]["record_count"] == 3
    assert rows[CUSTOMERS]["record_count"] == 2
    assert rows["tbl_payments"] == {
        "table_id": "tbl_payments",
        "record_count": 0,
        "last_updated": None,
    }


def test_browsing_is_scoped_to_members(shop, client_for, make_user, workspace):
    stranger = client_for(make_user("stranger"))
    assert browse(stranger, workspace, SALES).status_code == 404
    url = reverse("table-list", kwargs={"workspace_id": workspace.id})
    assert stranger.get(url).status_code == 404
