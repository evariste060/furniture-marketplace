"""Staff reports (module 18; PR-13; UAT scenario 7; plan §5 "18 — reports"; §7 Q25).

Every endpoint requires reports:read (administrator; plan §3 final
matrix). The XLSX export of a report is built from the same service call as its JSON, with the
same filters, so the two reconcile.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy.orm import Session

from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import FORBIDDEN_403, UNAUTHORIZED_401, VALIDATION_422, ResponseMap
from app.core.dependencies import require_permission
from app.core.errors import field_error
from app.core.roles import Permission
from app.db.session import get_db
from app.models.identity import User
from app.schemas.pagination import DEFAULT_PAGE_SIZE
from app.schemas.reports import (
    GroupBy,
    ReportType,
    SalesReport,
    StockReport,
    TopProductsReport,
)
from app.services import report_service
from app.services.report_xlsx import (
    XLSX_CONTENT_TYPE,
    sales_xlsx,
    stock_xlsx,
    top_products_xlsx,
)

router = APIRouter(prefix="/staff/reports", tags=["Staff Reports"])

GUARDED: ResponseMap = {**UNAUTHORIZED_401, **FORBIDDEN_403}
XLSX_200: ResponseMap = {
    200: {
        "content": {XLSX_CONTENT_TYPE: {"schema": {"type": "string", "format": "binary"}}},
        "description": "The report as an Excel workbook",
    }
}
PERMISSION_NOTE = "Requires 'reports:read' (administrator)."
SALES_RULE = (
    "Counts only paid orders and delivered cash-on-delivery orders (orders with a succeeded "
    "payment; UAT scenario 7), each once, dated by its first payment success. `from` and `to` "
    "are inclusive Africa/Kigali dates (YYYY-MM-DD), at most 366 days apart; weeks start on "
    "Monday (§7 Q25). Amounts are whole RWF."
)

Reader = Annotated[User, Depends(require_permission(Permission.REPORTS_READ))]
Db = Annotated[Session, Depends(get_db)]
FromDate = Annotated[date, Query(alias="from", description="First Kigali day (YYYY-MM-DD)")]
ToDate = Annotated[date, Query(alias="to", description="Last Kigali day, inclusive")]
Limit = Annotated[
    int,
    Query(
        ge=1,
        le=report_service.MAX_TOP_PRODUCTS,
        description=f"Products to list (1-{report_service.MAX_TOP_PRODUCTS})",
    ),
]


@router.get(
    "/sales",
    response_model=SalesReport,
    summary="Sales by day or week",
    description=(
        f"{PERMISSION_NOTE} {SALES_RULE} Every day or week of the range is listed, with zeros "
        "where nothing sold; the first and last week are cut at the range. `totals` is the sum "
        "of the periods."
    ),
    responses={**GUARDED, **VALIDATION_422},
)
def sales_report(
    _: Reader, db: Db, from_date: FromDate, to_date: ToDate, group_by: GroupBy
) -> SalesReport:
    return report_service.sales(db, from_date, to_date, group_by)


@router.get(
    "/top-products",
    response_model=TopProductsReport,
    summary="Top products by units sold",
    description=(
        f"{PERMISSION_NOTE} The products in the sales of the range (same rule: {SALES_RULE}) "
        "ranked by units sold, then revenue (line totals after discounts), then product name. "
        "A product deleted since keeps its lines under the name it was sold with."
    ),
    responses={**GUARDED, **VALIDATION_422},
)
def top_products_report(
    _: Reader,
    db: Db,
    from_date: FromDate,
    to_date: ToDate,
    limit: Limit = report_service.DEFAULT_TOP_PRODUCTS,
) -> TopProductsReport:
    return report_service.top_products(db, from_date, to_date, limit)


@router.get(
    "/stock",
    response_model=StockReport,
    summary="Stock report",
    description=(
        f"{PERMISSION_NOTE} One row per SKU, active or not, ordered by SKU, with the figures of "
        "GET /api/v1/inventory (available = on hand - unavailable - reserved - committed, never "
        "below 0). Paginated; `totals` covers every SKU."
    ),
    responses={**GUARDED, **VALIDATION_422},
)
def stock_report(
    _: Reader, db: Db, page: PageNumber = 1, size: PageSize = DEFAULT_PAGE_SIZE
) -> StockReport:
    return report_service.stock(db, page, size)


@router.get(
    "/{report_type}/export",
    response_class=Response,
    summary="Export a report to Excel (XLSX)",
    description=(
        f"{PERMISSION_NOTE} `report_type` is `sales`, `top-products` or `stock`; the query "
        "parameters are those of the JSON report (`from`, `to` and `group_by` for sales; "
        "`from`, `to` and `limit` for top products; none for stock, which exports every SKU). "
        "The rows and totals are those of the JSON report with the same parameters."
    ),
    responses={**XLSX_200, **GUARDED, **VALIDATION_422},
)
def export_report(
    _: Reader,
    db: Db,
    report_type: Annotated[ReportType, Path(description="sales, top-products or stock")],
    from_date: Annotated[
        date | None, Query(alias="from", description="Sales, top products")
    ] = None,
    to_date: Annotated[date | None, Query(alias="to", description="Sales, top products")] = None,
    group_by: Annotated[GroupBy | None, Query(description="Sales: day or week")] = None,
    limit: Limit = report_service.DEFAULT_TOP_PRODUCTS,
) -> Response:
    if report_type == "stock":
        generated_at, rows, totals = report_service.stock_snapshot(db)
        stamp = generated_at.strftime("%Y%m%d-%H%M")
        return _xlsx(stock_xlsx(generated_at, rows, totals), f"stock-{stamp}.xlsx")
    if from_date is None:
        raise field_error(("query", "from"), "Field required")
    if to_date is None:
        raise field_error(("query", "to"), "Field required")
    span = f"{from_date.isoformat()}-to-{to_date.isoformat()}"
    if report_type == "sales":
        if group_by is None:
            raise field_error(("query", "group_by"), "Field required")
        report = report_service.sales(db, from_date, to_date, group_by)
        return _xlsx(sales_xlsx(report), f"sales-{span}-by-{group_by}.xlsx")
    top = report_service.top_products(db, from_date, to_date, limit)
    return _xlsx(top_products_xlsx(top), f"top-products-{span}.xlsx")


def _xlsx(content: bytes, filename: str) -> Response:
    """filename is built from fixed words, ISO dates and digits only."""
    return Response(
        content=content,
        media_type=XLSX_CONTENT_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
