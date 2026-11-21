"""Read catalogue import files and build templates (module 8). No database access here.

Reading turns an uploaded CSV or XLSX file into header names and data rows of raw cell values.
Problems that make the whole file unusable raise FileProblem with a message safe to show; they
never include file contents or exception text.

Safety:
- CSV must be UTF-8 (a byte-order mark is allowed) and comma-separated; NUL bytes and broken
  quoting are refused.
- XLSX is a zip: its total uncompressed size is checked before parsing (zip bombs), only the
  first worksheet is read, formulas are reported as formulas and never evaluated
  (data_only=False), and external links are not loaded. openpyxl parses XML with the standard
  library (expat), which refuses entity-expansion ("billion laughs") documents.
- Reading stops one row past MAX_IMPORT_ROWS, so an oversized sheet is never read whole.
"""

import csv
import io
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from app.schemas.catalog_import import (
    ATTRIBUTE_PREFIX,
    COLUMNS_BY_NAME,
    DYNAMIC_KEY_MAX_LENGTH,
    IMPORT_COLUMNS,
    MAX_IMPORT_COLUMNS,
    MAX_IMPORT_ROWS,
    SPECIFICATION_PREFIX,
    TEMPLATE_DYNAMIC_COLUMNS,
)

XLSX_MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_CONTENT_TYPE = "text/csv; charset=utf-8"
TEMPLATE_SHEET = "Products"
INSTRUCTIONS_SHEET = "Instructions"
ZIP_MAGIC = b"PK\x03\x04"


class FileProblem(Exception):
    """The file as a whole cannot be imported. `field` names a header when one is at fault."""

    def __init__(self, message: str, *, row: int | None = None, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.row = row
        self.field = field


@dataclass(frozen=True)
class Formula:
    """A spreadsheet formula cell. It is reported as an error, never evaluated."""


FORMULA = Formula()


@dataclass
class DataRow:
    number: int  # spreadsheet row number; the header is row 1
    cells: dict[str, Any]  # header -> raw value (str, int, float, bool, datetime, FORMULA, None)
    extra_values: bool = False  # values to the right of the last header


@dataclass
class ParsedFile:
    headers: list[str]
    rows: list[DataRow] = field(default_factory=list)


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


# ---- headers ---------------------------------------------------------------------------------
def _check_headers(raw: list[Any]) -> list[str]:
    while raw and _blank(raw[-1]):
        raw = raw[:-1]
    if not raw:
        raise FileProblem("The first row must contain the column headers.", row=1)
    if len(raw) > MAX_IMPORT_COLUMNS:
        raise FileProblem(f"The file has more than {MAX_IMPORT_COLUMNS} columns.", row=1)
    headers: list[str] = []
    for position, value in enumerate(raw, start=1):
        if not isinstance(value, str) or _blank(value):
            raise FileProblem(f"Column {position} has no header.", row=1)
        name = value.strip().lower()
        if name in headers:
            raise FileProblem("This header appears more than once.", row=1, field=name)
        if name.startswith((ATTRIBUTE_PREFIX, SPECIFICATION_PREFIX)):
            key = name.split(":", 1)[1].strip()
            if not key or len(key) > DYNAMIC_KEY_MAX_LENGTH or not key.isprintable():
                raise FileProblem(
                    "attr: and spec: headers need a key of 1-60 printable characters.",
                    row=1,
                    field=name,
                )
            name = name.split(":", 1)[0] + ":" + key
        elif name not in COLUMNS_BY_NAME:
            raise FileProblem("Unknown column header.", row=1, field=name)
        headers.append(name)
    missing = [c.name for c in IMPORT_COLUMNS if c.required and c.name not in headers]
    if missing:
        raise FileProblem("Required column is missing.", row=1, field=missing[0])
    return headers


def _data_row(number: int, headers: list[str], values: list[Any]) -> DataRow | None:
    if all(_blank(v) for v in values):
        return None  # blank rows are skipped and not counted
    cells = {h: (values[i] if i < len(values) else None) for i, h in enumerate(headers)}
    extra = any(not _blank(v) for v in values[len(headers) :])
    return DataRow(number=number, cells=cells, extra_values=extra)


def _add_row(parsed: ParsedFile, row: DataRow | None) -> None:
    if row is None:
        return
    if len(parsed.rows) >= MAX_IMPORT_ROWS:
        raise FileProblem(f"The file has more than {MAX_IMPORT_ROWS} data rows.")
    parsed.rows.append(row)


# ---- CSV -------------------------------------------------------------------------------------
def read_csv(data: bytes) -> ParsedFile:
    if data.startswith(ZIP_MAGIC):
        raise FileProblem("The file is not a CSV text file.")
    if b"\x00" in data:
        raise FileProblem("The file contains NUL bytes; save it as UTF-8 CSV.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise FileProblem("The file is not valid UTF-8; save it as 'CSV UTF-8'.") from None
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader, None)
        if header is None:
            raise FileProblem("The file is empty.")
        parsed = ParsedFile(headers=_check_headers(list(header)))
        # Row numbers count records, as a spreadsheet shows them (a quoted cell may span lines).
        for number, values in enumerate(reader, start=2):
            _add_row(parsed, _data_row(number, parsed.headers, list(values)))
    except csv.Error:
        raise FileProblem(
            f"The CSV is malformed near line {reader.line_num} (check quotes and separators)."
        ) from None
    return parsed


# ---- XLSX ------------------------------------------------------------------------------------
def _check_zip(data: bytes) -> None:
    if not data.startswith(ZIP_MAGIC):
        raise FileProblem("The file is not a valid .xlsx workbook.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            total = sum(info.file_size for info in archive.infolist())
    except (zipfile.BadZipFile, OSError, ValueError):
        raise FileProblem("The file is not a valid .xlsx workbook.") from None
    if total > XLSX_MAX_UNCOMPRESSED_BYTES:
        raise FileProblem("The workbook is too large when unpacked.")


def _xlsx_value(cell: Any) -> Any:
    if getattr(cell, "data_type", None) == "f":
        return FORMULA
    return cell.value


def read_xlsx(data: bytes) -> ParsedFile:
    _check_zip(data)
    try:
        workbook = load_workbook(
            io.BytesIO(data), read_only=True, data_only=False, keep_links=False
        )
    except Exception:  # openpyxl raises many types for damaged files; none are shown
        raise FileProblem("The file is not a valid .xlsx workbook.") from None
    try:
        if not workbook.worksheets:
            raise FileProblem("The workbook has no worksheet.")
        sheet = workbook.worksheets[0]
        sheet.reset_dimensions()  # do not trust the size recorded in the file
        rows = sheet.iter_rows()
        try:
            header_cells = next(rows, None)
            if header_cells is None:
                raise FileProblem("The file is empty.")
            parsed = ParsedFile(headers=_check_headers([_xlsx_value(c) for c in header_cells]))
            for number, cells in enumerate(rows, start=2):
                _add_row(parsed, _data_row(number, parsed.headers, [_xlsx_value(c) for c in cells]))
        except FileProblem:
            raise
        except Exception:
            raise FileProblem("The workbook could not be read.") from None
    finally:
        workbook.close()
    return parsed


def is_date_value(value: Any) -> bool:
    return isinstance(value, (datetime, date, time))


# ---- templates -------------------------------------------------------------------------------
def template_headers() -> list[str]:
    return [column.name for column in IMPORT_COLUMNS] + list(TEMPLATE_DYNAMIC_COLUMNS)


def csv_template() -> bytes:
    """Header row only, so importing the untouched template changes nothing."""
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerow(template_headers())
    return ("﻿" + buffer.getvalue()).encode("utf-8")  # BOM: Excel opens it as UTF-8


INSTRUCTIONS = (
    "Fill in the Products sheet: one row per SKU (variant). Only the first sheet is imported.",
    "Row 1 holds the headers; keep them as they are. Columns may be in any order.",
    "An existing SKU is updated; a new SKU is created. Rows with the same product_slug are "
    "variants of one product and must not disagree on product columns.",
    "A blank cell leaves an existing value unchanged (a new SKU or product gets the default). "
    "Values cannot be cleared by import; use the staff screens for that.",
    "category_slug and brand_slug must be slugs of existing categories and brands.",
    "attr:<key> columns set variant attributes (e.g. attr:colour); spec:<key> columns set "
    "product specifications (e.g. spec:display). Add or remove such columns as needed.",
    "Prices and quantities are whole numbers without separators or decimals. Formulas are "
    "refused; text may not start with =, +, @ or - (except '- ' for a list item).",
    "Every row is checked first. Valid rows are imported together; rows with errors are "
    "listed by row number and column and change nothing.",
)


def xlsx_template() -> bytes:
    workbook = Workbook()
    products = workbook.active
    assert products is not None
    products.title = TEMPLATE_SHEET
    products.append(template_headers())
    for cell in products[1]:
        cell.font = Font(bold=True)
    products.freeze_panes = "A2"
    for index, name in enumerate(template_headers(), start=1):
        products.column_dimensions[products.cell(row=1, column=index).column_letter].width = max(
            14, len(name) + 4
        )
    guide = workbook.create_sheet(INSTRUCTIONS_SHEET)
    guide.append(["Column", "Required", "Description"])
    for cell in guide[1]:
        cell.font = Font(bold=True)
    for column in IMPORT_COLUMNS:
        guide.append([column.name, "yes" if column.required else "no", column.description])
    guide.append(["attr:<key>", "no", "Variant attribute, e.g. attr:colour = Black."])
    guide.append(["spec:<key>", "no", "Product specification, e.g. spec:display = 6.1 inch."])
    guide.append([])
    for line in INSTRUCTIONS:
        guide.append([line])
    guide.column_dimensions["A"].width = 22
    guide.column_dimensions["B"].width = 10
    guide.column_dimensions["C"].width = 100
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
