"""The customer-cart upsert must work under a generic plan (2026-10-26).

psycopg prepares a statement after it has run 5 times on one connection, and PostgreSQL may then
plan it generically. A generic plan cannot match `ON CONFLICT ... WHERE status = $1` to the
partial index uq_carts_active_user, so every add-to-cart failed with 500 until the connection
was recycled. force_generic_plan reproduces that state on the first run.
"""

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Cart, User
from app.repositories import cart_repository


def test_ensure_customer_cart_works_under_a_generic_plan(db: Session):
    user = User(email="generic.plan@example.rw", full_name="Generic Plan", password_hash="x")
    db.add(user)
    db.commit()
    db.execute(text("SET plan_cache_mode = force_generic_plan"))
    try:
        first = cart_repository.ensure_customer_cart(db, user.id)
        db.commit()
        again = cart_repository.ensure_customer_cart(db, user.id)  # the conflict path
        db.commit()
    finally:
        db.execute(text("RESET plan_cache_mode"))
        db.commit()
    assert again.id == first.id
    assert db.scalar(select(func.count(Cart.id)).where(Cart.user_id == user.id)) == 1
