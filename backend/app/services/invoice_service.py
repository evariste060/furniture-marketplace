"""Invoices and delivery notes (module 16; plan §5 "16 — invoices"; §7 Q19; ADR-007; PR-14).

Issuance (§7 Q19): an invoice is issued when a payment success is recorded (payments, module 15)
or when a cash-on-delivery order is delivered (orders, §7 Q14), inside that same transaction,
after the caller has taken the order's locks in the common order (advisory lock, then the order
row). A payment that needs reconciliation (late, mismatched, unknown, or not yet confirmed) is not
a success and issues nothing. Downloads never issue: they render the stored snapshot.

Numbering (§7 Q19): INV-YYYY-NNNNNN, the year in Kigali time at issuance. The number comes from
invoice_counters, incremented by one upsert (INSERT ... ON CONFLICT DO UPDATE) in the issuing
transaction: the counter row stays locked until that transaction ends, a concurrent first
insert for a new year waits on the primary key, and a rollback undoes the increment together
with the invoice. So, per year, the committed numbers are exactly 1..last_number, each used once.
The lock order is order locks first, then the year's counter row; nothing takes them the other
way round. Unique order_id and invoice_number are the final boundary.

Refusal: when the seller's legal name, TIN or address is missing or invalid, when the order's
stored amounts do not reconcile, or when the year's numbers are used up, no invoice is issued
and no number is used. The payment or delivery is still recorded (an invoice problem must never
undo a payment); the refusal is logged and audited ('invoice.issue', status 'failure'), and the
invoice endpoints answer 409 invoice_not_available until an invoice exists. An administrator
('invoices:recover') then issues it with recover_invoice: same locks, checks and counter, the
current date as issue date, the order and payments unchanged; idempotent. Downloads never issue.

VAT (ADR-007): order-level only, VAT = total × 18 / 118, rounded once to the nearest whole RWF
with an exact half down (app.core.money.vat_component, exact fractions); it must equal the
order's stored tax_total. No EBM claim is made (PR-14).

Delivery notes: generated from the order (number, recipient, delivery address, items; no prices
or payment details), available once all of the order's stock is committed for delivery or
fulfilled (the state the approved workflow requires before dispatch) and the order is not
cancelled. That rule is an engineering reading of the workflow, pending owner approval: no
requirement names the eligible states.
"""

import logging
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound
from app.core.kigali_time import KIGALI
from app.core.money import VAT_RATE_PERCENT, vat_component
from app.core.request_context import RequestContext
from app.db.transaction import atomic
from app.models import Invoice, InvoiceCounter, StockReservation
from app.models.commerce import MAX_INVOICE_SEQUENCE, Order, OrderItem, PaymentAttempt
from app.models.identity import User
from app.services.audit_service import AuditService
from app.services.inventory import lock_order
from app.services.promotion_service import database_now
from app.services.settings_service import seller_details

logger = logging.getLogger("app.invoices")

SNAPSHOT_VERSION = 1
ADDRESS_FIELDS = ("street_address", "village", "cell", "sector", "district", "province")
DELIVERABLE_STATES = {"committed", "fulfilled"}
ORDER_NOT_FOUND = "Order not found."
INVOICE_NOT_AVAILABLE = "No invoice has been issued for this order."
NOTE_NOT_AVAILABLE = (
    "A delivery note is available once the order's stock is committed for delivery."
)

Outcome = Literal["issued", "already_issued", "refused"]


@dataclass(frozen=True)
class IssueResult:
    outcome: Outcome
    invoice: Invoice | None = None
    reason: str | None = None


@dataclass(frozen=True)
class DeliveryNote:
    order_number: str
    recipient: str
    address: list[str]
    lines: list[dict[str, Any]]


def invoice_number(year: int, sequence: int) -> str:
    return f"INV-{year:04d}-{sequence:06d}"


def _address_lines(snapshot: dict[str, Any]) -> list[str]:
    return [str(snapshot[f]) for f in ADDRESS_FIELDS if snapshot.get(f)]


def _description(item: OrderItem) -> str:
    variant = (item.variant_snapshot or {}).get("name")
    name = item.product_name_snapshot
    return f"{name} ({variant})" if variant and variant != name else name


def _items(db: Session, order_id: UUID) -> list[OrderItem]:
    return list(
        db.scalars(
            select(OrderItem)
            .where(OrderItem.order_id == order_id)
            .order_by(OrderItem.created_at, OrderItem.id)
        )
    )


def _amounts_reconcile(order: Order, items: list[OrderItem]) -> bool:
    """The stored order amounts add up (ADR-007) and its VAT is the extracted component."""
    return (
        bool(items)
        and all(i.line_subtotal - i.discount_amount == i.line_total for i in items)
        and sum(i.line_total for i in items) == order.subtotal - order.discount_total
        and order.subtotal - order.discount_total + order.delivery_fee == order.total
        and vat_component(order.total) == order.tax_total
    )


def _next_number(db: Session, year: int) -> int | None:
    """Take the year's next number: one upsert that locks the counter row until the caller's
    transaction ends. None when the year's six-digit range is used up (nothing changes)."""
    return db.scalar(
        insert(InvoiceCounter)
        .values(year=year, last_number=1)
        .on_conflict_do_update(
            index_elements=[InvoiceCounter.year],
            set_={"last_number": InvoiceCounter.last_number + 1},
            where=InvoiceCounter.last_number < MAX_INVOICE_SEQUENCE,
        )
        .returning(InvoiceCounter.last_number)
    )


def _refuse(
    db: Session, order: Order, reason: str, actor: User | None, ctx: RequestContext | None
) -> IssueResult:
    logger.error("Invoice not issued for order %s: %s", order.id, reason)
    AuditService.log_event(
        db,
        action="invoice.issue",
        status="failure",
        actor=actor,
        entity_type="order",
        entity_id=order.id,
        context=ctx,
        details={"reason": reason},
    )
    return IssueResult("refused", reason=reason)


def issue_for_order(
    db: Session,
    order: Order,
    *,
    payment_method: str,
    actor: User | None = None,
    ctx: RequestContext | None = None,
    recovery: bool = False,
) -> IssueResult:
    """Issue the order's invoice, once. Called inside the transaction that records the payment
    success (or the cash-on-delivery delivery), with the order's locks held."""
    existing = db.scalar(select(Invoice).where(Invoice.order_id == order.id))
    if existing is not None:
        return IssueResult("already_issued", invoice=existing)
    seller = seller_details(db)
    if seller is None:
        return _refuse(db, order, "seller_details_missing", actor, ctx)
    items = _items(db, order.id)
    if not _amounts_reconcile(order, items):
        return _refuse(db, order, "order_amounts_inconsistent", actor, ctx)
    issued_at = database_now(db)
    year = issued_at.astimezone(KIGALI).year
    sequence = _next_number(db, year)
    if sequence is None:
        return _refuse(db, order, "invoice_numbers_exhausted", actor, ctx)
    number = invoice_number(year, sequence)
    snapshot = {
        "version": SNAPSHOT_VERSION,
        "invoice_number": number,
        "issued_at": issued_at.isoformat(),
        "issued_on": issued_at.astimezone(KIGALI).date().isoformat(),
        "currency": order.currency_code,
        "seller": seller,
        "customer": {
            "name": order.recipient_name,
            "address": _address_lines(order.delivery_address_snapshot),
        },
        "order": {
            "number": order.order_number,
            "placed_on": order.created_at.astimezone(KIGALI).date().isoformat(),
            "payment_method": payment_method,
        },
        "lines": [
            {
                "sku": i.sku_snapshot,
                "description": _description(i),
                # ADR-014 phase 3: the selling store; the platform remains the issuer.
                "store_name": i.store_name_snapshot,
                "quantity": i.quantity,
                "unit_price": i.unit_price,
                "line_subtotal": i.line_subtotal,
                "discount": i.discount_amount,
                "line_total": i.line_total,
            }
            for i in items
        ],
        "totals": {
            "subtotal": order.subtotal,
            "discount": order.discount_total,
            "discount_code": order.discount_code_snapshot,
            "delivery_fee": order.delivery_fee,
            "total": order.total,
        },
        "vat": {
            "rate_percent": VAT_RATE_PERCENT,
            "amount": order.tax_total,
            "basis": "extracted_from_inclusive_total",
            "rounding": "nearest_whole_rwf_half_down",
        },
    }
    invoice = Invoice(
        order_id=order.id,
        invoice_number=number,
        issued_at=issued_at,
        total=order.total,
        vat_amount=order.tax_total,
        snapshot=snapshot,
    )
    db.add(invoice)
    db.flush()
    AuditService.log_event(
        db,
        action="invoice.issue",
        status="success",
        actor=actor,
        entity_type="order",
        entity_id=order.id,
        context=ctx,
        details={"invoice_id": str(invoice.id), "invoice_number": number, "recovery": recovery},
    )
    logger.info("Invoice %s issued for order %s", number, order.id)
    return IssueResult("issued", invoice=invoice)


# ---- recovery ----------------------------------------------------------------------------------
REFUSALS = {
    "seller_details_missing": "The seller's legal name, TIN and address must be set first.",
    "order_amounts_inconsistent": "The order's stored amounts do not reconcile; no invoice.",
    "invoice_numbers_exhausted": "This year's invoice numbers are used up.",
}
NOT_ISSUABLE = "This order has no confirmed payment, so no invoice can be issued."


def recover_invoice(
    db: Session, order_id: UUID, actor: User, ctx: RequestContext
) -> tuple[Invoice, bool]:
    """Issue the invoice of a paid order that has none (issuance was refused when the payment
    succeeded, e.g. while the seller details were unset). Same locks, counter and checks as
    issue_for_order; the order and its payments are not changed. Idempotent: an order that
    already has an invoice returns it (False) and uses no number. Returns (invoice, issued)."""
    with atomic(db):
        lock_order(db, order_id)
        order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
        if order is None:
            raise NotFound(ORDER_NOT_FOUND, code="order_not_found")
        existing = db.scalar(select(Invoice).where(Invoice.order_id == order.id))
        if existing is not None:
            return existing, False
        paid = db.scalar(
            select(PaymentAttempt)
            .where(PaymentAttempt.order_id == order.id, PaymentAttempt.status == "succeeded")
            .order_by(PaymentAttempt.succeeded_at.desc(), PaymentAttempt.id)
            .limit(1)
        )
        refusal = None
        if paid is None or order.status == "cancelled":
            refusal = "not_paid"
        else:
            result = issue_for_order(
                db, order, payment_method=paid.method, actor=actor, ctx=ctx, recovery=True
            )
            if result.invoice is not None:
                return result.invoice, result.outcome == "issued"
            refusal = result.reason  # audited by issue_for_order; committed with this block
    if refusal == "not_paid":
        AuditService.record_standalone(
            db,
            action="invoice.issue",
            status="conflict",
            actor=actor,
            entity_type="order",
            entity_id=order_id,
            context=ctx,
            details={"reason": "not_paid", "recovery": True},
        )
        raise Conflict(NOT_ISSUABLE, code="invoice_not_issuable")
    assert refusal is not None
    raise Conflict(REFUSALS.get(refusal, INVOICE_NOT_AVAILABLE), code=refusal)


# ---- documents ---------------------------------------------------------------------------------
def _issued(db: Session, order_id: UUID) -> Invoice:
    invoice = db.scalar(select(Invoice).where(Invoice.order_id == order_id))
    if invoice is None:
        raise Conflict(INVOICE_NOT_AVAILABLE, code="invoice_not_available")
    return invoice


def customer_invoice(db: Session, order_id: UUID, user: User) -> Invoice:
    """The invoice of the caller's own order. Another customer's order is the same 404 as a
    missing one; ownership is part of the query."""
    owned = db.scalar(select(Order.id).where(Order.id == order_id, Order.user_id == user.id))
    if owned is None:
        raise NotFound(ORDER_NOT_FOUND, code="order_not_found")
    return _issued(db, order_id)


def staff_invoice(db: Session, order_id: UUID) -> Invoice:
    if db.scalar(select(Order.id).where(Order.id == order_id)) is None:
        raise NotFound(ORDER_NOT_FOUND, code="order_not_found")
    return _issued(db, order_id)


def delivery_note(db: Session, order_id: UUID) -> DeliveryNote:
    order = db.get(Order, order_id)
    if order is None:
        raise NotFound(ORDER_NOT_FOUND, code="order_not_found")
    states = set(
        db.scalars(select(StockReservation.status).where(StockReservation.order_id == order_id))
    )
    if order.status == "cancelled" or not states or not states <= DELIVERABLE_STATES:
        raise Conflict(NOTE_NOT_AVAILABLE, code="delivery_note_unavailable")
    return DeliveryNote(
        order_number=order.order_number,
        recipient=order.recipient_name,
        address=_address_lines(order.delivery_address_snapshot),
        lines=[
            {"sku": i.sku_snapshot, "description": _description(i), "quantity": i.quantity}
            for i in _items(db, order_id)
        ],
    )
