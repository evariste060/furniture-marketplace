"""Shopping cart (module 11; plan §5 and §7 Q10, approved 2026-10-23; RE-026 B7).

Owners: a customer (signed in, no staff role) or a guest holding a cart token. Guests get the
token once, in the response to the request that created their cart; only its SHA-256 is stored
(carts.guest_token_hash). Lookups are scoped to the owner, so another owner's cart or line is
"not found" (404), never "forbidden".

Rules:
- 1 to 99 units per line, and never more than is available now (the stock lifecycle of ADR-002,
  through the shared stock calculation). Adding or updating beyond availability is refused
  (409 insufficient_stock); nothing is capped silently.
- A line whose product is no longer sold is flagged 'unavailable', one asking for more than is
  available 'insufficient_stock', and one whose amount (alone or added to the lines before it)
  would exceed the largest storable amount 'amount_out_of_range'; adding or updating into that
  range is refused (422). Flagged lines stay in the cart but are left out
  of the totals; one bad line never stops the others being priced.
- Totals always come from pricing.quote_merchandise (database prices). Requests carry no prices.
- Merge (customers): guest quantities are added to the customer's lines, capped by the 99-unit
  limit and by availability; each line's outcome is reported. The guest cart then becomes
  'converted' (kept, not deleted), so a repeated merge finds no guest cart (404) and can never
  add the units twice.
- A guest cart expires 30 days after its last change. Expired carts are refused (404) on every
  read and change. They are marked 'abandoned' when next presented; no scheduled job is needed.
- Promotions (module 13): one code per cart (carts.discount_id), applied with
  POST /cart/apply-code and removed with DELETE /cart/code. Every response re-checks the code
  and re-prices the discount from the current lines (app.services.promotion_service), so totals
  can never be stale: a code that stops applying stays on the cart with applied = false and a
  reason, and discounts nothing. Applying a code reserves nothing; uses are recorded at checkout.
- Delivery (module 12): GET /cart?zone=<zone code> adds the delivery quote and the grand total
  (subtotal after discount + delivery fee) from app.services.delivery_service. The
  free-delivery threshold is compared with the subtotal after discount (RE-026 B1); the
  delivery fee itself is never discounted. An unknown or inactive zone is 422
  delivery_zone_unavailable; a zone whose fee or the free-delivery threshold is not configured
  is 503 delivery_quote_unavailable: no fee or total is ever invented.

Audit: a successful merge writes one 'cart.merge' record in the merge's transaction (S4);
other cart changes are not audited (D-C9).
Abuse limits (S1, S3, S5; app.core.rate_limit.CartRateLimiter): guest-cart creation per client
network, repeated 409 insufficient_stock per network and per owner, and refused promotion codes
per network and per owner. Lowering, removing, reading and removing a code are never limited.
"""

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import (
    Conflict,
    NotFound,
    ServiceUnavailable,
    TooManyRequests,
    ValidationFailed,
    field_error,
)
from app.core.rate_limit import CartRateLimiter, RateLimitStoreUnavailable
from app.core.request_context import RequestContext
from app.core.security import generate_cart_token, hash_cart_token
from app.db.transaction import atomic
from app.models import Cart, CartItem, ProductVariant
from app.models.identity import User
from app.repositories import cart_repository as carts
from app.repositories import promotion_repository
from app.repositories.catalog import get_available_quantities
from app.schemas.cart import (
    MAX_LINE_QUANTITY,
    CartDelivery,
    CartDiscount,
    CartLine,
    CartMergeResponse,
    CartResponse,
    MergeLine,
)
from app.services import promotion_service
from app.services.audit_service import AuditService
from app.services.delivery_service import (
    DeliveryQuoteUnavailable,
    DeliveryZoneUnavailable,
    quote_for_zone,
)
from app.services.inventory import (
    InsufficientStock,
    SkuNotSellable,
    UnknownSku,
    sellable_variants,
)
from app.services.line_images import line_images
from app.services.pricing import MAX_AMOUNT, AmountOutOfRange, quote_merchandise

logger = logging.getLogger("app.cart")

CART_NOT_FOUND = "Cart not found. It may have expired; start a new cart without X-Cart-Token."
ITEM_NOT_FOUND = "Cart line not found."
NOT_SOLD = "This product is not available."
LINE_LIMIT = f"A cart line can hold at most {MAX_LINE_QUANTITY} units."
NOT_ENOUGH_STOCK = "Not enough stock is available for this quantity."
AMOUNT_TOO_LARGE = "This quantity would make the cart total larger than an order can hold."
TOO_MANY_CARTS = "Too many new carts from this network; try again later."
TOO_MANY_CODES = "Too many promotion codes were refused; try again later."
CODE_REFUSALS = frozenset({"promotion_unavailable", "promotion_not_applicable"})
TOO_MANY_REFUSALS = (
    "Too many requests for unavailable quantities; try again later or lower the quantity."
)
CREATION_UNAVAILABLE = "A new cart cannot be started right now; try again shortly."
DELIVERY_UNAVAILABLE = (
    "Delivery cannot be quoted for this zone right now; omit zone to see the merchandise total."
)
ZONE_UNAVAILABLE = "Delivery is not available for this zone."
CODE_UNAVAILABLE = "This promotion code is not valid."
CODE_NOT_APPLICABLE = "This promotion code does not apply to this cart right now."
NO_CART = "There is no cart yet; add a product before applying a code."
TOTAL_TOO_LARGE = "The cart total with delivery is larger than an order can hold."


@dataclass(frozen=True)
class CartOwner:
    """Exactly one of user (a customer) or token (a guest's raw cart token, may be None)."""

    user: User | None = None
    token: str | None = None

    @property
    def kind(self) -> str:
        return "customer" if self.user is not None else "guest"


def _cart_not_found() -> NotFound:
    return NotFound(CART_NOT_FOUND, code="cart_not_found")


class _CartExpired(Exception):
    def __init__(self, cart_id: uuid.UUID):
        self.cart_id = cart_id


@contextmanager
def _expiry_enforced(db: Session) -> Iterator[None]:
    """Turn an expired guest cart into 404, after marking it abandoned in its own transaction
    (the request's own transaction has already been rolled back by then)."""
    try:
        yield
    except _CartExpired as expired:
        db.rollback()
        with atomic(db):
            db.execute(
                update(Cart)
                .where(Cart.id == expired.cart_id, Cart.status == "active")
                .values(status="abandoned")
            )
        raise _cart_not_found() from None


def _owned_cart(db: Session, owner: CartOwner, *, lock: bool) -> Cart | None:
    """The owner's usable active cart, or None when there is none yet (no token, or a customer
    who never added anything). An unknown or expired guest token is 404."""
    if owner.user is not None:
        return carts.customer_cart(db, owner.user.id, lock=lock)
    if owner.token is None:
        return None
    cart = carts.guest_cart(db, hash_cart_token(owner.token), lock=lock)
    if cart is None:
        raise _cart_not_found()
    if carts.is_expired(db, cart):
        raise _CartExpired(cart.id)
    return cart


def _check_sold(db: Session, variant_id: uuid.UUID) -> None:
    if not sellable_variants(db, {variant_id}).get(variant_id, False):
        raise field_error(("body", "variant_id"), NOT_SOLD)


def _check_quantity(db: Session, variant_id: uuid.UUID, quantity: int) -> None:
    if quantity > MAX_LINE_QUANTITY:
        raise field_error(("body", "quantity"), LINE_LIMIT)
    if quantity > get_available_quantities(db, [variant_id]).get(variant_id, 0):
        raise Conflict(NOT_ENOUGH_STOCK, code="insufficient_stock")


# ---- reading -------------------------------------------------------------------------------
def build_response(
    db: Session, owner: CartOwner, cart: Cart | None, cart_token: str | None = None
) -> CartResponse:
    if cart is None:
        return CartResponse(
            id=None,
            owner=owner.kind,  # type: ignore[arg-type]
            expires_at=None,
            lines=[],
            item_count=0,
            merchandise_subtotal=0,
            has_unavailable_lines=False,
        )
    rows = carts.lines(db, cart.id)
    status, priced, subtotal = _price(db, rows)
    discount = _discount(db, owner, cart, rows, status, priced)
    shares = discount.allocations if discount is not None and discount.applied else {}
    discount_total = discount.amount if discount is not None else 0
    images = line_images(db, [row.variant_id for row in rows])
    lines = [
        CartLine(
            id=row.id,
            variant_id=row.variant_id,
            product_id=row.product_id,
            sku=row.sku,
            product_name=row.product_name,
            product_slug=row.product_slug,
            variant_name=row.variant_name,
            quantity=row.quantity,
            status=status[row.variant_id],  # type: ignore[arg-type]
            unit_price=priced.get(row.variant_id, (None, None))[0],
            line_subtotal=priced.get(row.variant_id, (None, None))[1],
            discount_amount=(shares.get(row.variant_id, 0) if row.variant_id in priced else None),
            previous_unit_price=_previous_price(row, priced),
            image=images.get(row.variant_id),
        )
        for row in rows
    ]
    return CartResponse(
        id=cart.id,
        owner=owner.kind,  # type: ignore[arg-type]
        expires_at=cart.expires_at,
        lines=lines,
        item_count=sum(r.quantity for r in rows if status[r.variant_id] == "available"),
        merchandise_subtotal=subtotal,
        has_unavailable_lines=any(s != "available" for s in status.values()),
        has_price_changes=any(line.previous_unit_price is not None for line in lines),
        discount=_discount_view(discount),
        discount_total=discount_total,
        subtotal_after_discount=subtotal - discount_total,
        cart_token=cart_token,
    )


def _previous_price(row: carts.LineRow, priced: dict[uuid.UUID, tuple[int, int]]) -> int | None:
    """The price the line was added at, when an available line's price has changed since."""
    if row.price_at_add is None or row.variant_id not in priced:
        return None
    return row.price_at_add if row.price_at_add != priced[row.variant_id][0] else None


def _price(
    db: Session, rows: list[carts.LineRow]
) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, tuple[int, int]], int]:
    """Line statuses, (unit price, line subtotal) of the priced lines, and their subtotal."""
    try:
        status = _line_statuses(db, rows)
        priced, subtotal = _quote(db, rows, status)
    except AmountOutOfRange:
        # A price changed between the amount check and the quote: check once more against the
        # current prices, which flags the line; a second failure is a real error.
        status = _line_statuses(db, rows)
        priced, subtotal = _quote(db, rows, status)
    return status, priced, subtotal


def _discount(
    db: Session,
    owner: CartOwner,
    cart: Cart,
    rows: list[carts.LineRow],
    status: dict[uuid.UUID, str],
    priced: dict[uuid.UUID, tuple[int, int]],
) -> promotion_service.DiscountQuote | None:
    """The cart's code re-checked and re-priced on the priced lines, in cart order."""
    if cart.discount_id is None:
        return None
    discount = promotion_repository.get(db, cart.discount_id)
    if discount is None:
        return None
    lines = [(r.variant_id, priced[r.variant_id][1]) for r in rows if r.variant_id in priced]
    user = owner.user
    return promotion_service.quote(
        db, discount, lines, user_id=user.id if user else None, phone=user.phone if user else None
    )


def _discount_view(quote: promotion_service.DiscountQuote | None) -> CartDiscount | None:
    if quote is None:
        return None
    discount = quote.discount
    return CartDiscount(
        code=discount.code,
        name=discount.name,
        kind=discount.kind,  # type: ignore[arg-type]
        percent_off=discount.percent_off,
        amount_off=discount.amount_off,
        applied=quote.applied,
        reason=quote.reason,  # type: ignore[arg-type]
        amount=quote.amount,
    )


def _line_statuses(db: Session, rows: list[carts.LineRow]) -> dict[uuid.UUID, str]:
    """Status of each line, in cart order: 'unavailable' (not sold), 'insufficient_stock',
    'amount_out_of_range' (its own total, or the running cart total with it, would exceed the
    largest storable amount, pricing.MAX_AMOUNT) or 'available'. Only available lines are
    priced, so the pricing service never receives an unrepresentable cart."""
    variant_ids = {row.variant_id for row in rows}
    sellable = sellable_variants(db, variant_ids)
    available = get_available_quantities(db, list(variant_ids))
    price_query = select(ProductVariant.id, ProductVariant.price).where(
        ProductVariant.id.in_(variant_ids)
    )
    prices: dict[uuid.UUID, int] = {vid: price for vid, price in db.execute(price_query)}
    status: dict[uuid.UUID, str] = {}
    running = 0
    for row in rows:
        if not sellable.get(row.variant_id, False):
            status[row.variant_id] = "unavailable"
        elif row.quantity > available.get(row.variant_id, 0):
            status[row.variant_id] = "insufficient_stock"
        elif running + prices[row.variant_id] * row.quantity > MAX_AMOUNT:
            status[row.variant_id] = "amount_out_of_range"
        else:
            running += prices[row.variant_id] * row.quantity
            status[row.variant_id] = "available"
    return status


def _check_amounts(
    db: Session, cart: Cart, changed: uuid.UUID, before: dict[uuid.UUID, str]
) -> None:
    """Refuse a change that leaves the changed line, or newly any other line, above the
    largest storable amount (422), instead of storing a cart that cannot be priced."""
    db.flush()
    after = _line_statuses(db, carts.lines(db, cart.id))
    newly = [v for v, s in after.items() if s == "amount_out_of_range" and before.get(v) != s]
    if after.get(changed) == "amount_out_of_range" or newly:
        raise field_error(("body", "quantity"), AMOUNT_TOO_LARGE)


def _quote(
    db: Session, rows: list[carts.LineRow], status: dict[uuid.UUID, str]
) -> tuple[dict[uuid.UUID, tuple[int, int]], int]:
    """Price the available lines with the pricing service. If stock or sellability changed
    between the checks and the quote, the affected line is flagged and the rest re-quoted."""
    for _ in range(len(rows) + 1):
        ok = [(r.variant_id, r.quantity) for r in rows if status[r.variant_id] == "available"]
        if not ok:
            return {}, 0
        try:
            quote = quote_merchandise(db, ok)
        except InsufficientStock as exc:
            status[exc.variant_id] = "insufficient_stock"
            continue
        except (SkuNotSellable, UnknownSku) as exc:
            for variant_id in exc.variant_ids:
                status[variant_id] = "unavailable"
            continue
        return {
            line.variant_id: (line.unit_price, line.line_subtotal) for line in quote.lines
        }, quote.merchandise_subtotal
    raise RuntimeError("cart quote did not settle")  # pragma: no cover


def _add_delivery(db: Session, response: CartResponse, zone: str) -> None:
    """Add the zone's delivery quote and the grand total, from database values only."""
    try:
        # B1: the threshold is compared with the subtotal after discount; delivery itself is
        # never discounted.
        quote = quote_for_zone(db, zone, response.subtotal_after_discount)
    except DeliveryZoneUnavailable:
        raise ValidationFailed(
            ZONE_UNAVAILABLE,
            code="delivery_zone_unavailable",
            details=[{"type": "value_error", "loc": ["query", "zone"], "msg": ZONE_UNAVAILABLE}],
        ) from None
    except DeliveryQuoteUnavailable:
        logger.error("Delivery quote refused: zone fee or free-delivery threshold not configured")
        raise ServiceUnavailable(DELIVERY_UNAVAILABLE, code="delivery_quote_unavailable") from None
    grand_total = response.subtotal_after_discount + quote.delivery_fee
    if grand_total > MAX_AMOUNT:
        raise field_error(("query", "zone"), TOTAL_TOO_LARGE)
    response.delivery = CartDelivery(
        zone_code=quote.zone_code,
        zone_name=quote.zone_name,
        district=quote.district,
        cod_available=quote.cod_available,
        zone_fee=quote.zone_fee,
        delivery_fee=quote.delivery_fee,
        free_delivery=quote.free_delivery,
        free_delivery_threshold=quote.free_delivery_threshold,
    )
    response.grand_total = grand_total


# ---- abuse limits (S1, S3) --------------------------------------------------------------------
def _owner_key(owner: CartOwner) -> str | None:
    """Rate-limit key of the cart owner; a pseudonym, never the raw guest token."""
    if owner.user is not None:
        return f"user:{owner.user.id}"
    if owner.token is not None:
        return f"guest:{hash_cart_token(owner.token)[:32]}"
    return None


def _allow_guest_creation(limiter: CartRateLimiter, ctx: RequestContext) -> None:
    try:
        decision = limiter.hit_guest_creation(ctx.ip_address)
    except RateLimitStoreUnavailable:
        logger.error("Guest cart creation refused: the rate-limit store is unavailable")
        raise ServiceUnavailable(CREATION_UNAVAILABLE, code="cart_creation_unavailable") from None
    if not decision.allowed:
        logger.warning("Guest cart creation limit reached for a client network")
        raise TooManyRequests(
            TOO_MANY_CARTS,
            code="rate_limited",
            headers={"Retry-After": str(decision.retry_after)},
        )


def _allow_more_stock(limiter: CartRateLimiter, ctx: RequestContext, owner: CartOwner) -> None:
    decision = limiter.check_stock_probe(ctx.ip_address, _owner_key(owner))
    if not decision.allowed:
        logger.warning("Cart stock-probe limit reached (%s)", decision.scope)
        raise TooManyRequests(
            TOO_MANY_REFUSALS,
            code="rate_limited",
            headers={"Retry-After": str(decision.retry_after)},
        )


def _allow_code_attempt(limiter: CartRateLimiter, ctx: RequestContext, owner: CartOwner) -> None:
    """S5: refuse once refused codes from this network, or for this cart owner, reach the
    limit. The network key is shared by every identity on it, so switching between a guest
    token and a customer session does not reset the count."""
    decision = limiter.check_code_attempt(ctx.ip_address, _owner_key(owner))
    if not decision.allowed:
        logger.warning("Promotion-code limit reached (%s)", decision.scope)
        raise TooManyRequests(
            TOO_MANY_CODES,
            code="rate_limited",
            headers={"Retry-After": str(decision.retry_after)},
        )


@contextmanager
def _code_refusals_counted(
    limiter: CartRateLimiter, ctx: RequestContext, owner: CartOwner
) -> Iterator[None]:
    """Count each refused code (422 promotion_unavailable or promotion_not_applicable) towards
    the S5 limit, then re-raise it. Successful applies are never counted."""
    try:
        yield
    except ValidationFailed as exc:
        if exc.code in CODE_REFUSALS:
            limiter.record_code_refusal(ctx.ip_address, _owner_key(owner))
        raise


@contextmanager
def _stock_refusals_counted(
    limiter: CartRateLimiter, ctx: RequestContext, owner: CartOwner
) -> Iterator[None]:
    """Count each 409 insufficient_stock towards the stock-probe limit, then re-raise it."""
    try:
        yield
    except Conflict as exc:
        if exc.code == "insufficient_stock":
            limiter.record_stock_refusal(ctx.ip_address, _owner_key(owner))
        raise


class CartService:
    @staticmethod
    def get(db: Session, owner: CartOwner, zone: str | None) -> CartResponse:
        with _expiry_enforced(db):
            cart = _owned_cart(db, owner, lock=False)
        response = build_response(db, owner, cart)
        if zone is not None:
            _add_delivery(db, response, zone)
        return response

    @staticmethod
    def add_item(
        db: Session,
        owner: CartOwner,
        variant_id: uuid.UUID,
        quantity: int,
        limiter: CartRateLimiter,
        ctx: RequestContext,
    ) -> CartResponse:
        new_token: str | None = None
        # The probe limit first: a request it refuses must not use up the creation budget.
        _allow_more_stock(limiter, ctx, owner)
        if owner.user is None and owner.token is None:
            _allow_guest_creation(limiter, ctx)
        with _stock_refusals_counted(limiter, ctx, owner), _expiry_enforced(db), atomic(db):
            if owner.user is not None:
                cart = carts.ensure_customer_cart(db, owner.user.id)
            elif owner.token is None:
                new_token = generate_cart_token()
                cart = carts.create_guest_cart(db, hash_cart_token(new_token))
            else:
                found = _owned_cart(db, owner, lock=True)
                assert found is not None
                cart = found
            _check_sold(db, variant_id)
            line = carts.item_for_variant(db, cart.id, variant_id)
            total = quantity + (line.quantity if line else 0)
            _check_quantity(db, variant_id, total)
            before = _line_statuses(db, carts.lines(db, cart.id))
            # The customer sees today's price when adding, so the line notes it (a top-up too).
            price = carts.current_price(db, variant_id)
            if line is None:
                db.add(
                    CartItem(
                        cart_id=cart.id, variant_id=variant_id, quantity=total, price_at_add=price
                    )
                )
            else:
                line.quantity = total
                line.price_at_add = price
            _check_amounts(db, cart, variant_id, before)
            carts.refresh_guest_expiry(db, cart)
        if new_token is not None:
            owner = CartOwner(token=new_token)
        return build_response(db, owner, cart, cart_token=new_token)

    @staticmethod
    def update_item(
        db: Session,
        owner: CartOwner,
        item_id: uuid.UUID,
        quantity: int,
        limiter: CartRateLimiter,
        ctx: RequestContext,
    ) -> CartResponse:
        with _stock_refusals_counted(limiter, ctx, owner), _expiry_enforced(db), atomic(db):
            cart = _owned_cart(db, owner, lock=True)
            line = carts.item(db, cart.id, item_id) if cart is not None else None
            if cart is None or line is None:
                raise NotFound(ITEM_NOT_FOUND, code="cart_item_not_found")
            if quantity > line.quantity:  # lowering a line is never limited
                _allow_more_stock(limiter, ctx, owner)
            if not sellable_variants(db, {line.variant_id}).get(line.variant_id, False):
                raise Conflict(
                    "This product is no longer sold; remove the line.", code="variant_unavailable"
                )
            _check_quantity(db, line.variant_id, quantity)
            before = _line_statuses(db, carts.lines(db, cart.id))
            line.quantity = quantity
            _check_amounts(db, cart, line.variant_id, before)
            carts.refresh_guest_expiry(db, cart)
        return build_response(db, owner, cart)

    @staticmethod
    def remove_item(db: Session, owner: CartOwner, item_id: uuid.UUID) -> None:
        with _expiry_enforced(db), atomic(db):
            cart = _owned_cart(db, owner, lock=True)
            line = carts.item(db, cart.id, item_id) if cart is not None else None
            if cart is None or line is None:
                raise NotFound(ITEM_NOT_FOUND, code="cart_item_not_found")
            carts.delete_item(db, line.id)
            carts.refresh_guest_expiry(db, cart)

    @staticmethod
    def apply_code(
        db: Session,
        owner: CartOwner,
        code: str,
        limiter: CartRateLimiter,
        ctx: RequestContext,
    ) -> CartResponse:
        """Put a code on the cart, replacing any other (one code per cart). Unknown, draft and
        disabled codes are refused alike (422 promotion_unavailable); an active code that does
        not apply to the cart now is refused with its reason (422 promotion_not_applicable).
        Repeating the request with the same code changes nothing. Refused codes count towards
        the S5 limit (429 rate_limited beyond it)."""
        _allow_code_attempt(limiter, ctx, owner)
        with _code_refusals_counted(limiter, ctx, owner), _expiry_enforced(db), atomic(db):
            cart = _owned_cart(db, owner, lock=True)
            if cart is None:
                raise NotFound(NO_CART, code="cart_not_found")
            discount = promotion_service.find_usable_code(db, code)
            if discount is None:
                raise ValidationFailed(
                    CODE_UNAVAILABLE,
                    code="promotion_unavailable",
                    details=[
                        {"type": "value_error", "loc": ["body", "code"], "msg": CODE_UNAVAILABLE}
                    ],
                )
            rows = carts.lines(db, cart.id)
            status, priced, _ = _price(db, rows)
            cart.discount_id = discount.id
            quote = _discount(db, owner, cart, rows, status, priced)
            assert quote is not None
            if not quote.applied:
                raise ValidationFailed(
                    CODE_NOT_APPLICABLE,
                    code="promotion_not_applicable",
                    details=[
                        {
                            "type": "value_error",
                            "loc": ["body", "code"],
                            "msg": CODE_NOT_APPLICABLE,
                            "reason": quote.reason,
                        }
                    ],
                )
            carts.refresh_guest_expiry(db, cart)
        return build_response(db, owner, cart)

    @staticmethod
    def remove_code(db: Session, owner: CartOwner) -> CartResponse:
        """Take the code off the cart. Idempotent: a cart without a code is returned as it is."""
        with _expiry_enforced(db), atomic(db):
            cart = _owned_cart(db, owner, lock=True)
            if cart is not None and cart.discount_id is not None:
                cart.discount_id = None
                carts.refresh_guest_expiry(db, cart)
        return build_response(db, owner, cart)

    @staticmethod
    def accept_prices(db: Session, owner: CartOwner) -> CartResponse:
        """The customer has seen the current prices: every line notes them, so no line reports
        a previous price. Idempotent; a visitor without a cart gets the empty cart."""
        with _expiry_enforced(db), atomic(db):
            cart = _owned_cart(db, owner, lock=True)
            if cart is not None:
                carts.accept_prices(db, cart.id)
                carts.refresh_guest_expiry(db, cart)
        return build_response(db, owner, cart)

    @staticmethod
    def merge(db: Session, customer: User, token: str, ctx: RequestContext) -> CartMergeResponse:
        guest_owner = CartOwner(token=token)
        report: list[MergeLine] = []
        with _expiry_enforced(db), atomic(db):
            guest = _owned_cart(db, guest_owner, lock=True)  # guest first, then customer
            assert guest is not None
            target = carts.ensure_customer_cart(db, customer.id)
            guest_rows = carts.lines(db, guest.id)
            variant_ids = {row.variant_id for row in guest_rows}
            sellable = sellable_variants(db, variant_ids)
            available = get_available_quantities(db, list(variant_ids))
            for row in guest_rows:
                existing = carts.item_for_variant(db, target.id, row.variant_id)
                current = existing.quantity if existing else 0
                if not sellable.get(row.variant_id, False):
                    report.append(_merge_line(row, 0, "excluded", "unavailable"))
                    continue
                limit = min(MAX_LINE_QUANTITY, available.get(row.variant_id, 0))
                wanted = current + row.quantity
                new_quantity = max(current, min(wanted, limit))
                added = new_quantity - current
                if added == row.quantity:
                    report.append(_merge_line(row, added, "merged", None))
                else:
                    # The binding limit: stock when it is below 99 and too low, else the line limit.
                    stock = available.get(row.variant_id, 0)
                    short = wanted > stock and stock < MAX_LINE_QUANTITY
                    reason = "insufficient_stock" if short else "line_limit"
                    report.append(
                        _merge_line(row, added, "capped" if added else "excluded", reason)
                    )
                if added == 0:
                    continue
                if existing is None:
                    db.add(
                        CartItem(
                            cart_id=target.id,
                            variant_id=row.variant_id,
                            quantity=added,
                            price_at_add=row.price_at_add,
                        )
                    )
                else:
                    existing.quantity = new_quantity
            if target.discount_id is None and guest.discount_id is not None:
                target.discount_id = guest.discount_id  # D-P6: the customer's own code wins
            guest.status = "converted"
            db.flush()
            # S4: committed with the merge, so a rolled-back merge leaves no record. IDs and
            # counts only: never the guest token, its hash or any request header.
            AuditService.log_event(
                db=db,
                action="cart.merge",
                status="success",
                actor=customer,
                entity_type="cart",
                entity_id=target.id,
                context=ctx,
                details={
                    "guest_cart_id": guest.id,
                    "guest_lines": len(report),
                    "merged": sum(1 for line in report if line.outcome == "merged"),
                    "capped": sum(1 for line in report if line.outcome == "capped"),
                    "excluded": sum(1 for line in report if line.outcome == "excluded"),
                    "units_added": sum(line.added_quantity for line in report),
                },
            )
        logger.info("Guest cart %s merged into a customer cart", guest.id)
        return CartMergeResponse(
            cart=build_response(db, CartOwner(user=customer), target), merged_lines=report
        )


def _merge_line(row: carts.LineRow, added: int, outcome: str, reason: str | None) -> MergeLine:
    return MergeLine(
        variant_id=row.variant_id,
        sku=row.sku,
        guest_quantity=row.quantity,
        added_quantity=added,
        outcome=outcome,  # type: ignore[arg-type]
        reason=reason,  # type: ignore[arg-type]
    )
