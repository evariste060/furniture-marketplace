"""Shopping cart (module 11; TC-05). Rules and ownership are in app.services.cart_service.

Who owns the cart:
- With `Authorization: Bearer <session token>` the caller must be a signed-in customer (staff
  accounts get 403 customer_only; a bad token 401). Their one active cart is used, and any
  X-Cart-Token is ignored except by POST /cart/merge.
- Without a bearer token the caller is a guest. The first POST /cart/items creates a guest cart
  and returns its token once (`cart_token`); later requests send it in X-Cart-Token. GET /cart
  without a token returns an empty cart and creates nothing.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.api.v1.responses import ERR, FORBIDDEN_403, UNAUTHORIZED_401, VALIDATION_422, ResponseMap
from app.core.dependencies import get_current_session, get_current_user, security_scheme
from app.core.errors import Forbidden
from app.core.rate_limit import CartRateLimiter, get_cart_rate_limiter
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Role, effective_roles
from app.db.session import get_db
from app.models.identity import User
from app.schemas.cart import (
    CART_TOKEN_PATTERN,
    CartItemAddRequest,
    CartItemUpdateRequest,
    CartMergeResponse,
    CartResponse,
)
from app.schemas.promotions import ApplyCodeRequest
from app.services.cart_service import CartOwner, CartService

router = APIRouter(prefix="/cart", tags=["Cart"])

Db = Annotated[Session, Depends(get_db)]
TOKEN_DESCRIPTION = "Guest cart token from cart_token; omit when signed in as a customer"
CartToken = Annotated[
    str | None,
    Header(alias="X-Cart-Token", pattern=CART_TOKEN_PATTERN, description=TOKEN_DESCRIPTION),
]


def _example(code: str, message: str) -> dict[str, Any]:
    return {"value": {"error": {"code": code, "message": message}}}


def _content(**examples: dict[str, Any]) -> dict[str, Any]:
    return {"content": {"application/json": {"examples": examples}}}


GUARDED: ResponseMap = {
    401: {**UNAUTHORIZED_401[401], "description": "A bearer token was sent but is not valid"},
    403: {
        **FORBIDDEN_403[403],
        "description": "customer_only: staff accounts have no cart; or the account is inactive",
        **_content(staff=_example("customer_only", "Carts are for customer accounts only.")),
    },
}
CART_404: ResponseMap = {
    404: {
        **ERR,
        "description": "cart_not_found: the X-Cart-Token is unknown, expired or already merged",
        **_content(
            unknown=_example(
                "cart_not_found",
                "Cart not found. It may have expired; start a new cart without X-Cart-Token.",
            )
        ),
    }
}
ITEM_404: ResponseMap = {
    404: {
        **ERR,
        "description": "cart_not_found, or cart_item_not_found: no such line in the caller's cart",
        **_content(unknown=_example("cart_item_not_found", "Cart line not found.")),
    }
}
STOCK_409: ResponseMap = {
    409: {
        **ERR,
        "description": "insufficient_stock: more units than are available; "
        "variant_unavailable: the product is no longer sold (remove the line)",
        **_content(
            stock=_example("insufficient_stock", "Not enough stock is available for this quantity.")
        ),
    }
}
RETRY_AFTER = {"Retry-After": {"description": "Seconds to wait", "schema": {"type": "integer"}}}
RATE_429: ResponseMap = {
    429: {
        **ERR,
        "description": "rate_limited: too many new guest carts from this network, or too many "
        "requests for unavailable quantities (lowering or removing a line is never limited)",
        "headers": RETRY_AFTER,
        **_content(
            carts=_example("rate_limited", "Too many new carts from this network; try again later.")
        ),
    }
}
CREATION_503: ResponseMap = {
    503: {
        **ERR,
        "description": "cart_creation_unavailable: a new guest cart cannot be started while the "
        "rate-limit store is unreachable; existing carts keep working",
        **_content(
            store=_example(
                "cart_creation_unavailable",
                "A new cart cannot be started right now; try again shortly.",
            )
        ),
    }
}
ZONE_422: ResponseMap = {
    422: {
        **ERR,
        "description": "validation_error: request failed validation; delivery_zone_unavailable: "
        "`zone` is not an active delivery zone code",
        **_content(
            zone=_example("delivery_zone_unavailable", "Delivery is not available for this zone.")
        ),
    }
}
ZONE_503: ResponseMap = {
    503: {
        **ERR,
        "description": "delivery_quote_unavailable: the zone's fee or the free-delivery "
        "threshold is not configured; omit zone for merchandise totals",
        **_content(
            zone=_example(
                "delivery_quote_unavailable",
                "Delivery cannot be quoted for this zone right now; omit zone to see the "
                "merchandise total.",
            )
        ),
    }
}


def _customer(user: User) -> User:
    """Customers only: any staff-flagged account is refused, even one without a role."""
    if user.is_staff or effective_roles(user) != {Role.CUSTOMER.value}:
        raise Forbidden("Carts are for customer accounts only.", code="customer_only")
    return user


def cart_owner(
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_scheme)],
    db: Db,
    token: CartToken = None,
) -> CartOwner:
    """A signed-in customer when a bearer token is sent (it must be valid), else a guest."""
    if credentials is not None and credentials.credentials:
        user = get_current_user(get_current_session(ctx, credentials, db))
        return CartOwner(user=_customer(user))
    return CartOwner(token=token)


Owner = Annotated[CartOwner, Depends(cart_owner)]
Limiter = Annotated[CartRateLimiter, Depends(get_cart_rate_limiter)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]


@router.get(
    "",
    response_model=CartResponse,
    summary="Read the cart with server-side totals",
    description=(
        "The caller's cart: lines with their status, and the merchandise subtotal of the "
        "available lines from catalogue prices. A guest without X-Cart-Token gets an empty cart "
        "(nothing is created). `zone` (a code from GET /delivery/zones) adds `delivery` and "
        "`grand_total`: delivery is free when the merchandise subtotal is at least the "
        "free-delivery threshold. This is an estimate; checkout derives the zone from the "
        "delivery address district."
    ),
    responses={**GUARDED, **CART_404, **ZONE_422, **ZONE_503},
)
def get_cart(
    owner: Owner,
    db: Db,
    zone: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=60,
            description="Delivery zone code from GET /delivery/zones (module 12)",
        ),
    ] = None,
) -> CartResponse:
    return CartService.get(db, owner, zone)


@router.post(
    "/items",
    response_model=CartResponse,
    summary="Add a product to the cart",
    description=(
        "Adds `quantity` units of a variant; if it is already in the cart the units are added "
        "to that line. A line holds 1 to 99 units and never more than is available (409 "
        "insufficient_stock; nothing is capped). A guest's first call, without X-Cart-Token, "
        "creates the cart and returns `cart_token` once; new guest carts are limited per client "
        "network (429). Repeated requests for unavailable quantities are limited too (429). "
        "Prices are never accepted."
    ),
    responses={
        **GUARDED,
        **CART_404,
        **STOCK_409,
        **VALIDATION_422,
        **RATE_429,
        **CREATION_503,
    },
)
def add_item(
    req: CartItemAddRequest, owner: Owner, db: Db, limiter: Limiter, ctx: Ctx
) -> CartResponse:
    return CartService.add_item(db, owner, req.variant_id, req.quantity, limiter, ctx)


@router.patch(
    "/items/{item_id}",
    response_model=CartResponse,
    summary="Change a line's quantity",
    description="Sets the line to `quantity` units (1 to 99, at most what is available).",
    responses={**GUARDED, **ITEM_404, **STOCK_409, **VALIDATION_422, **RATE_429},
)
def update_item(
    item_id: uuid.UUID,
    req: CartItemUpdateRequest,
    owner: Owner,
    db: Db,
    limiter: Limiter,
    ctx: Ctx,
) -> CartResponse:
    return CartService.update_item(db, owner, item_id, req.quantity, limiter, ctx)


@router.delete(
    "/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Remove a line",
    responses={**GUARDED, **ITEM_404, **VALIDATION_422},
)
def remove_item(item_id: uuid.UUID, owner: Owner, db: Db):
    CartService.remove_item(db, owner, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


CODE_422: ResponseMap = {
    422: {
        **ERR,
        "description": "validation_error; promotion_unavailable: the code is unknown or not "
        "active; promotion_not_applicable: the code does not apply to this cart now (details "
        "has the reason: not_started, expired, no_eligible_items, minimum_not_met, "
        "usage_limit_reached or customer_limit_reached)",
        **_content(
            unknown=_example("promotion_unavailable", "This promotion code is not valid."),
        ),
    }
}
CODE_429: ResponseMap = {
    429: {
        **ERR,
        "description": "rate_limited: too many refused promotion codes from this network or "
        "for this cart (S5); successful applies and removing a code are never limited",
        "headers": RETRY_AFTER,
        **_content(
            codes=_example(
                "rate_limited", "Too many promotion codes were refused; try again later."
            )
        ),
    }
}
NO_CART_404: ResponseMap = {
    404: {
        **ERR,
        "description": "cart_not_found: there is no cart yet, or the X-Cart-Token is unknown, "
        "expired or already merged",
    }
}


@router.post(
    "/apply-code",
    response_model=CartResponse,
    summary="Apply a promotion code to the cart",
    description=(
        "One code per cart: a new code replaces the current one, and repeating the request "
        "changes nothing. Codes are case-insensitive. The discount applies to eligible "
        "merchandise only, never to delivery, and is re-checked on every cart read; nothing is "
        "reserved until checkout. The cart must exist (add a product first). Refused codes "
        "are limited per client network and per cart (429)."
    ),
    responses={**GUARDED, **NO_CART_404, **CODE_422, **CODE_429},
)
def apply_code(
    req: ApplyCodeRequest, owner: Owner, db: Db, limiter: Limiter, ctx: Ctx
) -> CartResponse:
    return CartService.apply_code(db, owner, req.code, limiter, ctx)


@router.delete(
    "/code",
    response_model=CartResponse,
    summary="Remove the promotion code from the cart",
    description="Idempotent: a cart without a code is returned unchanged.",
    responses={**GUARDED, **CART_404, **VALIDATION_422},
)
def remove_code(owner: Owner, db: Db) -> CartResponse:
    return CartService.remove_code(db, owner)


@router.post(
    "/accept-prices",
    response_model=CartResponse,
    summary="Accept the cart's current prices",
    description=(
        "The customer has seen the price changes: every line notes its current price, so no "
        "line reports `previous_unit_price` and `has_price_changes` is false. Display only: "
        "totals and checkout always use the current prices. Idempotent; without a cart the "
        "empty cart is returned."
    ),
    responses={**GUARDED, **CART_404},
)
def accept_prices(owner: Owner, db: Db) -> CartResponse:
    return CartService.accept_prices(db, owner)


@router.post(
    "/merge",
    response_model=CartMergeResponse,
    summary="Merge a guest cart into the customer's cart",
    description=(
        "Signed-in customers only, with the guest cart's X-Cart-Token. Guest quantities are "
        "added to the customer's lines, capped by the 99-unit limit and by available stock; "
        "`merged_lines` reports each line (merged, capped or excluded). The guest cart is then "
        "closed, so repeating the request answers 404 and never adds the units twice."
    ),
    responses={**GUARDED, **CART_404, **VALIDATION_422},
)
def merge_cart(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Db,
    ctx: Ctx,
    token: Annotated[
        str, Header(alias="X-Cart-Token", pattern=CART_TOKEN_PATTERN, description="Guest token")
    ],
) -> CartMergeResponse:
    return CartService.merge(db, _customer(current_user), token, ctx)
