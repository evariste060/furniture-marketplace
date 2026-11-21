"""Cart queries (module 11). Every lookup is scoped to one owner: a customer's user ID or a
guest token hash, so a cart or line of another owner is simply not found."""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import Cart, CartItem, Product, ProductVariant

GUEST_CART_LIFETIME = timedelta(days=30)  # §7 Q10


@dataclass(frozen=True)
class LineRow:
    id: uuid.UUID
    variant_id: uuid.UUID
    quantity: int
    sku: str
    variant_name: str
    product_name: str
    product_slug: str
    price_at_add: int | None
    product_id: uuid.UUID


def _active(query, *, lock: bool):
    query = query.where(Cart.status == "active")
    return query.with_for_update() if lock else query


def customer_cart(db: Session, user_id: uuid.UUID, *, lock: bool = False) -> Cart | None:
    return db.scalar(_active(select(Cart).where(Cart.user_id == user_id), lock=lock))


def guest_cart(db: Session, token_hash: str, *, lock: bool = False) -> Cart | None:
    """The active guest cart for this token hash, expired or not (the caller checks expiry)."""
    return db.scalar(_active(select(Cart).where(Cart.guest_token_hash == token_hash), lock=lock))


def is_expired(db: Session, cart: Cart) -> bool:
    if cart.expires_at is None:
        return False
    return bool(db.scalar(select(func.clock_timestamp() >= cart.expires_at)))


def ensure_customer_cart(db: Session, user_id: uuid.UUID) -> Cart:
    """The customer's active cart, created if missing, row-locked. Two concurrent first
    requests cannot create two carts: the insert yields to the partial unique index."""
    db.execute(
        pg_insert(Cart)
        .values(id=uuid.uuid4(), user_id=user_id, status="active")
        .on_conflict_do_nothing(
            index_elements=["user_id"],
            # The predicate is written as SQL text, not a bound parameter: PostgreSQL matches
            # it to the partial index uq_carts_active_user while planning, and a generic plan
            # of the prepared statement (psycopg prepares a query after 5 runs on a connection)
            # cannot prove that a parameter equals 'active', so the insert would fail.
            index_where=text("status = 'active' AND user_id IS NOT NULL"),
        )
    )
    cart = customer_cart(db, user_id, lock=True)
    assert cart is not None
    return cart


def create_guest_cart(db: Session, token_hash: str) -> Cart:
    cart = Cart(guest_token_hash=token_hash, status="active")
    db.add(cart)
    db.flush()
    refresh_guest_expiry(db, cart)
    return cart


def refresh_guest_expiry(db: Session, cart: Cart) -> None:
    """A guest cart expires 30 days after its last change (database time)."""
    if cart.guest_token_hash is None:
        return
    cart.expires_at = db.scalar(select(func.clock_timestamp() + GUEST_CART_LIFETIME))
    db.flush()


def lines(db: Session, cart_id: uuid.UUID) -> list[LineRow]:
    rows = db.execute(
        select(
            CartItem.id,
            CartItem.variant_id,
            CartItem.quantity,
            ProductVariant.sku,
            ProductVariant.name,
            Product.name,
            Product.slug,
            CartItem.price_at_add,
            Product.id,
        )
        .join(ProductVariant, ProductVariant.id == CartItem.variant_id)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(CartItem.cart_id == cart_id)
        .order_by(CartItem.created_at, CartItem.id)
    ).all()
    return [LineRow(*row) for row in rows]


def item(db: Session, cart_id: uuid.UUID, item_id: uuid.UUID) -> CartItem | None:
    return db.scalar(select(CartItem).where(CartItem.id == item_id, CartItem.cart_id == cart_id))


def item_for_variant(db: Session, cart_id: uuid.UUID, variant_id: uuid.UUID) -> CartItem | None:
    return db.scalar(
        select(CartItem).where(CartItem.cart_id == cart_id, CartItem.variant_id == variant_id)
    )


def current_price(db: Session, variant_id: uuid.UUID) -> int | None:
    return db.scalar(select(ProductVariant.price).where(ProductVariant.id == variant_id))


def accept_prices(db: Session, cart_id: uuid.UUID) -> None:
    """Every line's price_at_add becomes its variant's current price."""
    db.execute(
        update(CartItem)
        .where(CartItem.cart_id == cart_id, CartItem.variant_id == ProductVariant.id)
        .values(price_at_add=ProductVariant.price)
    )


def delete_item(db: Session, item_id: uuid.UUID) -> None:
    db.execute(delete(CartItem).where(CartItem.id == item_id))
