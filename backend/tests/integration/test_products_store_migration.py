"""ADR-014 phase 2 migration b2d4f6a8c0e1: every product belongs to a store.

Runs on the disposable per-test schema of the *_test database (tests/conftest.py pg_engine). The
upgrade refuses, changing nothing, while products exist (it never invents an owner for them);
the column is NOT NULL with a RESTRICT foreign key, so a store with products cannot be deleted.
"""

from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from tests.integration.test_image_media_migration import _alembic

PHASE2 = "b2d4f6a8c0e1"
BEFORE = "a9d3f5b7c1e2"
HEAD = "f2a4c6e8b0d1"  # ADR-014 phase 6 (furniture service icons)


def _revision(engine: Engine) -> str:
    with engine.begin() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _category(engine: Engine) -> str:
    category_id = str(uuid4())
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO categories (id, name, slug) VALUES (:id, 'Sofas', :slug)"),
            {"id": category_id, "slug": f"sofas-{category_id[:8]}"},
        )
    return category_id


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
                ":name, :slug, 'shop@example.com', '+250788000001', 'Gasabo', 'approved', now(), "
                "now(), now())"
            ),
            {
                "id": store_id,
                "owner": user_id,
                "name": f"Store {store_id[:8]}",
                "slug": f"s-{store_id[:8]}",
            },
        )
    return store_id


def _product(engine: Engine, category_id: str, store_id: str | None) -> None:
    columns = "id, name, slug, category_id" + (", store_id" if store_id else "")
    values = ":id, 'Sofa', :slug, :category" + (", :store" if store_id else "")
    product_id = str(uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO products ({columns}) VALUES ({values})"),
            {
                "id": product_id,
                "slug": f"sofa-{product_id[:8]}",
                "category": category_id,
                "store": store_id,
            },
        )


def test_products_need_a_store_at_head(pg_engine: Engine):
    assert _revision(pg_engine) == HEAD
    columns = {c["name"]: c for c in inspect(pg_engine).get_columns("products")}
    assert columns["store_id"]["nullable"] is False
    category, store = _category(pg_engine), _store(pg_engine)
    with pytest.raises(IntegrityError, match="store_id"):
        _product(pg_engine, category, None)
    _product(pg_engine, category, store)
    with pytest.raises(IntegrityError, match="fk_products_store_id_stores"):
        with pg_engine.begin() as conn:
            conn.execute(text("DELETE FROM stores WHERE id = :id"), {"id": store})


def test_the_upgrade_refuses_and_changes_nothing_while_products_exist(pg_engine: Engine):
    _alembic(pg_engine, "downgrade", BEFORE)
    category = _category(pg_engine)
    _product(pg_engine, category, None)
    _product(pg_engine, category, None)
    with pytest.raises(RuntimeError) as refused:
        _alembic(pg_engine, "upgrade", PHASE2)
    assert "2 products exist" in str(refused.value) and "No product was changed" in str(
        refused.value
    )
    assert _revision(pg_engine) == BEFORE
    with pg_engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM products")).scalar_one() == 2
    assert "store_id" not in {c["name"] for c in inspect(pg_engine).get_columns("products")}

    with pg_engine.begin() as conn:  # the development path: remove the demo catalogue first
        conn.execute(text("DELETE FROM products"))
    _alembic(pg_engine, "upgrade", PHASE2)
    assert _revision(pg_engine) == PHASE2
    _alembic(pg_engine, "upgrade", "head")
    _alembic(pg_engine, "check")  # the models match the migrated schema


def test_the_downgrade_drops_the_column(pg_engine: Engine):
    _alembic(pg_engine, "downgrade", BEFORE)
    assert "store_id" not in {c["name"] for c in inspect(pg_engine).get_columns("products")}
    _alembic(pg_engine, "upgrade", PHASE2)
    assert "ix_products_store_status" in {
        i["name"] for i in inspect(pg_engine).get_indexes("products")
    }
