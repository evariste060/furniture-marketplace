"""Checkout (module 14; TC-06, TC-07; RE-026). Rules are in app.services.checkout_service.

The cart owner is resolved as for the cart: a signed-in customer (bearer session) or a guest
(X-Cart-Token). The Idempotency-Key header is required; a retry with the same key and request
replays the original order.
"""

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Response, status
from sqlalchemy.orm import Session

from app.api.v1.endpoints.cart import GUARDED, Owner
from app.api.v1.notifier import Notifier
from app.api.v1.responses import ERR, VALIDATION_422, ResponseMap
from app.core.request_context import RequestContext, get_request_context
from app.db.session import get_db
from app.schemas.checkout import CheckoutRequest, CheckoutResponse
from app.schemas.inventory import IDEMPOTENCY_KEY_PATTERN
from app.services.checkout_service import CheckoutService

router = APIRouter(prefix="/checkout", tags=["Checkout"])

Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]

RESPONSES: ResponseMap = {
    **GUARDED,
    200: {"description": "Replayed: this Idempotency-Key already placed the order"},
    404: {**ERR, "description": "cart_not_found: no cart, or the X-Cart-Token is unknown"},
    409: {
        **ERR,
        "description": "cart_empty; cart_needs_attention (a line is unavailable, short of "
        "stock or out of range; details list them); insufficient_stock (taken by another "
        "order meanwhile); idempotency_key_reused (same key, different request)",
    },
    **VALIDATION_422,
    503: {
        **ERR,
        "description": "delivery_quote_unavailable: the zone fee or free-delivery threshold is "
        "not configured",
    },
}


def _status(response: Response, result: CheckoutResponse) -> CheckoutResponse:
    response.status_code = status.HTTP_200_OK if result.replayed else status.HTTP_201_CREATED
    return result


@router.post(
    "",
    response_model=CheckoutResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Place an order from the cart",
    description=(
        "Turns the caller's cart into an order in one transaction: lines are repriced from the "
        "catalogue, the promotion code is re-checked and its use recorded, delivery is quoted "
        "from the address district (free at the threshold, on the subtotal after discount), "
        "the total is subtotal - discount + delivery, VAT (18%) is extracted from it, and stock "
        "is reserved. The request carries no prices or totals. Customers send a saved "
        "`address_id` or an `address`; guests send an `address`. `payment_method` must be one "
        "of the zone's available methods (card is not offered). The response has the order and "
        "the zone's payment methods. 422 codes: validation_error, delivery_unavailable (the "
        "district is outside the delivery area), promotion_not_applicable (details give the "
        "reason)."
    ),
    responses=RESPONSES,
)
def checkout(
    req: CheckoutRequest,
    owner: Owner,
    db: Db,
    ctx: Ctx,
    response: Response,
    background: BackgroundTasks,
    notifier: Notifier,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            pattern=IDEMPOTENCY_KEY_PATTERN,
            description="8-100 characters: letters, digits, '_', '.', ':' or '-'",
        ),
    ],
) -> Any:
    result = CheckoutService.checkout(db, owner, req, idempotency_key, ctx)
    notifier.schedule(background, db)  # the order confirmation and the staff alert
    return _status(response, result)
