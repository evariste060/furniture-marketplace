"""Staff inventory endpoints (ADR-002 stock lifecycle, approved 2026-10-22).

- inventory:read (held by no role in V1, SC-06): the stock list with its low-stock filter
  (module 10) and stock figures for one SKU; both use one calculation
- inventory:adjust (held by no role in V1, SC-06): receipts, adjustments and inspected returns

Reservation commit, release and expiry are internal operations for the future checkout and
payment services and the expiry job (scripts/expire_reservations.py). They are deliberately not
exposed over HTTP.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import ERR, FORBIDDEN_403, UNAUTHORIZED_401, VALIDATION_422, ResponseMap
from app.core.dependencies import require_permission
from app.core.errors import field_error
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Permission
from app.db.session import get_db
from app.models.identity import User
from app.schemas.inventory import (
    IDEMPOTENCY_KEY_PATTERN,
    InventoryListItem,
    InventoryResponse,
    StockAdjustmentRequest,
    StockAdjustmentResponse,
)
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page
from app.services.catalog_scope import CatalogScope
from app.services.inventory_admin import InventoryAdminService

router = APIRouter(prefix="/inventory", tags=["Inventory"])
PLATFORM = CatalogScope.platform()  # staff see every store's stock (ADR-014 phase 2)

GUARDED: ResponseMap = {**UNAUTHORIZED_401, **FORBIDDEN_403}
SKU_404: ResponseMap = {404: {**ERR, "description": "No SKU with this code"}}
ADJUST_409: ResponseMap = {
    409: {
        **ERR,
        "description": "Insufficient stock (the change would go below reserved, committed or "
        "unavailable units), or the Idempotency-Key was already used for a different change",
    }
}

Reader = Annotated[User, Depends(require_permission(Permission.INVENTORY_READ))]
Adjuster = Annotated[User, Depends(require_permission(Permission.INVENTORY_ADJUST))]
Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]
Sku = Annotated[str, Path(min_length=1, max_length=80, description="Exact SKU code")]


@router.get(
    "",
    response_model=Page[InventoryListItem],
    summary="Stock list, with the low-stock filter",
    description=(
        "Requires 'inventory:read' (held by no role in V1, SC-06). One row "
        "per SKU, active or not, ordered by SKU, with the same figures as GET /inventory/{sku}. "
        "`low_stock=true` lists SKUs whose available quantity is at or below their "
        "low_stock_threshold (threshold above 0): this is the low-stock alert. "
        "`low_stock=false` lists the others; omit it for all. `q` matches a case-insensitive "
        "substring of the SKU, variant name or product name."
    ),
    responses={**GUARDED, **VALIDATION_422},
)
def list_inventory(
    current_user: Reader,
    db: Db,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
    low_stock: Annotated[
        bool | None, Query(description="true: low stock only; false: not low stock")
    ] = None,
    q: Annotated[
        str | None,
        Query(min_length=1, max_length=160, description="Substring of SKU or product/variant name"),
    ] = None,
) -> Page[InventoryListItem]:
    if q is not None:
        q = q.strip()
        if not q:
            raise field_error(("query", "q"), "q must contain non-whitespace characters")
    items, total = InventoryAdminService.list_stock(
        db, low_stock=low_stock, q=q, page=page, size=size, scope=PLATFORM
    )
    return Page[InventoryListItem](items=items, total=total, page=page, size=size)


@router.get(
    "/{sku}",
    response_model=InventoryResponse,
    summary="Stock figures for a SKU",
    description=(
        "Returns physical, unavailable, reserved (active), committed and available quantities "
        "read from PostgreSQL. A SKU without an inventory record reports zeros. "
        "Requires 'inventory:read' (held by no role in V1, SC-06)."
    ),
    responses={**GUARDED, **SKU_404, **VALIDATION_422},
)
def get_inventory(sku: Sku, current_user: Reader, db: Db) -> InventoryResponse:
    return InventoryAdminService.get(db, sku, scope=PLATFORM)


@router.post(
    "/{sku}/adjustments",
    response_model=StockAdjustmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a physical stock change",
    description=(
        "Applies a receipt, adjustment or inspected return to physical on_hand and appends a "
        "stock-ledger movement, in one transaction with an 'inventory.adjust' audit record. "
        "Requires 'inventory:adjust' (held by no role in V1, SC-06).\n\n"
        "**Idempotency:** the `Idempotency-Key` header is required (8-100 characters: letters, "
        "digits, `_ . : -`). Repeating a request with the same key returns the original "
        "movement with HTTP 200 and `replayed: true`, without changing stock again. Reusing a "
        "key for a different change returns 409. Keys are scoped to the calling staff member.\n\n"
        "**Stock rules:** stock can never go below the units that are reserved, committed or "
        "unavailable; such a change returns 409 and nothing is applied."
    ),
    responses={
        200: {"model": StockAdjustmentResponse, "description": "Replay of an applied key"},
        **GUARDED,
        **SKU_404,
        **ADJUST_409,
        **VALIDATION_422,
    },
)
def adjust_inventory(
    sku: Sku,
    req: StockAdjustmentRequest,
    response: Response,
    current_user: Adjuster,
    db: Db,
    ctx: Ctx,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            pattern=IDEMPOTENCY_KEY_PATTERN,
            description="Unique key per intended change; reuse it only to retry that change",
        ),
    ],
) -> StockAdjustmentResponse:
    result = InventoryAdminService.adjust(
        db, current_user, sku, req, idempotency_key, ctx, scope=PLATFORM
    )
    if result.replayed:
        response.status_code = status.HTTP_200_OK
    return result
