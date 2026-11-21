"""Checkout (module 14; plan §5 "14 — orders & checkout"; RE-026; §7 Q11-Q16, Q21).

One database transaction, in this lock order: the owner's cart (FOR UPDATE), then the stock
balances (create_order_with_reservations), then the promotion row (promotion_service.redeem).
Every step reuses the module that owns the rule:
- Lines are repriced from the database (cart_service pricing, which uses the pricing service);
  a cart with a flagged line, or an empty one, is refused. The request carries no amounts.
- The cart's promotion code is re-quoted on those lines (promotion_service.quote) and, after the
  order row exists, redeemed under the code's row lock (promotion_service.redeem), which
  re-checks the window and the usage limits. A code that no longer applies refuses checkout.
- Delivery comes from the address district (delivery_service.quote_for_district) on the
  subtotal after discount; the delivery fee is never discounted.
- total = subtotal - discount + delivery fee. VAT is extracted from the total at 18%
  (app.core.money, ADR-007); order lines keep tax_amount 0 (§7 Q18, order-level VAT).
- The order, its lines, the first status-history row and the stock holds are written by
  inventory.create_order_with_reservations (all or nothing). The chosen payment method is
  recorded as the order's first payment attempt: cash on delivery 'pending' (due on delivery,
  TC-12), mobile money 'created' (paid through the payments module, 15). Card is not offered
  (§7 Q21). The cart becomes 'converted'.
- Holds (§7 Q11, Q13): mobile money 15 minutes from order creation; cash on delivery 24 hours
  unless staff confirm the order first (which commits the stock). Expired holds cancel the
  order (inventory.expire_due_reservations, §7 Q12).

Idempotency: the Idempotency-Key is scoped to its owner (the customer account, or the guest
cart token's pseudonym), so one owner's key can never replay another's order. The same key with
the same request replays the original order (200, replayed=true) and writes nothing; the same
key with a different request is refused (409 idempotency_key_reused). Concurrent duplicates wait
on the cart lock and then replay. Keys are kept with their order (no expiry is approved).
"""

import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import (
    Conflict,
    NotFound,
    ServiceUnavailable,
    ValidationFailed,
    field_error,
)
from app.core.kigali_time import KIGALI
from app.core.money import VAT_RATE_PERCENT, vat_component
from app.core.request_context import RequestContext
from app.core.security import hash_cart_token
from app.db.transaction import atomic
from app.models import (
    Brand,
    DeliveryZone,
    Order,
    OrderItem,
    PaymentAttempt,
    Product,
    ProductVariant,
)
from app.models.common import MAX_MONEY_RWF
from app.repositories import cart_repository as carts
from app.repositories import delivery_repository, promotion_repository
from app.repositories.address_repository import AddressRepository
from app.schemas.checkout import CheckoutRequest, CheckoutResponse
from app.schemas.order import PaymentMethod
from app.services import promotion_service
from app.services.audit_service import AuditService
from app.services.cart_service import CartOwner, _expiry_enforced, _owned_cart, _price
from app.services.delivery_service import (
    DeliveryQuote,
    DeliveryQuoteUnavailable,
    DeliveryZoneUnavailable,
    quote_for_district,
)
from app.services.inventory import (
    InsufficientStock,
    SkuNotSellable,
    UnknownSku,
    create_order_with_reservations,
)
from app.services.notification_service import record_order_placed
from app.services.order_service import order_detail, reservation_expiry

logger = logging.getLogger("app.checkout")

MOBILE_MONEY = ("mtn_momo", "airtel_money")  # mock provider until ADR-003 (§7 Q21)
CASH_ON_DELIVERY = "cash_on_delivery"
HOLDS: dict[str, timedelta] = {  # §7 Q11 and Q13
    "mtn_momo": timedelta(minutes=15),
    "airtel_money": timedelta(minutes=15),
    CASH_ON_DELIVERY: timedelta(hours=24),
}
ORDER_NUMBER_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O, 1/I: read aloud by phone
ORDER_NUMBER_SUFFIX = 6  # §7 Q16: ORD-YYMMDD-XXXXXX, random, not sequential

NO_CART = "There is no cart to check out."
CART_EMPTY = "The cart is empty."
CART_NEEDS_ATTENTION = "Some cart lines cannot be ordered; update or remove them first."
KEY_REUSED = "This Idempotency-Key was already used for a different checkout."
ADDRESS_NOT_FOUND = "Saved address not found."
GUEST_SAVED_ADDRESS = "Guests use an address typed at checkout (address)."
DELIVERY_UNAVAILABLE = "Delivery is not available in this district."
DELIVERY_NOT_CONFIGURED = "Delivery cannot be quoted right now; try again later."
METHOD_UNAVAILABLE = "This payment method is not available for this delivery zone."
PROMOTION_NOT_APPLICABLE = "The promotion code no longer applies; remove it or try again."
NOT_ENOUGH_STOCK = "Not enough stock is available for a line in the cart."
TOTAL_TOO_LARGE = "The order total is larger than an order can hold."


def available_methods(cod_available: bool) -> list[PaymentMethod]:
    methods: list[PaymentMethod] = ["mtn_momo", "airtel_money"]
    if cod_available:
        methods.append("cash_on_delivery")
    return methods


def new_order_number(db: Session, today: datetime) -> str:
    """§7 Q16: ORD-YYMMDD-XXXXXX, the date in Kigali time and a random suffix. A collision
    (1 in 32^6 per pair on one day) is avoided by checking before use."""
    for _ in range(10):
        suffix = "".join(secrets.choice(ORDER_NUMBER_ALPHABET) for _ in range(ORDER_NUMBER_SUFFIX))
        number = f"ORD-{today.astimezone(KIGALI):%y%m%d}-{suffix}"
        if db.scalar(select(Order.id).where(Order.order_number == number)) is None:
            return number
    raise RuntimeError("could not allocate an order number")  # pragma: no cover


def _scope(owner: CartOwner) -> str:
    if owner.user is not None:
        return f"user:{owner.user.id}"
    if owner.token is None:
        raise NotFound(NO_CART, code="cart_not_found")
    return f"guest:{hash_cart_token(owner.token)[:32]}"


def _order_by_key(db: Session, key: str) -> Order | None:
    return db.scalar(select(Order).where(Order.checkout_idempotency_key == key))


class _Replay(Exception):
    def __init__(self, order: Order) -> None:
        self.order = order


def _replay_response(db: Session, order: Order, fingerprint: str) -> CheckoutResponse:
    if order.checkout_request_hash != fingerprint:
        raise Conflict(KEY_REUSED, code="idempotency_key_reused")
    cod = True
    if order.delivery_zone_id is not None:
        zone = db.get(DeliveryZone, order.delivery_zone_id)
        cod = bool(zone and zone.cod_available)
    return CheckoutResponse(
        order=order_detail(db, order),
        payment_methods_available=available_methods(cod),
        reservation_expires_at=reservation_expiry(db, order.id),
        replayed=True,
    )


def _address(db: Session, owner: CartOwner, req: CheckoutRequest) -> dict[str, Any]:
    """The delivery address snapshot, from a saved address (owned only) or the request."""
    if req.address_id is not None:
        if owner.user is None:
            raise field_error(("body", "address_id"), GUEST_SAVED_ADDRESS)
        saved = AddressRepository.get_by_id_and_user(db, req.address_id, owner.user.id)
        if saved is None:  # another customer's address is not found either
            raise field_error(("body", "address_id"), ADDRESS_NOT_FOUND)
        return {
            "source": "saved",
            "address_id": str(saved.id),
            "recipient_name": saved.recipient_name,
            "phone": saved.phone,
            "province": saved.province,
            "district": saved.district,
            "sector": saved.sector,
            "cell": saved.cell,
            "village": saved.village,
            "street_address": saved.street_address,
            "delivery_instructions": saved.delivery_instructions,
            "country_code": saved.country_code,
        }
    assert req.address is not None
    return {"source": "inline", "country_code": "RW", **req.address.model_dump()}


def _delivery(db: Session, district: str | None, subtotal_after_discount: int) -> DeliveryQuote:
    try:
        return quote_for_district(db, district or "", subtotal_after_discount)
    except DeliveryZoneUnavailable:
        raise ValidationFailed(
            DELIVERY_UNAVAILABLE,
            code="delivery_unavailable",
            details=[
                {
                    "type": "value_error",
                    "loc": ["body", "address", "district"],
                    "msg": DELIVERY_UNAVAILABLE,
                }
            ],
        ) from None
    except DeliveryQuoteUnavailable:
        logger.error("Checkout refused: delivery fee or free-delivery threshold not configured")
        raise ServiceUnavailable(
            DELIVERY_NOT_CONFIGURED, code="delivery_quote_unavailable"
        ) from None


def _not_applicable(reason: str | None) -> ValidationFailed:
    return ValidationFailed(
        PROMOTION_NOT_APPLICABLE,
        code="promotion_not_applicable",
        details=[
            {
                "type": "value_error",
                "loc": ["cart", "discount"],
                "msg": PROMOTION_NOT_APPLICABLE,
                "reason": reason,
            }
        ],
    )


def _snapshots(db: Session, variant_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    rows = db.execute(
        select(ProductVariant, Product, Brand.name)
        .join(Product, Product.id == ProductVariant.product_id)
        .outerjoin(Brand, Brand.id == Product.brand_id)
        .where(ProductVariant.id.in_(variant_ids))
    ).all()
    return {
        variant.id: {
            "product_id": product.id,
            "sku": variant.sku,
            "product_name": product.name,
            "brand_model": " ".join(p for p in (brand_name, product.model) if p) or None,
            "variant": {"name": variant.name, "attributes": variant.attributes},
            "specifications": product.specifications,
            "warranty": product.warranty_text,
        }
        for variant, product, brand_name in rows
    }


class CheckoutService:
    @staticmethod
    def checkout(
        db: Session,
        owner: CartOwner,
        req: CheckoutRequest,
        idempotency_key: str,
        ctx: RequestContext,
    ) -> CheckoutResponse:
        key = f"{_scope(owner)}:{idempotency_key}"
        fingerprint = req.fingerprint()
        existing = _order_by_key(db, key)
        if existing is not None:
            return _replay_response(db, existing, fingerprint)
        user = owner.user
        try:
            with _expiry_enforced(db), atomic(db):
                try:
                    cart = _owned_cart(db, owner, lock=True)
                except NotFound:  # e.g. the guest cart a concurrent duplicate just converted
                    cart = None
                # A duplicate that held the cart lock first has committed by now: replay it.
                existing = _order_by_key(db, key)
                if existing is not None:
                    raise _Replay(existing)
                if cart is None:
                    raise NotFound(NO_CART, code="cart_not_found")
                rows = carts.lines(db, cart.id)
                if not rows:
                    raise Conflict(CART_EMPTY, code="cart_empty")
                status, priced, subtotal = _price(db, rows)
                flagged = [
                    {"variant_id": str(r.variant_id), "status": status[r.variant_id]}
                    for r in rows
                    if status[r.variant_id] != "available"
                ]
                if flagged:
                    raise Conflict(
                        CART_NEEDS_ATTENTION, code="cart_needs_attention", details=flagged
                    )
                address = _address(db, owner, req)
                lines = [(r.variant_id, priced[r.variant_id][1]) for r in rows]

                quote = None
                if cart.discount_id is not None:
                    discount = promotion_repository.get(db, cart.discount_id)
                    if discount is not None:
                        quote = promotion_service.quote(
                            db,
                            discount,
                            lines,
                            user_id=user.id if user else None,
                            phone=address["phone"],
                        )
                        if not quote.applied:
                            raise _not_applicable(quote.reason)
                discount_total = quote.amount if quote else 0
                after_discount = subtotal - discount_total
                delivery = _delivery(db, address.get("district"), after_discount)
                methods = available_methods(delivery.cod_available)
                if req.payment_method not in methods:
                    raise field_error(("body", "payment_method"), METHOD_UNAVAILABLE)
                total = after_discount + delivery.delivery_fee
                if total > MAX_MONEY_RWF:
                    raise field_error(("cart",), TOTAL_TOO_LARGE)
                now = promotion_service.database_now(db)
                address["district"] = delivery.district  # the canonical district name

                order = Order(
                    order_number=new_order_number(db, now),
                    user_id=user.id if user else None,
                    checkout_idempotency_key=key,
                    checkout_request_hash=fingerprint,
                    status="received",
                    subtotal=subtotal,
                    discount_total=discount_total,
                    delivery_fee=delivery.delivery_fee,
                    tax_total=vat_component(total),
                    total=total,
                    tax_treatment="vat_inclusive",
                    tax_snapshot={
                        "rate_percent": VAT_RATE_PERCENT,
                        "basis": "total",
                        "method": "extracted_from_inclusive_total",
                        "rounding": "nearest_half_down",
                    },
                    discount_id=quote.discount.id if quote else None,
                    discount_code_snapshot=quote.discount.code if quote else None,
                    discount_name_snapshot=quote.discount.name if quote else None,
                    discount_rules_snapshot=(
                        {
                            "kind": quote.discount.kind,
                            "percent_off": quote.discount.percent_off,
                            "amount_off": quote.discount.amount_off,
                            "max_discount": quote.discount.max_discount,
                            "min_subtotal": quote.discount.min_subtotal,
                            "applies_to": quote.discount.applies_to,
                            "eligible_subtotal": quote.eligible_subtotal,
                        }
                        if quote
                        else {}
                    ),
                    delivery_zone_id=_zone_id(db, delivery.zone_code),
                    delivery_method_snapshot="zone_flat_fee",
                    delivery_zone_snapshot=delivery.zone_name,
                    recipient_name=address["recipient_name"],
                    recipient_phone=address["phone"],
                    delivery_address_snapshot={
                        **address,
                        "zone_code": delivery.zone_code,
                        "zone_fee": delivery.zone_fee,
                        "free_delivery": delivery.free_delivery,
                        "free_delivery_threshold": delivery.free_delivery_threshold,
                    },
                    customer_email_snapshot=(user.email if user else req.email),
                    customer_note=req.note,
                )
                facts = _snapshots(db, [r.variant_id for r in rows])
                shares = quote.allocations if quote else {}
                for row in rows:
                    unit_price, line_subtotal = priced[row.variant_id]
                    fact = facts[row.variant_id]
                    share = shares.get(row.variant_id, 0)
                    order.items.append(
                        OrderItem(
                            product_id=fact["product_id"],
                            variant_id=row.variant_id,
                            sku_snapshot=fact["sku"],
                            product_name_snapshot=fact["product_name"],
                            brand_model_snapshot=fact["brand_model"],
                            variant_snapshot=fact["variant"],
                            specifications_snapshot=fact["specifications"],
                            warranty_snapshot=fact["warranty"],
                            quantity=row.quantity,
                            unit_price=unit_price,
                            line_subtotal=line_subtotal,
                            discount_amount=share,
                            tax_amount=0,  # §7 Q18: VAT is held at order level
                            line_total=line_subtotal - share,
                        )
                    )
                try:
                    create_order_with_reservations(
                        db,
                        order,
                        expires_at=now + HOLDS[req.payment_method],
                        actor=user,
                        ctx=ctx,
                    )
                except InsufficientStock:
                    raise Conflict(NOT_ENOUGH_STOCK, code="insufficient_stock") from None
                except (SkuNotSellable, UnknownSku):
                    raise Conflict(CART_NEEDS_ATTENTION, code="cart_needs_attention") from None
                if quote is not None:
                    try:
                        promotion_service.redeem(
                            db,
                            discount_id=quote.discount.id,
                            order_id=order.id,
                            user_id=user.id if user else None,
                            customer_phone=address["phone"],
                            amount=discount_total,
                        )
                    except promotion_service.PromotionNotApplicable as exc:
                        raise _not_applicable(exc.reason) from None
                db.add(
                    PaymentAttempt(
                        order_id=order.id,
                        method=req.payment_method,
                        amount=total,
                        status="pending" if req.payment_method == CASH_ON_DELIVERY else "created",
                        idempotency_key=f"checkout:{order.id}",
                    )
                )
                cart.status = "converted"
                db.flush()
                AuditService.log_event(
                    db=db,
                    action="order.checkout",
                    status="success",
                    actor=user,
                    entity_type="order",
                    entity_id=order.id,
                    context=ctx,
                    details={
                        "order_number": order.order_number,
                        "cart_id": str(cart.id),
                        "guest": user is None,
                        "lines": len(rows),
                        "subtotal": subtotal,
                        "discount_total": discount_total,
                        "delivery_fee": delivery.delivery_fee,
                        "tax_total": order.tax_total,
                        "total": total,
                        "payment_method": req.payment_method,
                        "discount_code": order.discount_code_snapshot,
                    },
                )
                record_order_placed(db, order)
        except _Replay as replay:
            return _replay_response(db, replay.order, fingerprint)
        logger.info("Order %s placed (%s)", order.order_number, req.payment_method)
        return CheckoutResponse(
            order=order_detail(db, order),
            payment_methods_available=methods,
            reservation_expires_at=reservation_expiry(db, order.id),
            replayed=False,
        )


def _zone_id(db: Session, code: str) -> uuid.UUID | None:
    zone = delivery_repository.zone_by_code(db, code)
    return zone.id if zone is not None else None
