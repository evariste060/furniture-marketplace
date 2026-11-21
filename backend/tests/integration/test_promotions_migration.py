"""Promotions migration (module 13, revision d2f7a9c4e8b1). Runs on the disposable per-test
schema of the *_test database (tests/conftest.py pg_engine)."""

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.core.config import get_settings

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
BEFORE = "b6f1d3a9c8e4"
PROMOTIONS = "d2f7a9c4e8b1"
NEW_DISCOUNT_COLUMNS = {
    "percent_off",
    "amount_off",
    "applies_to",
    "min_subtotal",
    "max_discount",
    "usage_limit_total",
    "usage_limit_per_customer",
}


def _alembic(engine: Engine, action: str, *args: str) -> None:
    previous = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = engine.url.render_as_string(hide_password=False)
    get_settings.cache_clear()
    try:
        getattr(command, action)(Config(str(ALEMBIC_INI)), *args)
    finally:
        os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


def _columns(engine: Engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def _version(engine: Engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _legacy_discount(
    engine: Engine, code: str | None, kind: str = "percent", value: str = "10", **extra
) -> str:
    discount_id = str(uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO discounts (id, code, name, kind, value, status, rules) "
                "VALUES (:id, :code, 'Legacy', :kind, CAST(:value AS numeric), :status, "
                "CAST(:rules AS jsonb))"
            ),
            {
                "id": discount_id,
                "code": code,
                "kind": kind,
                "value": value,
                "status": extra.get("status", "active"),
                "rules": json.dumps(extra.get("rules", {})),
            },
        )
    return discount_id


def _legacy_product(engine: Engine) -> tuple[str, str]:
    category, product, variant = (str(uuid4()) for _ in range(3))
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO categories (id, name, slug) VALUES (:id, 'C', :slug)"),
            {"id": category, "slug": f"c-{category}"},
        )
        conn.execute(
            text("INSERT INTO products (id, name, slug, category_id) VALUES (:id, 'P', :slug, :c)"),
            {"id": product, "slug": f"p-{product}", "c": category},
        )
        conn.execute(
            text(
                "INSERT INTO product_variants (id, product_id, sku, name, price) "
                "VALUES (:id, :p, :sku, 'V', 1000)"
            ),
            {"id": variant, "p": product, "sku": f"SKU-{variant[:8]}"},
        )
    return product, variant


def test_head_schema_has_the_approved_columns_and_constraints(pg_engine: Engine):
    inspector = inspect(pg_engine)
    assert NEW_DISCOUNT_COLUMNS <= _columns(pg_engine, "discounts")
    assert {"value", "rules"}.isdisjoint(_columns(pg_engine, "discounts"))
    assert {"category_id", "brand_id", "product_id"} <= _columns(pg_engine, "discount_targets")
    assert "variant_id" not in _columns(pg_engine, "discount_targets")
    assert {"customer_phone", "status", "released_at", "release_reason"} <= _columns(
        pg_engine, "discount_redemptions"
    )
    assert "discount_id" in _columns(pg_engine, "carts")
    checks = {c["name"] for c in inspector.get_check_constraints("discounts")}
    assert {
        "ck_discounts_code_upper_case",
        "ck_discounts_amount_matches_kind",
        "ck_discounts_valid_status",
        "ck_discounts_valid_applies_to",
    } <= checks
    uniques = {u["name"] for u in inspector.get_unique_constraints("discount_redemptions")}
    assert "discount_order_redemption" in uniques


def test_alembic_check_finds_no_drift(pg_engine: Engine):
    _alembic(pg_engine, "check")


def test_database_constraints_refuse_bad_rows(pg_engine: Engine):
    bad = [
        "INSERT INTO discounts (id, code, name, kind, percent_off) "
        "VALUES (gen_random_uuid(), 'X10', 'x', 'percent', 0)",
        "INSERT INTO discounts (id, code, name, kind, percent_off, amount_off) "
        "VALUES (gen_random_uuid(), 'X11', 'x', 'percent', 10, 5)",
        "INSERT INTO discounts (id, code, name, kind, amount_off) "
        "VALUES (gen_random_uuid(), 'X12', 'x', 'fixed', 0)",
        "INSERT INTO discounts (id, code, name, kind, percent_off, status) "
        "VALUES (gen_random_uuid(), 'X13', 'x', 'percent', 10, 'expired')",
        "INSERT INTO discounts (id, code, name, kind, percent_off) "
        "VALUES (gen_random_uuid(), 'lower', 'x', 'percent', 10)",
    ]
    for statement in bad:
        with pytest.raises(IntegrityError), pg_engine.begin() as conn:
            conn.execute(text(statement))
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO discounts (id, code, name, kind, percent_off) "
                "VALUES (gen_random_uuid(), 'DUP', 'x', 'percent', 10)"
            )
        )
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO discounts (id, code, name, kind, percent_off) "
                "VALUES (gen_random_uuid(), 'DUP', 'x', 'percent', 10)"
            )
        )
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        conn.execute(  # a target names exactly one thing
            text(
                "INSERT INTO discount_targets (id, discount_id) "
                "SELECT gen_random_uuid(), id FROM discounts WHERE code = 'DUP'"
            )
        )


def test_upgrade_carries_over_mappable_legacy_discounts_and_back(pg_engine: Engine):
    _alembic(pg_engine, "downgrade", BEFORE)
    assert NEW_DISCOUNT_COLUMNS.isdisjoint(_columns(pg_engine, "discounts"))
    percent = _legacy_discount(pg_engine, " welcome10 ", "percent", "10.00")
    fixed = _legacy_discount(pg_engine, "FLAT500", "fixed", "500")
    product, _ = _legacy_product(pg_engine)
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO discount_targets (id, discount_id, product_id) "
                "VALUES (gen_random_uuid(), :d, :p)"
            ),
            {"d": fixed, "p": product},
        )

    _alembic(pg_engine, "upgrade", PROMOTIONS)
    with pg_engine.connect() as conn:
        rows = {
            str(r.id): r
            for r in conn.execute(
                text("SELECT id, code, kind, percent_off, amount_off, applies_to FROM discounts")
            )
        }
    assert (rows[percent].code, rows[percent].percent_off, rows[percent].amount_off) == (
        "WELCOME10",
        10,
        None,
    )
    assert rows[percent].applies_to == "all"
    assert (rows[fixed].amount_off, rows[fixed].applies_to) == (500, "targets")

    _alembic(pg_engine, "downgrade", BEFORE)  # and back again without loss
    with pg_engine.connect() as conn:
        values: dict[str, object] = {
            row.code: row.value for row in conn.execute(text("SELECT code, value FROM discounts"))
        }
    assert {k: int(str(v).split(".")[0]) for k, v in values.items()} == {
        "WELCOME10": 10,
        "FLAT500": 500,
    }
    _alembic(pg_engine, "upgrade", PROMOTIONS)
    assert _version(pg_engine) == PROMOTIONS


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        (lambda e: _legacy_discount(e, None), "has no code"),
        (lambda e: _legacy_discount(e, "has space"), "not letters, digits"),
        (
            lambda e: (_legacy_discount(e, "SAME"), _legacy_discount(e, "same")),
            "differ only in letter case",
        ),
        (lambda e: _legacy_discount(e, "FRAC", "fixed", "10.50"), "has a fraction"),
        (lambda e: _legacy_discount(e, "TOOBIG", "percent", "100.00", status="active"), None),
        (lambda e: _legacy_discount(e, "OLD", status="expired"), "status 'expired'"),
        (lambda e: _legacy_discount(e, "RULES", rules={"min": 1}), "rules holds data"),
    ],
)
def test_upgrade_refuses_data_it_cannot_carry_over_and_changes_nothing(
    pg_engine: Engine, setup, reason
):
    _alembic(pg_engine, "downgrade", BEFORE)
    setup(pg_engine)
    if reason is None:  # a 100% discount maps cleanly
        _alembic(pg_engine, "upgrade", PROMOTIONS)
        assert _version(pg_engine) == PROMOTIONS
        return
    with pytest.raises(RuntimeError, match=reason):
        _alembic(pg_engine, "upgrade", PROMOTIONS)
    assert _version(pg_engine) == BEFORE
    assert {"value", "rules"} <= _columns(pg_engine, "discounts")


def test_upgrade_refuses_variant_targets_and_existing_redemptions(pg_engine: Engine):
    _alembic(pg_engine, "downgrade", BEFORE)
    discount = _legacy_discount(pg_engine, "VARIANT")
    _, variant = _legacy_product(pg_engine)
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO discount_targets (id, discount_id, variant_id) "
                "VALUES (gen_random_uuid(), :d, :v)"
            ),
            {"d": discount, "v": variant},
        )
    with pytest.raises(RuntimeError, match="targets a variant"):
        _alembic(pg_engine, "upgrade", PROMOTIONS)
    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM discount_targets"))
        order = str(uuid4())
        conn.execute(
            text(
                "INSERT INTO orders (id, order_number, checkout_idempotency_key, subtotal, "
                "total, recipient_name, recipient_phone, delivery_address_snapshot) VALUES "
                "(:id, :n, :k, 0, 0, 'R', '+250780000000', '{}')"
            ),
            {"id": order, "n": f"T-{order[:8]}", "k": f"k-{order}"},
        )
        conn.execute(
            text(
                "INSERT INTO discount_redemptions (id, discount_id, order_id, amount) "
                "VALUES (gen_random_uuid(), :d, :o, 0)"
            ),
            {"d": discount, "o": order},
        )
    with pytest.raises(RuntimeError, match="redemptions exist"):
        _alembic(pg_engine, "upgrade", PROMOTIONS)
    assert _version(pg_engine) == BEFORE


def test_downgrade_refuses_category_or_brand_targets(pg_engine: Engine):
    _alembic(pg_engine, "downgrade", PROMOTIONS)  # later revisions (module 14) first
    with pg_engine.begin() as conn:
        discount: object = conn.execute(
            text(
                "INSERT INTO discounts (id, code, name, kind, percent_off, applies_to) "
                "VALUES (gen_random_uuid(), 'CAT10', 'x', 'percent', 10, 'targets') RETURNING id"
            )
        ).scalar_one()
        category: object = conn.execute(
            text(
                "INSERT INTO categories (id, name, slug) VALUES (gen_random_uuid(), 'C', 'c-down') "
                "RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO discount_targets (id, discount_id, category_id) "
                "VALUES (gen_random_uuid(), :d, :c)"
            ),
            {"d": discount, "c": category},
        )
    with pytest.raises(RuntimeError, match="category or brand"):
        _alembic(pg_engine, "downgrade", BEFORE)
    assert _version(pg_engine) == PROMOTIONS
