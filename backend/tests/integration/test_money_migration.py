"""Money migration to whole-RWF BIGINT (ADR-007, implementation plan step A2)."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.core.config import get_settings
from app.models.common import MAX_MONEY_RWF

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
BEFORE = "e1b7f3c9a5d2"
MONEY = "528e6436c34e"


def _migrate(engine: Engine, action: str, revision: str) -> None:
    previous = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = engine.url.render_as_string(hide_password=False)
    get_settings.cache_clear()
    try:
        getattr(command, action)(Config(str(ALEMBIC_INI)), revision)
    finally:
        os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


def _seed_variant(engine: Engine, price: str, compare_at: str | None = None) -> str:
    ids = [str(uuid4()) for _ in range(3)]
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO categories (id, name, slug) VALUES (:id, 'Phones', :slug)"),
            {"id": ids[0], "slug": f"phones-{ids[0]}"},
        )
        conn.execute(
            text(
                "INSERT INTO products (id, name, slug, category_id) "
                "VALUES (:id, 'Phone', :slug, :category)"
            ),
            {"id": ids[1], "slug": f"phone-{ids[1]}", "category": ids[0]},
        )
        conn.execute(
            text(
                "INSERT INTO product_variants (id, product_id, sku, name, price, compare_at_price) "
                "VALUES (:id, :product, :sku, 'Black', CAST(:price AS numeric), "
                "CAST(:compare_at AS numeric))"
            ),
            {
                "id": ids[2],
                "product": ids[1],
                "sku": f"SKU-{ids[2]}",
                "price": price,
                "compare_at": compare_at,
            },
        )
    return ids[2]


def _variant_amounts(engine: Engine, variant_id: str) -> tuple:
    with engine.connect() as conn:
        return tuple(
            conn.execute(
                text("SELECT price, compare_at_price FROM product_variants WHERE id = :id"),
                {"id": variant_id},
            ).one()
        )


def _column_type(engine: Engine, table: str, column: str) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        ).scalar_one()


def _current_revision(engine: Engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_whole_amounts_survive_upgrade_and_downgrade(pg_engine: Engine):
    _migrate(pg_engine, "downgrade", BEFORE)
    variant = _seed_variant(pg_engine, "125000.00", "150000.00")

    _migrate(pg_engine, "upgrade", MONEY)
    assert _variant_amounts(pg_engine, variant) == (125000, 150000)
    assert _column_type(pg_engine, "product_variants", "price") == "bigint"

    _migrate(pg_engine, "downgrade", BEFORE)
    assert _column_type(pg_engine, "product_variants", "price") == "numeric"
    assert [str(v) for v in _variant_amounts(pg_engine, variant)] == ["125000.00", "150000.00"]

    _migrate(pg_engine, "upgrade", "head")
    assert _variant_amounts(pg_engine, variant) == (125000, 150000)


def test_fractional_amounts_block_the_upgrade_without_rounding(pg_engine: Engine):
    _migrate(pg_engine, "downgrade", BEFORE)
    variant = _seed_variant(pg_engine, "1500.50")

    with pytest.raises(RuntimeError) as excinfo:
        _migrate(pg_engine, "upgrade", MONEY)

    message = str(excinfo.value)
    assert "product_variants.price: 1 row(s)" in message
    assert "1500.50" not in message  # counts only, never amounts
    assert _current_revision(pg_engine) == BEFORE
    assert _column_type(pg_engine, "product_variants", "price") == "numeric"
    assert str(_variant_amounts(pg_engine, variant)[0]) == "1500.50"


def test_database_rejects_amounts_above_the_cap(pg_engine: Engine):
    _seed_variant(pg_engine, str(MAX_MONEY_RWF))
    with pytest.raises(IntegrityError, match="amounts_within_cap"):
        _seed_variant(pg_engine, str(MAX_MONEY_RWF + 1))


MONEY_COLUMNS = {
    "product_variants": ("price", "compare_at_price"),
    "orders": ("subtotal", "discount_total", "delivery_fee", "tax_total", "total"),
    "order_items": ("unit_price", "line_subtotal", "discount_amount", "tax_amount", "line_total"),
    "payment_attempts": ("amount",),
    "delivery_fee_rules": ("fee",),
    "discount_redemptions": ("amount",),
}


def test_every_money_column_is_bigint(pg_engine: Engine):
    types = {
        (table, column): _column_type(pg_engine, table, column)
        for table, columns in MONEY_COLUMNS.items()
        for column in columns
    }
    assert set(types.values()) == {"bigint"}, types
