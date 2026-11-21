"""Staff reports (module 18; PR-13; UAT scenario 7; plan §5 "18 — reports"; §7 Q25).

Approved rules:
- Sales count only paid orders and delivered cash-on-delivery orders (plan §5, UAT scenario 7).
  In this system both are exactly the orders with a 'succeeded' payment attempt: a mobile-money
  payment succeeds through its verified webhook, and a cash-on-delivery attempt succeeds only
  when the order is delivered (§7 Q14; payments:manage confirm-cod covers the same case). A late
  success after the hold lapsed leaves the attempt 'expired' and the order cancelled (ADR-002),
  so it is not a sale. These are also exactly the orders that receive an invoice (§7 Q19).
- Days and weeks are Africa/Kigali calendar days; weeks start on Monday (§7 Q25).
- Amounts are whole RWF: sums of BIGINT columns, cast back to BIGINT; no floating point.
- Stock figures are those of GET /inventory (app.services.inventory.stock_figures).

Engineering defaults, not approved (docs/qa/module-18-reports-acceptance.md, R-1 to R-4):
- R-1 a sale is dated by its first payment success (when it became a sale and was invoiced),
  not by when the order was placed;
- R-2 top products rank by units sold, then revenue, then product name, then product ID, ten
  by default (at most 100);
- R-3 `from` and `to` are inclusive Kigali dates, at most 366 days apart;
- R-4 every day or week of the range is listed, with zeros where nothing sold, and the first
  and last week are cut at the range.

Each order is counted once: the sales subquery has one row per order, however many attempts
succeeded (a duplicate payment is a reconciliation matter, not a second sale). All grouping and
summing happens in the database; only one row per period, product or SKU reaches Python.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import BigInteger, Date, Integer, case, cast, func, select
from sqlalchemy.orm import Session

from app.core.errors import field_error
from app.core.kigali_time import KIGALI, to_kigali
from app.models import OrderItem, Product, ProductVariant
from app.models.commerce import Order, PaymentAttempt
from app.schemas.inventory import InventoryListItem
from app.schemas.reports import (
    TIMEZONE,
    GroupBy,
    SalesFigures,
    SalesPeriod,
    SalesReport,
    StockReport,
    StockTotals,
    TopProduct,
    TopProductsReport,
)
from app.services.inventory_admin import stock_list_query
from app.services.promotion_service import database_now

MAX_RANGE_DAYS = 366
DEFAULT_TOP_PRODUCTS = 10
MAX_TOP_PRODUCTS = 100
FIGURES = ("subtotal", "discount_total", "delivery_fee", "tax_total", "total")


def check_range(from_date: date, to_date: date) -> None:
    """422 (the standard validation error) for a reversed or too long range."""
    if to_date < from_date:
        raise field_error(("query", "to"), "to must be on or after from")
    if (to_date - from_date).days + 1 > MAX_RANGE_DAYS:
        raise field_error(("query", "to"), f"The range can cover at most {MAX_RANGE_DAYS} days")


def kigali_bounds(from_date: date, to_date: date) -> tuple[datetime, datetime]:
    """[start, end) in UTC: from 00:00 Kigali on `from_date` to 00:00 Kigali after `to_date`."""
    start = datetime.combine(from_date, time.min, tzinfo=KIGALI).astimezone(UTC)
    end = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=KIGALI).astimezone(UTC)
    return start, end


def _sales(from_date: date, to_date: date) -> Any:
    """One row per qualifying order (a 'succeeded' payment attempt) with its sale time, the
    first payment success, for the sales dated within the range."""
    start, end = kigali_bounds(from_date, to_date)
    sale_at = func.min(PaymentAttempt.succeeded_at)
    return (
        select(PaymentAttempt.order_id.label("order_id"), sale_at.label("sale_at"))
        .where(PaymentAttempt.status == "succeeded")
        .group_by(PaymentAttempt.order_id)
        .having(sale_at >= start, sale_at < end)
        .subquery("sales")
    )


def _money(column: Any) -> Any:
    return cast(func.coalesce(func.sum(column), 0), BigInteger)


@dataclass(frozen=True)
class _Period:
    key: date  # the bucket the database groups by: the day, or the week's Monday
    start: date
    end: date


def _periods(from_date: date, to_date: date, group_by: GroupBy) -> list[_Period]:
    if group_by == "day":
        days = (to_date - from_date).days + 1
        return [_Period(day, day, day) for day in (from_date + timedelta(n) for n in range(days))]
    periods = []
    monday = from_date - timedelta(days=from_date.weekday())
    while monday <= to_date:
        sunday = monday + timedelta(days=6)
        periods.append(_Period(monday, max(monday, from_date), min(sunday, to_date)))
        monday += timedelta(days=7)
    return periods


def sales(db: Session, from_date: date, to_date: date, group_by: GroupBy) -> SalesReport:
    check_range(from_date, to_date)
    sales_rows = _sales(from_date, to_date)
    local = func.timezone(TIMEZONE, sales_rows.c.sale_at)  # Kigali wall-clock time
    bucket = cast(func.date_trunc(group_by, local), Date)  # date_trunc('week') is a Monday
    query = (
        select(
            bucket.label("bucket"),
            func.count(Order.id).label("orders"),
            *(_money(getattr(Order, name)).label(name) for name in FIGURES),
        )
        .select_from(sales_rows)
        .join(Order, Order.id == sales_rows.c.order_id)
        .group_by(bucket)
    )
    found = {row.bucket: row for row in db.execute(query)}
    periods = []
    for period in _periods(from_date, to_date, group_by):
        row = found.pop(period.key, None)
        figures = {name: int(getattr(row, name)) if row else 0 for name in ("orders", *FIGURES)}
        periods.append(SalesPeriod(period_start=period.start, period_end=period.end, **figures))
    assert not found, "a sale outside the range's periods"
    totals = SalesFigures(
        **{name: sum(getattr(p, name) for p in periods) for name in ("orders", *FIGURES)}
    )
    return SalesReport(
        from_date=from_date, to_date=to_date, group_by=group_by, periods=periods, totals=totals
    )


def top_products(db: Session, from_date: date, to_date: date, limit: int) -> TopProductsReport:
    check_range(from_date, to_date)
    sales_rows = _sales(from_date, to_date)
    # A deleted product leaves product_id NULL on its lines; those group by their name snapshot.
    deleted_name = case((OrderItem.product_id.is_(None), OrderItem.product_name_snapshot))
    name = func.coalesce(func.max(Product.name), func.max(OrderItem.product_name_snapshot))
    units = cast(func.sum(OrderItem.quantity), BigInteger)
    revenue = _money(OrderItem.line_total)
    query = (
        select(
            OrderItem.product_id.label("product_id"),
            name.label("product_name"),
            units.label("units"),
            revenue.label("revenue"),
            func.count(func.distinct(OrderItem.order_id)).label("orders"),
        )
        .select_from(sales_rows)
        .join(OrderItem, OrderItem.order_id == sales_rows.c.order_id)
        .outerjoin(Product, Product.id == OrderItem.product_id)
        .group_by(OrderItem.product_id, deleted_name)
        .order_by(
            units.desc(),
            revenue.desc(),
            name.asc(),
            OrderItem.product_id.asc().nulls_last(),
        )
        .limit(limit)
    )
    items = [
        TopProduct(
            rank=rank,
            product_id=row.product_id,
            product_name=row.product_name,
            units=int(row.units),
            revenue=int(row.revenue),
            orders=int(row.orders),
        )
        for rank, row in enumerate(db.execute(query), start=1)
    ]
    return TopProductsReport(from_date=from_date, to_date=to_date, limit=limit, items=items)


def stock_rows(
    db: Session, *, offset: int = 0, limit: int | None = None
) -> list[InventoryListItem]:
    """Rows of GET /inventory (every SKU, active or not), ordered by SKU."""
    query, _ = stock_list_query()
    query = query.order_by(ProductVariant.sku.asc()).offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return [InventoryListItem.model_validate(dict(row)) for row in db.execute(query).mappings()]


def stock_totals(db: Session) -> StockTotals:
    query, _ = stock_list_query()
    rows = query.subquery("stock")
    total = {
        name: cast(func.coalesce(func.sum(getattr(rows.c, name)), 0), BigInteger).label(name)
        for name in (
            "on_hand",
            "unavailable_quantity",
            "reserved_quantity",
            "committed_quantity",
            "available_quantity",
        )
    }
    row = db.execute(
        select(
            func.count().label("skus"),
            *total.values(),
            cast(func.count().filter(rows.c.is_low_stock), Integer).label("low_stock_skus"),
        )
    ).one()
    return StockTotals(**{key: int(value) for key, value in row._mapping.items()})


def stock(db: Session, page: int, size: int) -> StockReport:
    generated_at = to_kigali(database_now(db))
    assert generated_at is not None
    totals = stock_totals(db)
    items = stock_rows(db, offset=(page - 1) * size, limit=size)
    return StockReport(
        items=items,
        total=totals.skus,
        page=page,
        size=size,
        generated_at=generated_at,
        totals=totals,
    )


def stock_snapshot(db: Session) -> tuple[datetime, list[InventoryListItem], StockTotals]:
    """Every row with totals computed from those same rows, for the export."""
    generated_at = to_kigali(database_now(db))
    assert generated_at is not None
    rows = stock_rows(db)
    totals = StockTotals(
        skus=len(rows),
        on_hand=sum(r.on_hand for r in rows),
        unavailable_quantity=sum(r.unavailable_quantity for r in rows),
        reserved_quantity=sum(r.reserved_quantity for r in rows),
        committed_quantity=sum(r.committed_quantity for r in rows),
        available_quantity=sum(r.available_quantity for r in rows),
        low_stock_skus=sum(1 for r in rows if r.is_low_stock),
    )
    return generated_at, rows, totals
