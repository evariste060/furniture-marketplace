"""Row checks of the catalogue import that need no database (module 8)."""

from datetime import datetime

import pytest

from app.services.catalog_import import (
    BOOLEAN,
    DATE_REFUSED,
    FORMULA_REFUSED,
    INJECTION_REFUSED,
    REQUIRED,
    WHOLE_NUMBER,
    RowError,
    check_file_rows,
    check_row,
)
from app.services.import_files import FORMULA, DataRow, ParsedFile

VALID = {
    "sku": "GS24-128-BLK",
    "product_slug": "galaxy-s24",
    "product_name": "Galaxy S24",
    "category_slug": "phones",
    "variant_name": "128 GB Black",
    "price": "1250000",
}


def row(number: int = 2, **cells) -> DataRow:
    return DataRow(number=number, cells={**VALID, **cells})


def errors_of(data: DataRow) -> dict[str, str]:
    values, errors = check_row(data)
    assert values is None
    return {e.field or "": e.message for e in errors}


def test_a_valid_row_is_cleaned_into_typed_values():
    values, errors = check_row(
        row(
            price=" 1250000 ",
            compare_at_price=1300000,
            low_stock_threshold=2.0,
            variant_active="Yes",
            opening_stock="5",
            product_status="active",
            **{"attr:colour": "Black", "spec:display": 6.1, "attr:ram": ""},
        )
    )
    assert errors == []
    assert values is not None
    assert (values.price, values.compare_at_price, values.low_stock_threshold) == (
        1250000,
        1300000,
        2,
    )
    assert values.variant_active is True and values.opening_stock == 5
    assert values.attributes == {"colour": "Black"}  # blank attr cells are skipped
    assert values.specifications == {"display": "6.1"}


def test_numbers_typed_into_text_columns_become_text():
    values, _ = check_row(row(sku=12345, model=2024.0))
    assert values is not None and (values.sku, values.model) == ("12345", "2024")


@pytest.mark.parametrize(
    "value",
    ["1,500", "1500.50", "1.5e3", "-5", "RWF 1500", " ", True, 1500.5, -1, datetime(2026, 1, 1)],
    ids=lambda v: repr(v),
)
def test_prices_must_be_plain_non_negative_whole_numbers(value):
    if value == " ":
        assert errors_of(row(price=value)) == {"price": REQUIRED}
    else:
        assert errors_of(row(price=value)) == {"price": WHOLE_NUMBER}


def test_amounts_above_the_money_cap_are_refused():
    assert "price" in errors_of(row(price="9999999999999"))


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("product_name", FORMULA, FORMULA_REFUSED),
        ("price", FORMULA, FORMULA_REFUSED),
        ("variant_active", FORMULA, FORMULA_REFUSED),
        ("attr:colour", FORMULA, FORMULA_REFUSED),
        ("product_name", '=HYPERLINK("http://x")', INJECTION_REFUSED),
        ("description", "+cmd|' /C calc'!A0", INJECTION_REFUSED),
        ("model", "@SUM(1)", INJECTION_REFUSED),
        ("variant_name", "-2+3+cmd|' /C calc'!A0", INJECTION_REFUSED),
        ("spec:display", "  =1+1", INJECTION_REFUSED),
        ("warranty_text", datetime(2026, 1, 1), DATE_REFUSED),
        ("variant_active", "maybe", BOOLEAN),
    ],
)
def test_formulas_injection_like_text_and_wrong_types_are_refused(column, value, message):
    assert errors_of(row(**{column: value})) == {column: message}


def test_a_list_item_dash_is_allowed_in_text():
    values, errors = check_row(row(description="- 8 GB RAM\n- 256 GB storage"))
    assert errors == [] and values is not None


@pytest.mark.parametrize(
    ("column", "value", "expected"),
    [
        ("sku", "HAS SPACE", "A SKU may not contain spaces or '/'."),
        ("product_slug", "Not A Slug", "Use lowercase letters and digits"),
        ("category_slug", "phones_", "Use lowercase letters and digits"),
        ("product_status", "published", "Use draft, active, hidden or archived."),
        ("product_name", "x" * 241, "at most 240 characters"),
        ("low_stock_threshold", "99999999999", "less than or equal to"),
    ],
)
def test_field_rules_come_from_the_product_schemas(column, value, expected):
    assert expected in errors_of(row(**{column: value}))[column]


def test_every_blank_required_column_is_reported():
    data = DataRow(number=7, cells={column: None for column in VALID})
    assert errors_of(data) == {column: REQUIRED for column in VALID}


def test_values_right_of_the_headers_are_reported():
    data = row()
    data.extra_values = True
    _, errors = check_row(data)
    assert errors == [
        RowError(2, None, "This row has values to the right of the last column header.")
    ]


def test_errors_never_echo_the_submitted_value():
    secret = "=SECRET-VALUE-123"
    _, errors = check_row(row(product_name=secret, sku="BAD SKU-SECRET"))
    assert all("SECRET" not in e.message for e in errors)


# ---- file-level row checks -------------------------------------------------------------------
def parsed(*rows: DataRow) -> ParsedFile:
    return ParsedFile(headers=list(VALID), rows=list(rows))


def test_a_sku_repeated_in_the_file_is_refused_on_every_row():
    checked, errors = check_file_rows(
        parsed(row(2), row(3, sku="OTHER"), row(4), row(5, price="bad"))
    )
    assert [r.number for r in checked] == [3]
    duplicate = [e for e in errors if e.field == "sku"]
    assert [e.row for e in duplicate] == [2, 4, 5]
    assert all("rows 2, 4, 5" in e.message for e in duplicate)


def test_rows_of_one_product_that_disagree_are_all_refused_whatever_the_order():
    first = check_file_rows(
        parsed(row(2, sku="A"), row(3, sku="B", product_name="Galaxy S24 Ultra"), row(4, sku="C"))
    )
    second = check_file_rows(
        parsed(row(2, sku="B", product_name="Galaxy S24 Ultra"), row(3, sku="A"), row(4, sku="C"))
    )
    for checked, errors in (first, second):
        assert checked == []
        assert sorted(e.row for e in errors if e.field == "product_name") == [2, 3, 4]


def test_blank_product_columns_do_not_conflict_with_a_given_value():
    checked, errors = check_file_rows(
        parsed(
            row(2, sku="A", description="Flagship", **{"spec:display": "6.1"}),
            row(3, sku="B"),
        )
    )
    assert errors == [] and [r.number for r in checked] == [2, 3]


def test_specification_disagreements_are_reported_per_spec_column():
    _, errors = check_file_rows(
        parsed(
            row(2, sku="A", **{"spec:display": "6.1"}), row(3, sku="B", **{"spec:display": "6.2"})
        )
    )
    assert {(e.row, e.field) for e in errors} == {(2, "spec:display"), (3, "spec:display")}


def test_different_products_may_differ():
    checked, errors = check_file_rows(
        parsed(row(2, sku="A"), row(3, sku="B", product_slug="other", product_name="Other"))
    )
    assert errors == [] and len(checked) == 2
