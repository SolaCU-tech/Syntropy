import pytest

from apps.schema_registry.ssd import (
    assign_missing_ids,
    is_valid_machine_key,
    make_machine_key,
    new_id,
)


@pytest.mark.parametrize(
    ("label", "key"),
    [
        ("Customer Name", "customer_name"),
        ("Customer's Phone No.", "customer_s_phone_no"),
        ("  Amount (₦)  ", "amount"),
        ("Café Owner", "cafe_owner"),
        ("2024 Sales", "f_2024_sales"),
        ("Order", "order_value"),
        ("ID", "id_value"),
        ("class", "class_value"),
        ("!!!", "field"),
        ("", "field"),
    ],
)
def test_make_machine_key(label, key):
    assert make_machine_key(label) == key
    assert is_valid_machine_key(key)


def test_make_machine_key_deduplicates():
    taken = {"name", "name_2"}

    assert make_machine_key("Name", taken) == "name_3"


def test_make_machine_key_respects_postgres_length_limit():
    key = make_machine_key("x" * 100, {"x" * 63})

    assert len(key) <= 63
    assert key.endswith("_2")


@pytest.mark.parametrize("key", ["Name", "name__x", "_name", "name_", "1name", "select", "id"])
def test_invalid_machine_keys(key):
    assert not is_valid_machine_key(key)


def test_new_ids_have_the_right_prefix_and_are_unique():
    ids = {new_id("field") for _ in range(100)}

    assert len(ids) == 100
    assert all(i.startswith("fld_") for i in ids)


def test_assign_missing_ids_keeps_existing_ones(retail):
    del retail["tables"][0]["fields"][1]["id"]
    del retail["source_mappings"][0]["id"]

    filled = assign_missing_ids(retail)

    assert filled["tables"][0]["id"] == "tbl_customers"
    assert filled["tables"][0]["fields"][1]["id"].startswith("fld_")
    assert filled["source_mappings"][0]["id"].startswith("map_")
    assert "id" not in retail["tables"][0]["fields"][1], "the input must not be modified"
