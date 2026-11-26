"""Value validation and canonical forms (no database)."""

import pytest

from apps.schema_registry.ssd import FieldDef, Table
from apps.storage.values import REQUIRED, clean_values, unique_key


def field(**kw) -> FieldDef:
    base = {"id": "fld_value", "key": "value", "label": "Value"}
    return FieldDef(**{**base, **kw})


def table(*fields: FieldDef) -> Table:
    return Table(id="tbl_things", key="things", label="Things", fields=list(fields))


def clean_one(f: FieldDef, raw, *, creating=True):
    result = clean_values(table(f), {f.id: raw}, creating=creating)
    return result.scalars.get(f.id, result.links.get(f.id)), result.errors.get(f.id)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1500", "1500.00"),
        ("1500.5", "1500.50"),
        (1500, "1500.00"),
        ("-0.00", "0.00"),
        (" 12.3 ", "12.30"),
    ],
)
def test_decimals_are_stored_as_canonical_strings(raw, expected):
    value, errors = clean_one(field(type="decimal", scale=2), raw)
    assert errors is None
    assert value == expected


@pytest.mark.parametrize("raw", [0.1, True, "1.005", "1e3", "abc", "NaN", "Infinity"])
def test_decimals_reject_floats_rounding_and_junk(raw):
    _, errors = clean_one(field(type="decimal", scale=2), raw)
    assert errors


def test_decimal_precision_and_range():
    f = field(type="decimal", scale=2, precision=5, min_value="0", max_value="500")
    assert clean_one(f, "500.00")[1] is None
    assert clean_one(f, "500.01")[1]
    assert clean_one(f, "-1")[1]
    assert clean_one(field(type="decimal", scale=2, precision=4), "123.45")[1]


@pytest.mark.parametrize(
    ("raw", "ok"),
    [(5, True), ("5", True), (True, False), (1.5, False), (2**53, False), ("5.0", False)],
)
def test_integers(raw, ok):
    value, errors = clean_one(field(type="integer"), raw)
    assert (errors is None) == ok
    if ok:
        assert value == 5


def test_integer_range():
    f = field(type="integer", min_value="1", max_value="10")
    assert clean_one(f, 0)[1]
    assert clean_one(f, 11)[1]
    assert clean_one(f, 10)[1] is None


def test_dates_and_datetimes():
    assert clean_one(field(type="date"), "2026-11-24") == ("2026-11-24", None)
    assert clean_one(field(type="date"), "20261124")[1]
    assert clean_one(field(type="date"), "2026-02-30")[1]
    assert clean_one(field(type="datetime"), "2026-11-24T10:30:00+01:00") == (
        "2026-11-24T09:30:00Z",
        None,
    )
    assert clean_one(field(type="datetime"), "2026-11-24T10:30:00")[1]  # no time zone


def test_text_enum_boolean_reference():
    assert clean_one(field(type="text", max_length=3), "abcd")[1]
    assert clean_one(field(type="text"), "a\x00b")[1]
    assert clean_one(field(type="text"), 5)[1]
    enum = field(type="enum", options=[{"key": "a", "label": "A"}])
    assert clean_one(enum, "a") == ("a", None)
    assert clean_one(enum, "b")[1]
    assert clean_one(field(type="boolean"), "true")[1]
    assert clean_one(field(type="reference"), "not-a-uuid")[1]


def test_required_defaults_and_unknown_fields():
    name = field(id="fld_name", key="name", type="text", required=True)
    status = field(
        id="fld_status",
        key="status",
        type="enum",
        options=[{"key": "new", "label": "New"}],
        default="new",
    )
    t = table(name, status)

    created = clean_values(t, {"fld_name": "Ade"}, creating=True)
    assert created.errors == {}
    assert created.scalars == {"fld_name": "Ade", "fld_status": "new"}

    assert clean_values(t, {"fld_name": "   "}, creating=True).errors == {"fld_name": [REQUIRED]}
    assert clean_values(t, {}, creating=True).errors == {"fld_name": [REQUIRED]}
    # An update only touches what it names, but can't clear a required field.
    assert clean_values(t, {}, creating=False).errors == {}
    assert clean_values(t, {"fld_name": None}, creating=False).errors == {"fld_name": [REQUIRED]}
    assert "fld_nope" in clean_values(t, {"fld_nope": 1}, creating=False).errors
    assert clean_values(t, ["not", "a", "dict"], creating=True).errors


def test_unique_keys_ignore_case_and_spacing_for_text():
    text = field(type="text")
    assert unique_key(text, " Indomie  Noodles") == unique_key(text, "indomie noodles")
    assert unique_key(field(type="decimal", scale=2), "5.00") == "5.00"
    assert unique_key(text, "x" * 500).startswith("sha256:")
