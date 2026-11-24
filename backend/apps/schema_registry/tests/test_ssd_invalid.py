"""Invalid SSD fixtures: each mutation of the retail example must be rejected with its code."""

import pytest

from apps.schema_registry.ssd import SSDValidationError, parse_ssd


def _table(doc, key):
    return next(t for t in doc["tables"] if t["key"] == key)


def _field(doc, table_key, field_key):
    return next(f for f in _table(doc, table_key)["fields"] if f["key"] == field_key)


def _rel(doc, rel_id):
    return next(r for r in doc["relationships"] if r["id"] == rel_id)


def wrong_spec_version(d):
    d["spec_version"] = "2.0"


def no_tables(d):
    d["tables"] = []


def table_without_fields(d):
    _table(d, "customers")["fields"] = []


def unknown_property(d):
    d["tables"][0]["colour"] = "teal"


def unknown_logical_type(d):
    _field(d, "customers", "area")["type"] = "string"


def float_money_bound(d):
    _field(d, "products", "unit_price")["min_value"] = 0.5


def duplicate_id(d):
    _field(d, "customers", "phone")["id"] = "fld_customer_name"


def id_with_wrong_prefix(d):
    _table(d, "customers")["id"] = "customers"


def duplicate_table_key(d):
    _table(d, "products")["key"] = "customers"


def duplicate_field_key(d):
    _field(d, "customers", "area")["key"] = "phone"


def key_not_snake_case(d):
    _field(d, "customers", "area")["key"] = "Area Name"


def key_is_reserved_word(d):
    _field(d, "customers", "area")["key"] = "select"


def key_is_system_column(d):
    _field(d, "customers", "area")["key"] = "created_at"


def enum_without_options(d):
    _field(d, "sales", "payment_method")["options"] = []


def duplicate_enum_option(d):
    options = _field(d, "sales", "payment_method")["options"]
    options.append(dict(options[0]))


def decimal_without_scale(d):
    del _field(d, "products", "unit_price")["scale"]


def precision_below_scale(d):
    f = _field(d, "products", "unit_price")
    f["precision"], f["scale"] = 2, 4


def max_length_on_integer(d):
    _field(d, "sales", "quantity")["max_length"] = 10


def options_on_text(d):
    _field(d, "customers", "area")["options"] = [{"key": "ikeja", "label": "Ikeja"}]


def min_above_max(d):
    f = _field(d, "sales", "quantity")
    f["min_value"], f["max_value"] = "10", "1"


def fractional_integer_bound(d):
    _field(d, "sales", "quantity")["min_value"] = "1.5"


def enum_default_not_an_option(d):
    _field(d, "sales", "payment_status")["default"] = "refunded"


def decimal_default_too_precise(d):
    _field(d, "sales", "amount_paid")["default"] = "0.001"


def integer_default_below_min(d):
    _field(d, "products", "stock_quantity")["default"] = -1


def boolean_default_on_integer(d):
    _field(d, "products", "stock_quantity")["default"] = True


def reference_with_default(d):
    _field(d, "sales", "product")["default"] = "x"


def money_role_on_text(d):
    _field(d, "customers", "area")["display_role"] = "money"


def money_role_without_currency(d):
    del _field(d, "customers", "credit_limit")["currency"]


def two_title_fields(d):
    _field(d, "customers", "area")["display_role"] = "title"


def relationship_to_unknown_table(d):
    _rel(d, "rel_sale_product")["to_table"] = "tbl_suppliers"


def relationship_from_field_on_other_table(d):
    _rel(d, "rel_sale_product")["from_field"] = "fld_customer_name"


def relationship_from_non_reference_field(d):
    _rel(d, "rel_sale_product")["from_field"] = "fld_sale_quantity"


def reference_field_without_relationship(d):
    d["relationships"] = [r for r in d["relationships"] if r["id"] != "rel_sale_product"]


def two_relationships_on_one_field(d):
    d["relationships"].append(dict(_rel(d, "rel_sale_product"), id="rel_sale_product_again"))


def optional_disagrees_with_required(d):
    _rel(d, "rel_sale_product")["optional"] = True


def one_to_one_without_unique(d):
    _rel(d, "rel_sale_product")["cardinality"] = "one_to_one"


def set_null_on_required_link(d):
    _rel(d, "rel_sale_product")["on_delete"] = "set_null"


def target_field_not_unique(d):
    _rel(d, "rel_sale_customer")["to_field"] = "fld_customer_area"


def mapping_to_unknown_field(d):
    d["source_mappings"][0]["field"] = "fld_sale_missing"


def unknown_transform(d):
    d["source_mappings"][0]["transform"] = "run_sql"


INVALID_FIXTURES = [
    (wrong_spec_version, "literal_error"),
    (no_tables, "too_short"),
    (table_without_fields, "too_short"),
    (unknown_property, "extra_forbidden"),
    (unknown_logical_type, "enum"),
    (float_money_bound, "string_type"),
    (duplicate_id, "ssd_duplicate_id"),
    (id_with_wrong_prefix, "string_pattern_mismatch"),
    (duplicate_table_key, "ssd_duplicate_key"),
    (duplicate_field_key, "ssd_duplicate_key"),
    (key_not_snake_case, "string_pattern_mismatch"),
    (key_is_reserved_word, "ssd_reserved_key"),
    (key_is_system_column, "ssd_reserved_key"),
    (enum_without_options, "ssd_enum_without_options"),
    (duplicate_enum_option, "ssd_duplicate_option"),
    (decimal_without_scale, "ssd_decimal_without_scale"),
    (precision_below_scale, "ssd_invalid_precision"),
    (max_length_on_integer, "ssd_constraint_not_allowed"),
    (options_on_text, "ssd_constraint_not_allowed"),
    (min_above_max, "ssd_invalid_range"),
    (fractional_integer_bound, "ssd_invalid_range"),
    (enum_default_not_an_option, "ssd_invalid_default"),
    (decimal_default_too_precise, "ssd_invalid_default"),
    (integer_default_below_min, "ssd_invalid_default"),
    (boolean_default_on_integer, "ssd_invalid_default"),
    (reference_with_default, "ssd_invalid_default"),
    (money_role_on_text, "ssd_invalid_display_role"),
    (money_role_without_currency, "ssd_invalid_display_role"),
    (two_title_fields, "ssd_multiple_title_fields"),
    (relationship_to_unknown_table, "ssd_unknown_reference"),
    (relationship_from_field_on_other_table, "ssd_unknown_reference"),
    (relationship_from_non_reference_field, "ssd_invalid_relationship"),
    (reference_field_without_relationship, "ssd_orphan_reference_field"),
    (two_relationships_on_one_field, "ssd_invalid_relationship"),
    (optional_disagrees_with_required, "ssd_invalid_relationship"),
    (one_to_one_without_unique, "ssd_invalid_relationship"),
    (set_null_on_required_link, "ssd_invalid_delete_policy"),
    (target_field_not_unique, "ssd_invalid_relationship"),
    (mapping_to_unknown_field, "ssd_unknown_reference"),
    (unknown_transform, "enum"),
]


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    INVALID_FIXTURES,
    ids=[mutate.__name__ for mutate, _ in INVALID_FIXTURES],
)
def test_invalid_ssd_is_rejected(retail, mutate, expected_code):
    mutate(retail)

    with pytest.raises(SSDValidationError) as excinfo:
        parse_ssd(retail)

    assert expected_code in excinfo.value.codes


def test_validation_errors_are_plain_and_located(retail):
    key_is_reserved_word(retail)

    with pytest.raises(SSDValidationError) as excinfo:
        parse_ssd(retail)

    error = excinfo.value.errors[0]
    assert error["message"] == "Field key 'select' is a reserved word"
    assert error["location"].startswith("tables.0.fields.2")


def test_invalid_json_text_is_rejected():
    with pytest.raises(SSDValidationError) as excinfo:
        parse_ssd("{not json")

    assert excinfo.value.codes == ["json_invalid"]
