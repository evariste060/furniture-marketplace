"""Media registry migration (revision c4e8f2a6b9d1; checkpoint 1b topic 1, 2026-10-26).

Runs on the disposable per-test schema of the *_test database (tests/conftest.py pg_engine).
"""

import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from tests.integration.test_image_media_migration import _alembic

BEFORE = "b8d3f5a1c2e7"
REGISTRY = "c4e8f2a6b9d1"
SHA = hashlib.sha256(b"x").hexdigest()


def _columns(engine: Engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def _product(conn) -> tuple[str, str, str]:
    category, brand, product = (str(uuid4()) for _ in range(3))
    conn.execute(
        text("INSERT INTO categories (id, name, slug) VALUES (:id, 'Phones', :slug)"),
        {"id": category, "slug": f"phones-{category}"},
    )
    conn.execute(
        text("INSERT INTO brands (id, name, slug) VALUES (:id, 'Tecno', :slug)"),
        {"id": brand, "slug": f"tecno-{brand}"},
    )
    conn.execute(
        text(
            "INSERT INTO products (id, name, slug, category_id, brand_id) "
            "VALUES (:id, 'Phone', :slug, :category, :brand)"
        ),
        {"id": product, "slug": f"phone-{product}", "category": category, "brand": brand},
    )
    return category, brand, product


def _media(conn, key: str, visibility: str, owner_type: str, owner_id: str, **extra) -> str:
    media_id = str(uuid4())
    values = {
        "id": media_id,
        "key": key,
        "visibility": visibility,
        "kind": "public_source" if visibility == "public" else "original",
        "state": "active",
        "sha": SHA,
        "width": 800 if visibility == "public" else None,
        "height": 600 if visibility == "public" else None,
        "owner_type": owner_type,
        "owner_id": owner_id,
        "delete_after": None,
        **extra,
    }
    conn.execute(
        text(
            "INSERT INTO media_objects (id, storage_key, visibility, kind, state, sha256, bytes, "
            "width, height, content_type, owner_type, owner_id, delete_after) VALUES (:id, :key, "
            ":visibility, :kind, :state, :sha, 10, :width, :height, 'image/jpeg', :owner_type, "
            ":owner_id, :delete_after)"
        ),
        values,
    )
    return media_id


def test_the_registry_replaces_the_key_columns(pg_engine: Engine):
    assert "media_objects" in inspect(pg_engine).get_table_names()
    assert {"public_media_id", "original_media_id"} <= _columns(pg_engine, "product_images")
    assert {"storage_key", "original_key", "thumbnail_key", "width", "height"}.isdisjoint(
        _columns(pg_engine, "product_images")
    )
    assert {"image_media_id", "image_original_media_id"} <= _columns(pg_engine, "categories")
    assert "image_key" not in _columns(pg_engine, "categories")
    assert {"logo_media_id", "logo_original_media_id"} <= _columns(pg_engine, "brands")
    assert "logo_key" not in _columns(pg_engine, "brands")


@pytest.mark.parametrize(
    "extra",
    [
        {"visibility": "public", "kind": "original"},  # originals are private
        {"visibility": "private", "kind": "public_source"},
        {"kind": "incoming"},  # incoming: private and with an expiry
        {"state": "gone"},
        {"sha": "not-a-hash"},
        {"width": 0, "height": 5},
        {"width": 5, "height": None},
        {"owner_type": "orders"},
    ],
    ids=lambda extra: "-".join(f"{k}={v}" for k, v in extra.items()),
)
def test_registry_constraints(pg_engine: Engine, extra: dict):
    values = dict(extra)
    visibility = values.pop("visibility", "public")
    owner_type = values.pop("owner_type", "products")
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        _media(conn, f"k/{uuid4()}", visibility, owner_type, str(uuid4()), **values)


def test_a_key_is_unique_within_its_visibility_only(pg_engine: Engine):
    owner = str(uuid4())
    with pg_engine.begin() as conn:
        _media(conn, "same/key.jpg", "public", "products", owner)
        _media(conn, "same/key.jpg", "private", "products", owner)  # the original, same key
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        _media(conn, "same/key.jpg", "public", "products", owner)


def test_media_in_use_cannot_be_deleted(pg_engine: Engine):
    with pg_engine.begin() as conn:
        category, _, product = _product(conn)
        public = _media(conn, "a.jpg", "public", "products", product)
        original = _media(conn, "a.jpg", "private", "products", product)
        conn.execute(
            text(
                "INSERT INTO product_images (id, product_id, public_media_id, original_media_id) "
                "VALUES (:id, :product, :public, :original)"
            ),
            {"id": str(uuid4()), "product": product, "public": public, "original": original},
        )
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM media_objects WHERE id = :id"), {"id": public})
    # A category image needs both its objects.
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        lone = _media(conn, "c.jpg", "public", "categories", category)
        conn.execute(
            text("UPDATE categories SET image_media_id = :m WHERE id = :id"),
            {"m": lone, "id": category},
        )


def test_the_upgrade_refuses_while_unregistered_images_exist(pg_engine: Engine):
    _alembic(pg_engine, "downgrade", BEFORE)
    with pg_engine.begin() as conn:
        category, brand, product = _product(conn)
        conn.execute(
            text(
                "INSERT INTO product_images (id, product_id, storage_key) "
                "VALUES (:id, :product, 'products/old.jpg')"
            ),
            {"id": str(uuid4()), "product": product},
        )
        conn.execute(
            text(
                "UPDATE categories SET image_key = 'c.png', image_width = 5, image_height = 5 "
                "WHERE id = :id"
            ),
            {"id": category},
        )
    with pytest.raises(RuntimeError) as refused:
        _alembic(pg_engine, "upgrade", REGISTRY)
    message = str(refused.value)
    assert "1 product image rows" in message and "1 category images" in message
    assert "reset_dev_images.py --confirm" in message
    assert "media_objects" not in inspect(pg_engine).get_table_names()  # nothing changed

    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM product_images"))
        conn.execute(
            text("UPDATE categories SET image_key = NULL, image_width = NULL, image_height = NULL")
        )
    _alembic(pg_engine, "upgrade", REGISTRY)
    assert "media_objects" in inspect(pg_engine).get_table_names()


def test_the_downgrade_moves_the_links_back_to_keys_and_dimensions(pg_engine: Engine):
    with pg_engine.begin() as conn:
        category, brand, product = _product(conn)
        public = _media(conn, "p.jpg", "public", "products", product)
        original = _media(conn, "p.jpg", "private", "products", product)
        image = str(uuid4())
        conn.execute(
            text(
                "INSERT INTO product_images (id, product_id, public_media_id, original_media_id) "
                "VALUES (:id, :product, :public, :original)"
            ),
            {"id": image, "product": product, "public": public, "original": original},
        )
        logo = _media(conn, "l.png", "public", "brands", brand)
        logo_original = _media(conn, "l.png", "private", "brands", brand)
        conn.execute(
            text(
                "UPDATE brands SET logo_media_id = :m, logo_original_media_id = :o WHERE id = :id"
            ),
            {"m": logo, "o": logo_original, "id": brand},
        )
    _alembic(pg_engine, "downgrade", BEFORE)
    assert "media_objects" not in inspect(pg_engine).get_table_names()
    with pg_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT storage_key, original_key, width, height FROM product_images WHERE id = :id"
            ),
            {"id": image},
        ).one()
        assert tuple(row) == ("p.jpg", "p.jpg", 800, 600)
        logo_row = conn.execute(
            text("SELECT logo_key, logo_width, logo_height FROM brands WHERE id = :id"),
            {"id": brand},
        ).one()
        assert tuple(logo_row) == ("l.png", 800, 600)
