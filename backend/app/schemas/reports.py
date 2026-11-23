"""Staff reports (module 18; PR-13; UAT scenario 7; plan §5 "18 — reports"; §7 Q25).

Amounts are whole RWF (integers). Dates are Africa/Kigali calendar dates; weeks start on Monday.
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.inventory import InventoryListItem
from app.schemas.pagination import Page

GroupBy = Literal["day", "week"]
MarketplaceGroupBy = Literal["day", "week", "month"]
ReportType = Literal["sales", "top-products", "stock"]

TIMEZONE = "Africa/Kigali"


class SalesFigures(BaseModel):
    orders: int = Field(ge=0, description="Qualifying orders")
    subtotal: int = Field(ge=0, description="Merchandise before discounts (RWF)")
    discount_total: int = Field(ge=0, description="Promotion discounts (RWF)")
    delivery_fee: int = Field(ge=0, description="Delivery fees (RWF)")
    tax_total: int = Field(ge=0, description="VAT included in the totals (RWF)")
    total: int = Field(ge=0, description="Order totals: what the customers paid (RWF)")


class SalesPeriod(SalesFigures):
    period_start: date = Field(description="First Kigali day of the period within the range")
    period_end: date = Field(description="Last Kigali day of the period within the range")


class SalesReport(BaseModel):
    from_date: date = Field(serialization_alias="from")
    to_date: date = Field(serialization_alias="to")
    group_by: GroupBy
    timezone: str = TIMEZONE
    periods: list[SalesPeriod] = Field(
        description="Every day or week of the range in order, including those without sales"
    )
    totals: SalesFigures


class TopProduct(BaseModel):
    rank: int = Field(ge=1)
    product_id: UUID | None = Field(description="Null when the product has since been deleted")
    product_name: str
    units: int = Field(ge=0, description="Units sold")
    revenue: int = Field(ge=0, description="Line totals after discounts (RWF)")
    orders: int = Field(ge=0, description="Qualifying orders containing the product")


class TopProductsReport(BaseModel):
    from_date: date = Field(serialization_alias="from")
    to_date: date = Field(serialization_alias="to")
    timezone: str = TIMEZONE
    limit: int
    items: list[TopProduct]


class StockTotals(BaseModel):
    skus: int = Field(ge=0)
    on_hand: int
    unavailable_quantity: int
    reserved_quantity: int
    committed_quantity: int
    available_quantity: int
    low_stock_skus: int = Field(ge=0)


class StockReport(Page[InventoryListItem]):
    """The rows of GET /inventory (one calculation: app.services.inventory.stock_figures)."""

    generated_at: datetime = Field(description="Database time of the figures (Kigali offset)")
    totals: StockTotals = Field(description="Over every SKU, not just this page")


class StoreCounts(BaseModel):
    """Stores by status now (ADR-014)."""

    approved: int = Field(ge=0)
    pending: int = Field(ge=0, description="Applications waiting for a decision")
    rejected: int = Field(ge=0)
    suspended: int = Field(ge=0)


class MarketplaceFigures(BaseModel):
    orders: int = Field(ge=0, description="Qualifying orders (the sales rule)")
    merchandise_total: int = Field(
        ge=0, description="Goods after discounts sold by the stores in those orders (RWF)"
    )
    commission_amount: int = Field(ge=0, description="The platform's commission on them (RWF)")
    new_stores: int = Field(ge=0, description="Stores approved for the first time")
    new_customers: int = Field(
        ge=0, description="Customer accounts registered (store owners included)"
    )


class MarketplacePeriod(MarketplaceFigures):
    period_start: date = Field(description="First Kigali day of the period within the range")
    period_end: date = Field(description="Last Kigali day of the period within the range")


class MarketplaceReport(BaseModel):
    """The marketplace overview (SC-06, ADR-014 phase 7): counts now, and aggregated figures
    per period. No customer, seller or order is identified."""

    from_date: date = Field(serialization_alias="from")
    to_date: date = Field(serialization_alias="to")
    group_by: MarketplaceGroupBy
    timezone: str = TIMEZONE
    stores: StoreCounts
    customers: int = Field(ge=0, description="Active customer accounts now (store owners included)")
    published_products: int = Field(ge=0, description="Products on the storefront now")
    periods: list[MarketplacePeriod] = Field(
        description="Every day, week or month of the range in order, including empty ones"
    )
    totals: MarketplaceFigures
