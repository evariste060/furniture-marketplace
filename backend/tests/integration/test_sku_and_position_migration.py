"""Case-insensitive SKUs, one product image per position, import warnings (revision e7b2d6f4a8c3;
checkpoint 1b, 2026-10-26). The upgrade checks existing data first and refuses with a list.

Runs on the disposable per-test schema of the *_test database (tests/conftest.py pg_engine).
"""

from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from tests.integration.test_image_media_migration import _alembic
from tests.integration.test_media_registry_migration import _media, _product

BEFORE = "d5f9b3c7e1a2"
RULES = "e7b2d6f4a8c3"


def _variant(conn, product: str, sku: str) -> None:
    conn.execute(
        text(
            "INSERT INTO product_variants (id, product_id, sku, name, price) "
            "VALUES (:id, :product, :sku, 'Std', 100)"
        ),
        {"id": str(uuid4()), "product": product, "sku": sku},
    )


def _image(conn, product: str, sort_order: int) -> None:
    key = f"products/{product}/{uuid4().hex}.jpg"
    public = _media(conn, key, "public", "products", product)
    original = _media(conn, key, "private", "products", product)
    conn.execute(
        text(
            "INSERT INTO product_images (id, product_id, public_media_id, original_media_id, "
            "sort_order) VALUES (:id, :product, :public, :original, :sort_order)"
        ),
        {
            "id": str(uuid4()),
            "product": product,
            "public": public,
            "original": original,
            "sort_order": sort_order,
        },
    )


def test_the_upgrade_refuses_with_a_list_until_the_data_is_fixed(pg_engine: Engine):
    _alembic(pg_engine, "downgrade", BEFORE)
    with pg_engine.begin() as conn:
        _, _, product = _product(conn)
        _variant(conn, product, "ABC-1")
        _variant(conn, product, "abc-1")
        _variant(conn, product, "X__2")
        _image(conn, product, 0)
        _image(conn, product, 0)
    with pytest.raises(RuntimeError) as refused:
        _alembic(pg_engine, "upgrade", RULES)
    message = str(refused.value)
    assert "3 problem(s)" in message
    assert "SKUs differing only by case: " in message  # listed in collation order
    assert "ABC-1" in message and "abc-1" in message
    assert "SKU containing '__': X__2" in message
    assert "2 images at position 1" in message

    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE product_variants SET sku = 'ABC-2' WHERE sku = 'abc-1'"))
        conn.execute(text("UPDATE product_variants SET sku = 'X-2' WHERE sku = 'X__2'"))
        conn.execute(
            text(
                "UPDATE product_images SET sort_order = 1 WHERE id = "
                "(SELECT id FROM product_images ORDER BY id LIMIT 1)"
            )
        )
    _alembic(pg_engine, "upgrade", RULES)
    assert "warnings" in {c["name"] for c in inspect(pg_engine).get_columns("import_jobs")}


def test_the_new_indexes_hold_and_variant_images_may_share_positions(pg_engine: Engine):
    with pg_engine.begin() as conn:
        _, _, product = _product(conn)
        _variant(conn, product, "SKU-1")
        _image(conn, product, 0)
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        _variant(conn, product, "sku-1")
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        _image(conn, product, 0)
    with pg_engine.begin() as conn:
        variant = conn.execute(text("SELECT id FROM product_variants LIMIT 1")).scalar()
        key = f"products/{product}/{uuid4().hex}.jpg"
        public = _media(conn, key, "public", "products", product)
        original = _media(conn, key, "private", "products", product)
        conn.execute(
            text(
                "INSERT INTO product_images (id, product_id, variant_id, public_media_id, "
                "original_media_id, sort_order) VALUES (:id, :product, :variant, :public, "
                ":original, 0)"
            ),
            {
                "id": str(uuid4()),
                "product": product,
                "variant": variant,
                "public": public,
                "original": original,
            },
        )


def test_the_downgrade_drops_the_indexes_and_the_column(pg_engine: Engine):
    _alembic(pg_engine, "downgrade", BEFORE)
    indexes = {i["name"] for i in inspect(pg_engine).get_indexes("product_variants")}
    assert "uq_product_variants_sku_lower" not in indexes
    assert "warnings" not in {c["name"] for c in inspect(pg_engine).get_columns("import_jobs")}
    _alembic(pg_engine, "upgrade", "head")
