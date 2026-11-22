"""Disposable catalogue and order rows for inventory tests (never real business data)."""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.models import (
    Brand,
    Category,
    InventoryBalance,
    Order,
    OrderItem,
    Product,
    ProductVariant,
    StockReservation,
)
from app.models.marketplace import Store
from app.models.operations import AuditRecord
from app.services import inventory
from app.services.seller_order_service import build_seller_orders
from tests.support.sellers import new_store

NEEDS_STORES = "_test_needs_stores"


def needs_stores(order: Order) -> Order:
    """Mark a hand-built test order: on its first flush each line gets its product's store and
    the order gets its seller orders, as checkout does (ADR-014 phase 3). Unmarked orders, and
    every order checkout creates, are never touched."""
    setattr(order, NEEDS_STORES, True)
    return order


@event.listens_for(Session, "before_flush")
def _attach_seller_orders(session: Session, flush_context, instances) -> None:  # noqa: ANN001
    for obj in list(session.new):
        if not isinstance(obj, Order) or not getattr(obj, NEEDS_STORES, False):
            continue
        setattr(obj, NEEDS_STORES, False)
        with session.no_autoflush:
            for item in obj.items:
                if item.store_id is None and item.variant_id is not None:
                    row = session.execute(
                        select(Store.id, Store.name)
                        .join(Product, Product.store_id == Store.id)
                        .join(ProductVariant, ProductVariant.product_id == Product.id)
                        .where(ProductVariant.id == item.variant_id)
                    ).one()
                    item.store_id, item.store_name_snapshot = row
            if obj.items and not obj.seller_orders:
                build_seller_orders(session, obj)


def seed_sku(session: Session, *, on_hand: int | None = 1, **variant_overrides) -> ProductVariant:
    """One sellable test SKU; on_hand=None creates no inventory record."""
    tag = uuid4().hex[:12]
    product = Product(
        store=new_store(),
        name=f"Test phone {tag}",
        slug=f"test-phone-{tag}",
        category=Category(name=f"Test category {tag}", slug=f"test-cat-{tag}"),
        brand=Brand(name=f"Test brand {tag}", slug=f"test-brand-{tag}"),
        specifications={},
        status="active",
    )
    variant = ProductVariant(
        product=product,
        sku=f"TEST-{tag}",
        name="Test variant",
        price=1000,
        **variant_overrides,
    )
    if on_hand is not None:
        variant.inventory = InventoryBalance(on_hand=on_hand, unavailable_quantity=0)
    session.add(product)
    session.flush()
    return variant


def new_order(lines: dict[UUID, int], *, key: str | None = None, user_id=None) -> Order:
    order = Order(
        order_number=f"TEST-{uuid4().hex[:16]}",
        checkout_idempotency_key=key or f"checkout-{uuid4().hex}",
        user_id=user_id,
        subtotal=0,
        total=0,
        recipient_name="Test Recipient",
        recipient_phone="+250780000000",
        delivery_address_snapshot={"district": "Test"},
    )
    for variant_id, quantity in lines.items():
        order.items.append(
            OrderItem(
                variant_id=variant_id,
                sku_snapshot="TEST",
                product_name_snapshot="Test product",
                quantity=quantity,
                unit_price=0,
                line_subtotal=0,
                line_total=0,
            )
        )
    return needs_stores(order)


def soon(seconds: float = 600) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=seconds)


def wait_until_due(seconds: float = 1.2) -> None:
    """Holds are created with a short expiry and then become due in database time."""
    time.sleep(seconds)


def hold_expiry(session: Session, order_id: UUID) -> datetime | None:
    """When the order's active stock holds expire (database time); None if none is active."""
    return session.scalar(
        select(func.max(StockReservation.expires_at)).where(
            StockReservation.order_id == order_id, StockReservation.status == "active"
        )
    )


@contextmanager
def stock_clock_at(monkeypatch: pytest.MonkeyPatch, instant: datetime) -> Iterator[None]:
    """Inside the block the stock services (inventory._db_now, the database clock) read
    `instant`, or the real time if that is later. Holds are immutable apart from their status,
    so a test makes a normal hold due by moving this clock to its expiry, not by editing the row
    or waiting for a short hold: nothing depends on how long the steps before took."""
    database_clock = inventory._db_now
    with monkeypatch.context() as patch:
        patch.setattr(inventory, "_db_now", lambda session: max(database_clock(session), instant))
        yield


def statuses(session: Session, order_id: UUID) -> list[str]:
    session.expire_all()
    return sorted(
        session.scalars(
            select(StockReservation.status).where(StockReservation.order_id == order_id)
        )
    )


def allocated(session: Session, variant_id: UUID) -> int:
    session.expire_all()
    return int(
        session.execute(
            select(func.coalesce(func.sum(StockReservation.quantity), 0)).where(
                StockReservation.variant_id == variant_id,
                StockReservation.status.in_(("active", "committed")),
            )
        ).scalar_one()
    )


def on_hand(session: Session, variant_id: UUID) -> int | None:
    """Physical stock, or None when the SKU has no inventory record."""
    session.expire_all()
    return session.scalar(
        select(InventoryBalance.on_hand).where(InventoryBalance.variant_id == variant_id)
    )


def audit_count(session: Session, action: str, entity_id: UUID | None = None) -> int:
    stmt = select(func.count(AuditRecord.id)).where(AuditRecord.action == action)
    if entity_id is not None:
        stmt = stmt.where(AuditRecord.entity_id == str(entity_id))
    return session.execute(stmt).scalar_one()
