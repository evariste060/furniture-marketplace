"""ADR-014 phase 3 migration c6e8a0b2d4f7: seller orders.

Runs on the disposable per-test schema of the *_test database (tests/conftest.py pg_engine). The
upgrade refuses, changing nothing, while orders exist (it never guesses a store or a commission
for existing lines); the downgrade refuses while seller orders exist; every order line belongs
to its store's seller order (composite foreign key, checked at commit).
"""

from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from tests.integration.test_image_media_migration import _alembic
from tests.integration.test_products_store_migration import _revision

PHASE3 = "c6e8a0b2d4f7"
BEFORE = "b2d4f6a8c0e1"


def _order(engine: Engine) -> str:
    order_id = str(uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO orders (id, order_number, checkout_idempotency_key, status, "
                "subtotal, total, recipient_name, recipient_phone, delivery_address_snapshot) "
                "VALUES (:id, :number, :key, 'received', 0, 0, 'Test', '+250788000000', '{}')"
            ),
            {"id": order_id, "number": f"T-{order_id[:12]}", "key": f"k-{order_id}"},
        )
    return order_id


def _store(engine: Engine) -> str:
    user_id, store_id = str(uuid4()), str(uuid4())
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, email, full_name) VALUES (:id, :email, 'Owner')"),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
        conn.execute(
            text(
                "INSERT INTO stores (id, owner_user_id, name, slug, contact_email, contact_phone, "
                "district, status, submitted_at, reviewed_at, approved_at) VALUES (:id, :owner, "
                "'Store', :slug, 'shop@example.com', '+250788000001', 'Gasabo', 'approved', now(), "
                "now(), now())"
            ),
            {"id": store_id, "owner": user_id, "slug": f"s-{store_id[:8]}"},
        )
    return store_id


def _seller_order(conn, order_id: str, store_id: str, **money) -> None:
    values = {
        "subtotal": 1000,
        "discount_total": 0,
        "merchandise_total": 1000,
        "commission_rate_bps": 1000,
        "commission_amount": 100,
        "seller_net_amount": 900,
        **money,
    }
    conn.execute(
        text(
            "INSERT INTO seller_orders (id, order_id, store_id, store_name_snapshot, subtotal, "
            "discount_total, merchandise_total, commission_rate_bps, commission_amount, "
            "seller_net_amount) VALUES (:id, :order, :store, 'Store', :subtotal, :discount_total, "
            ":merchandise_total, :commission_rate_bps, :commission_amount, :seller_net_amount)"
        ),
        {"id": str(uuid4()), "order": order_id, "store": store_id, **values},
    )


def _line(conn, order_id: str, store_id: str) -> None:
    conn.execute(
        text(
            "INSERT INTO order_items (id, order_id, store_id, store_name_snapshot, sku_snapshot, "
            "product_name_snapshot, quantity, unit_price, line_subtotal, line_total) VALUES "
            "(:id, :order, :store, 'Store', 'SKU', 'Sofa', 1, 1000, 1000, 1000)"
        ),
        {"id": str(uuid4()), "order": order_id, "store": store_id},
    )


def test_every_line_belongs_to_its_store_seller_order(pg_engine: Engine):
    assert _revision(pg_engine) == PHASE3
    order, store = _order(pg_engine), _store(pg_engine)
    with pytest.raises(IntegrityError, match="fk_order_items_seller_order"):
        with pg_engine.begin() as conn:
            _line(conn, order, store)  # no seller order for (order, store): refused at commit
    with pg_engine.begin() as conn:  # the seller order may come after its lines (deferred)
        _line(conn, order, store)
        _seller_order(conn, order, store)
    with pytest.raises(IntegrityError, match="order_store"):
        with pg_engine.begin() as conn:
            _seller_order(conn, order, store)  # one seller order per store and order


@pytest.mark.parametrize(
    ("money", "check"),
    [
        ({"merchandise_total": 999, "seller_net_amount": 899}, "merchandise_is_net_of_discount"),
        ({"seller_net_amount": 901}, "commission_and_net_make_merchandise"),
        ({"commission_rate_bps": 10_001}, "commission_rate_in_range"),
        (
            {
                "subtotal": -1,
                "merchandise_total": -1,
                "commission_amount": 0,
                "seller_net_amount": -1,
            },
            "amounts_nonnegative",
        ),
    ],
)
def test_seller_order_money_is_consistent(pg_engine: Engine, money: dict, check: str):
    order, store = _order(pg_engine), _store(pg_engine)
    with pytest.raises(IntegrityError, match=check):
        with pg_engine.begin() as conn:
            _seller_order(conn, order, store, **money)


def test_the_upgrade_refuses_and_changes_nothing_while_orders_exist(pg_engine: Engine):
    _alembic(pg_engine, "downgrade", BEFORE)
    _order(pg_engine)
    with pytest.raises(RuntimeError) as refused:
        _alembic(pg_engine, "upgrade", PHASE3)
    assert "1 orders exist" in str(refused.value) and "No order was changed" in str(refused.value)
    assert _revision(pg_engine) == BEFORE
    assert "seller_orders" not in inspect(pg_engine).get_table_names()
    assert "store_id" not in {c["name"] for c in inspect(pg_engine).get_columns("order_items")}

    with pg_engine.begin() as conn:  # the development path: remove the demo orders first
        conn.execute(text("DELETE FROM orders"))
    _alembic(pg_engine, "upgrade", PHASE3)
    assert _revision(pg_engine) == PHASE3
    _alembic(pg_engine, "check")  # the models match the migrated schema


def test_the_downgrade_refuses_while_seller_orders_exist(pg_engine: Engine):
    order, store = _order(pg_engine), _store(pg_engine)
    with pg_engine.begin() as conn:
        _seller_order(conn, order, store)
    with pytest.raises(RuntimeError, match="1 seller orders exist"):
        _alembic(pg_engine, "downgrade", BEFORE)
    assert _revision(pg_engine) == PHASE3
    with pg_engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM seller_orders")).scalar_one() == 1
        conn.execute(text("DELETE FROM seller_orders"))
    _alembic(pg_engine, "downgrade", BEFORE)
    assert "seller_orders" not in inspect(pg_engine).get_table_names()
    with pg_engine.begin() as conn:  # the upgrade refuses while orders exist
        conn.execute(text("DELETE FROM orders"))
    _alembic(pg_engine, "upgrade", PHASE3)
