"""Reading catalogue import files and building templates (module 8; no database)."""

import csv
import io
import zipfile

import pytest
from openpyxl import Workbook, load_workbook

from app.schemas.catalog_import import IMPORT_COLUMNS, MAX_IMPORT_ROWS, REQUIRED_COLUMNS
from app.services import import_files
from app.services.import_files import (
    FORMULA,
    INSTRUCTIONS_SHEET,
    TEMPLATE_SHEET,
    FileProblem,
    csv_template,
    read_csv,
    read_xlsx,
    template_headers,
    xlsx_template,
)

HEADERS = list(REQUIRED_COLUMNS)


def csv_bytes(rows: list[list[str]], bom: bool = False) -> bytes:
    buffer = io.StringIO(newline="")
    csv.writer(buffer).writerows(rows)
    return (("﻿" if bom else "") + buffer.getvalue()).encode("utf-8")


def xlsx_bytes(rows: list[list[object]], extra_sheet: bool = False) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    if extra_sheet:
        workbook.create_sheet("Notes").append(["sku", "ignored"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def problem(fn, data: bytes) -> FileProblem:
    with pytest.raises(FileProblem) as caught:
        fn(data)
    return caught.value


# ---- CSV -------------------------------------------------------------------------------------
def test_csv_rows_keep_spreadsheet_numbers_and_skip_blank_rows():
    data = csv_bytes([HEADERS, ["A-1"] + [""] * 5, ["", "", "", "", "", ""], ["A-2"] + [""] * 5])
    parsed = read_csv(data)
    assert parsed.headers == HEADERS
    assert [row.number for row in parsed.rows] == [2, 4]
    assert parsed.rows[0].cells["sku"] == "A-1"


def test_csv_header_names_are_trimmed_case_folded_and_may_be_reordered():
    headers = [" Price ", "SKU", "variant_name", "category_slug", "product_name", "Product_Slug"]
    parsed = read_csv(csv_bytes([headers, ["1", "A", "B", "c", "D", "e"]]))
    assert parsed.headers == [
        "price",
        "sku",
        "variant_name",
        "category_slug",
        "product_name",
        "product_slug",
    ]
    assert parsed.rows[0].cells["price"] == "1"


def test_csv_with_a_byte_order_mark_and_multiline_cells_is_read():
    parsed = read_csv(csv_bytes([HEADERS, ["A", "", "", "", "line one\nline two", ""]], bom=True))
    assert parsed.headers[0] == "sku"
    assert parsed.rows[0].number == 2
    assert parsed.rows[0].cells["variant_name"] == "line one\nline two"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "empty"),
        ("sku,naïve".encode("latin-1"), "UTF-8"),
        (b"sku,price\x00\n", "NUL"),
        (b'sku,product_slug,product_name,category_slug,variant_name,price\n"open', "malformed"),
        (b"PK\x03\x04rest", "not a CSV"),
    ],
    ids=["empty", "latin-1", "nul", "broken-quote", "zip"],
)
def test_unusable_csv_files_are_refused_without_showing_contents(data, message):
    found = problem(read_csv, data)
    assert message in found.message


@pytest.mark.parametrize(
    ("headers", "field", "message"),
    [
        (HEADERS + ["colour"], "colour", "Unknown column"),
        (HEADERS + ["sku"], "sku", "more than once"),
        (HEADERS[:-1], "price", "Required column"),
        (HEADERS[:2] + [""] + HEADERS[2:], None, "Column 3 has no header"),
        (HEADERS + ["attr:"], "attr:", "key"),
    ],
    ids=["unknown", "duplicate", "missing-required", "blank-in-middle", "empty-key"],
)
def test_bad_headers_fail_the_file_and_name_the_header(headers, field, message):
    found = problem(read_csv, csv_bytes([headers, ["x"] * len(headers)]))
    assert message in found.message and found.row == 1 and found.field == field


def test_trailing_blank_headers_are_ignored_but_values_beyond_them_are_flagged():
    parsed = read_csv(csv_bytes([HEADERS + ["", ""], ["A", "", "", "", "", "", "", "stray"]]))
    assert parsed.headers == HEADERS
    assert parsed.rows[0].extra_values is True


def test_dynamic_columns_are_accepted_with_their_key():
    parsed = read_csv(csv_bytes([HEADERS + ["attr: Colour", "spec:Display"], ["A"] * 8]))
    assert parsed.headers[-2:] == ["attr:colour", "spec:display"]


def test_more_than_the_row_limit_is_refused_while_reading(monkeypatch):
    monkeypatch.setattr(import_files, "MAX_IMPORT_ROWS", 3)
    ok = read_csv(csv_bytes([HEADERS] + [[f"S{i}"] for i in range(3)]))
    assert len(ok.rows) == 3
    found = problem(read_csv, csv_bytes([HEADERS] + [[f"S{i}"] for i in range(4)]))
    assert "more than 3 data rows" in found.message


def test_the_real_row_limit_is_5000():
    assert MAX_IMPORT_ROWS == 5000
    rows = [HEADERS] + [[f"S{i}", "p", "n", "c", "v", "1"] for i in range(MAX_IMPORT_ROWS)]
    assert len(read_csv(csv_bytes(rows)).rows) == MAX_IMPORT_ROWS
    over = rows + [["S-extra", "p", "n", "c", "v", "1"]]
    assert "more than 5000" in problem(read_csv, csv_bytes(over)).message


# ---- XLSX ------------------------------------------------------------------------------------
def test_xlsx_reads_the_first_sheet_with_native_types_and_row_numbers():
    data = xlsx_bytes(
        [
            HEADERS,
            ["A", "p", "Phone", "phones", "Black", 1500],
            [None] * 6,
            ["B", "p", 7, "c", "v", 2.0],
        ],
        extra_sheet=True,
    )
    parsed = read_xlsx(data)
    assert [row.number for row in parsed.rows] == [2, 4]
    assert parsed.rows[0].cells["price"] == 1500
    assert parsed.rows[1].cells["product_name"] == 7
    assert parsed.rows[1].cells["price"] == 2.0


def test_xlsx_formulas_are_marked_and_never_evaluated():
    parsed = read_xlsx(xlsx_bytes([HEADERS, ["A", "p", "=1+1", "c", "v", "=SUM(1,2)"]]))
    assert parsed.rows[0].cells["product_name"] is FORMULA
    assert parsed.rows[0].cells["price"] is FORMULA


def test_a_formula_header_is_refused():
    found = problem(read_xlsx, xlsx_bytes([["=A2"] + HEADERS[1:], ["x"] * 6]))
    assert "no header" in found.message


@pytest.mark.parametrize(
    "data",
    [b"not a zip at all", b"PK\x03\x04truncated", b""],
    ids=["text", "truncated-zip", "empty"],
)
def test_damaged_workbooks_are_refused(data):
    assert "not a valid .xlsx" in problem(read_xlsx, data).message


def test_a_zip_that_is_not_a_workbook_is_refused():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "hi")
    assert "not a valid .xlsx" in problem(read_xlsx, buffer.getvalue()).message


def test_a_workbook_that_unpacks_too_large_is_refused_before_parsing(monkeypatch):
    monkeypatch.setattr(import_files, "XLSX_MAX_UNCOMPRESSED_BYTES", 1000)
    data = xlsx_bytes([HEADERS, ["A"] * 6])
    assert "too large when unpacked" in problem(read_xlsx, data).message


def test_an_empty_first_sheet_is_refused():
    assert "empty" in problem(read_xlsx, xlsx_bytes([])).message


def test_xlsx_row_limit(monkeypatch):
    monkeypatch.setattr(import_files, "MAX_IMPORT_ROWS", 2)
    data = xlsx_bytes([HEADERS, ["A"], ["B"], ["C"]])
    assert "more than 2 data rows" in problem(read_xlsx, data).message


# ---- templates -------------------------------------------------------------------------------
def test_both_templates_have_the_same_headers_and_no_data_rows():
    headers = template_headers()
    assert headers[: len(IMPORT_COLUMNS)] == [c.name for c in IMPORT_COLUMNS]
    from_csv = read_csv(csv_template())
    from_xlsx = read_xlsx(xlsx_template())
    assert from_csv.headers == from_xlsx.headers == headers
    assert from_csv.rows == [] and from_xlsx.rows == []


def test_the_csv_template_has_a_bom_and_crlf_line_end():
    data = csv_template()
    assert data.startswith("﻿".encode()) and data.endswith(b"\r\n")
    assert data.count(b"\r\n") == 1


def test_the_xlsx_template_has_a_products_sheet_first_and_instructions():
    workbook = load_workbook(io.BytesIO(xlsx_template()))
    assert workbook.sheetnames == [TEMPLATE_SHEET, INSTRUCTIONS_SHEET]
    guide = workbook[INSTRUCTIONS_SHEET]
    described = {row[0] for row in guide.iter_rows(min_row=2, values_only=True) if row[0]}
    assert {c.name for c in IMPORT_COLUMNS} <= described
    for row in guide.iter_rows(values_only=True):
        for value in row:
            assert not (isinstance(value, str) and value.startswith("=")), value
