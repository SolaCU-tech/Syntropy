"""Phase 1 exit gate: the hand-written retail SSD is valid."""

import json

from apps.schema_registry.examples import RETAIL_SSD_PATH
from apps.schema_registry.ssd import (
    JSON_SCHEMA_PATH,
    SSD,
    Cardinality,
    DeletePolicy,
    DisplayRole,
    LogicalType,
    json_schema,
    json_schema_text,
    parse_ssd,
)


def test_retail_ssd_is_valid():
    ssd = parse_ssd(RETAIL_SSD_PATH.read_text(encoding="utf-8"))

    assert ssd.spec_version == "1.0"
    assert [t.key for t in ssd.tables] == ["customers", "products", "sales"]


def test_retail_ssd_links_sales_to_customers_and_products(retail):
    ssd = parse_ssd(retail)
    sales = ssd.table_by_key("sales")
    links = {
        (ssd.table_by_id(r.from_table).key, sales.field_by_id(r.from_field).key): (
            ssd.table_by_id(r.to_table).key,
            r.cardinality,
            r.optional,
            r.on_delete,
        )
        for r in ssd.relationships
    }

    assert links == {
        ("sales", "customer"): ("customers", Cardinality.MANY_TO_ONE, True, DeletePolicy.RESTRICT),
        ("sales", "product"): ("products", Cardinality.MANY_TO_ONE, False, DeletePolicy.RESTRICT),
    }


def test_retail_ssd_money_fields_are_naira_decimals(retail):
    ssd = parse_ssd(retail)
    money = [f for t in ssd.tables for f in t.fields if f.display_role == DisplayRole.MONEY]

    assert money, "the retail example should have money fields"
    for field in money:
        assert field.type == LogicalType.DECIMAL
        assert field.currency == "NGN"
        assert field.scale == 2


def test_every_retail_table_has_a_title_or_date_field(retail):
    ssd = parse_ssd(retail)
    for table in ssd.tables:
        roles = {f.display_role for f in table.fields}
        assert roles & {DisplayRole.TITLE, DisplayRole.DATE}, table.key


def test_ssd_round_trips_through_json(retail):
    ssd = parse_ssd(retail)
    again = parse_ssd(ssd.model_dump_json())

    assert again == ssd


def test_decimals_stay_strings_in_json(retail):
    dumped = json.loads(parse_ssd(retail).model_dump_json())
    credit_limit = dumped["tables"][0]["fields"][3]

    assert credit_limit["min_value"] == "0"
    amount_paid = next(f for f in dumped["tables"][2]["fields"] if f["key"] == "amount_paid")
    assert amount_paid["default"] == "0.00"


def test_committed_json_schema_matches_the_models():
    # If this fails, run: python manage.py export_ssd_schema
    assert JSON_SCHEMA_PATH.read_text(encoding="utf-8") == json_schema_text()


def test_json_schema_describes_the_document():
    schema = json_schema()

    assert schema["title"] == SSD.model_config["title"]
    assert set(schema["required"]) == {"spec_version", "tables"}
    assert schema["additionalProperties"] is False
