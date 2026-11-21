"""XLSX rendering of the staff reports (module 18; PR-13 "viewed/exported to Excel").

Each workbook has the report sheet (a header row, one row per JSON item in the same order with
the same values, and a totals row where the JSON has totals) and an "About" sheet with the
filters, the time zone and the counting rule, so a file can be checked against its JSON report.

Every text cell is stored as text, never as a formula: product and variant names are staff
input, and a name starting with "=" must not run in the reader's spreadsheet (formula
injection). Amounts are whole RWF integers; dates are date cells.
"""

import io
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from app.schemas.inventory import InventoryListItem
from app.schemas.reports import (
    TIMEZONE,
    SalesReport,
    StockTotals,
    TopProductsReport,
)

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DATE_FORMAT = "yyyy-mm-dd"
SALES_RULE = (
    "Paid orders and delivered cash-on-delivery orders only (orders with a succeeded payment), "
    "dated by their first payment success, in Africa/Kigali days; weeks start on Monday."
)

SALES_HEADERS = (
    "Period start",
    "Period end",
    "Orders",
    "Subtotal (RWF)",
    "Discounts (RWF)",
    "Delivery fees (RWF)",
    "VAT included (RWF)",
    "Total (RWF)",
)
TOP_PRODUCTS_HEADERS = ("Rank", "Product", "Product ID", "Units", "Revenue (RWF)", "Orders")
STOCK_HEADERS = (
    "SKU",
    "Product",
    "Variant",
    "Sellable",
    "On hand",
    "Unavailable",
    "Reserved",
    "Committed",
    "Available",
    "Low-stock threshold",
    "Low stock",
)


def _append(sheet: Worksheet, values: Sequence[Any], *, bold: bool = False) -> None:
    sheet.append(list(values))
    for cell in sheet[sheet.max_row]:
        if isinstance(cell.value, str):
            cell.data_type = "s"  # text, even when it starts with "=" (never a formula)
        elif isinstance(cell.value, (date, datetime)):
            cell.number_format = DATE_FORMAT
        if bold:
            cell.font = Font(bold=True)


def _workbook(
    title: str,
    headers: Sequence[str],
    rows: Iterable[Sequence[Any]],
    totals: Sequence[Any] | None,
    about: Sequence[tuple[str, Any]],
) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = title
    _append(sheet, headers, bold=True)
    sheet.freeze_panes = "A2"
    for row in rows:
        _append(sheet, row)
    if totals is not None:
        _append(sheet, totals, bold=True)
    for index, header in enumerate(headers, start=1):
        letter = sheet.cell(row=1, column=index).column_letter
        sheet.column_dimensions[letter].width = max(12, len(header) + 4)
    info = workbook.create_sheet("About")
    for key, value in about:
        _append(info, (key, value))
    info.column_dimensions["A"].width = 18
    info.column_dimensions["B"].width = 100
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def sales_xlsx(report: SalesReport) -> bytes:
    t = report.totals
    return _workbook(
        "Sales",
        SALES_HEADERS,
        (
            (
                p.period_start,
                p.period_end,
                p.orders,
                p.subtotal,
                p.discount_total,
                p.delivery_fee,
                p.tax_total,
                p.total,
            )
            for p in report.periods
        ),
        (
            "Total",
            None,
            t.orders,
            t.subtotal,
            t.discount_total,
            t.delivery_fee,
            t.tax_total,
            t.total,
        ),
        (
            ("Report", "Sales"),
            ("From", report.from_date),
            ("To", report.to_date),
            ("Grouped by", report.group_by),
            ("Time zone", TIMEZONE),
            ("Counted", SALES_RULE),
        ),
    )


def top_products_xlsx(report: TopProductsReport) -> bytes:
    return _workbook(
        "Top products",
        TOP_PRODUCTS_HEADERS,
        (
            (
                p.rank,
                p.product_name,
                str(p.product_id) if p.product_id else "",
                p.units,
                p.revenue,
                p.orders,
            )
            for p in report.items
        ),
        None,
        (
            ("Report", "Top products"),
            ("From", report.from_date),
            ("To", report.to_date),
            ("Limit", report.limit),
            ("Time zone", TIMEZONE),
            ("Counted", SALES_RULE),
            ("Order", "Units sold, then revenue, then product name."),
        ),
    )


def stock_xlsx(generated_at: datetime, rows: list[InventoryListItem], totals: StockTotals) -> bytes:
    return _workbook(
        "Stock",
        STOCK_HEADERS,
        (
            (
                r.sku,
                r.product_name,
                r.variant_name,
                "yes" if r.is_sellable else "no",
                r.on_hand,
                r.unavailable_quantity,
                r.reserved_quantity,
                r.committed_quantity,
                r.available_quantity,
                r.low_stock_threshold,
                "yes" if r.is_low_stock else "no",
            )
            for r in rows
        ),
        (
            "Total",
            f"{totals.skus} SKUs",
            None,
            None,
            totals.on_hand,
            totals.unavailable_quantity,
            totals.reserved_quantity,
            totals.committed_quantity,
            totals.available_quantity,
            None,
            f"{totals.low_stock_skus} low",
        ),
        (
            ("Report", "Stock"),
            ("Generated at", generated_at.isoformat(timespec="seconds")),
            ("Time zone", TIMEZONE),
            (
                "Figures",
                "As GET /api/v1/inventory: available = on hand - unavailable - reserved - "
                "committed, never below 0.",
            ),
        ),
    )
