"""Finance role (a7c2e4f9b1d3) and catalogue media and merchandising (b8d3f5a1c2e7) migrations.

Runs on the disposable per-test schema of the *_test database (tests/conftest.py pg_engine). The
image key columns of b8d3f5a1c2e7 were replaced by the media registry (c4e8f2a6b9d1), so the
image tests run at revision b8d3f5a1c2e7.
"""

from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from tests.integration.test_image_media_migration import _alembic

BEFORE = "f3a8c6e1b5d9"
FINANCE = "a7c2e4f9b1d3"
MEDIA = "b8d3f5a1c2e7"
NEW_COLUMNS = {
    "categories": {"description", "image_key", "image_width", "image_height"},
    "brands": {"logo_key", "logo_width", "logo_height"},
    "products": {"is_featured"},
    "product_images": {"original_key"},
}


def _columns(engine: Engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def _catalogue(engine: Engine) -> dict[str, str]:
    ids = {name: str(uuid4()) for name in ("category", "brand", "product", "image")}
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO categories (id, name, slug) VALUES (:id, 'Phones', :slug)"),
            {"id": ids["category"], "slug": f"phones-{ids['category']}"},
        )
        conn.execute(
            text("INSERT INTO brands (id, name, slug) VALUES (:id, 'Tecno', :slug)"),
            {"id": ids["brand"], "slug": f"tecno-{ids['brand']}"},
        )
        conn.execute(
            text(
                "INSERT INTO products (id, name, slug, category_id, brand_id) "
                "VALUES (:id, 'Phone', :slug, :category, :brand)"
            ),
            {
                "id": ids["product"],
                "slug": f"phone-{ids['product']}",
                "category": ids["category"],
                "brand": ids["brand"],
            },
        )
        conn.execute(
            text(
                "INSERT INTO product_images (id, product_id, storage_key, thumbnail_key, width, "
                "height) VALUES (:id, :product, :key, :thumb, 1600, 800)"
            ),
            {
                "id": ids["image"],
                "product": ids["product"],
                "key": "products/" + "a" * 32 + ".jpg",
                "thumb": "products/" + "a" * 32 + "_thumb.jpg",
            },
        )
    return ids


def _staff(engine: Engine, role: str) -> None:
    user_id = str(uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, full_name, is_staff, is_active) "
                "VALUES (:id, :email, 'x', 'Staff Member', true, true)"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
        conn.execute(
            text(
                "INSERT INTO staff_role_assignments (id, user_id, role) VALUES (:id, :user, :role)"
            ),
            {"id": str(uuid4()), "user": user_id, "role": role},
        )


@pytest.fixture
def media_engine(pg_engine: Engine) -> Engine:
    _alembic(pg_engine, "downgrade", MEDIA)
    return pg_engine


def test_upgrade_downgrade_upgrade_keeps_existing_catalogue_rows(media_engine: Engine):
    pg_engine = media_engine
    for table, columns in NEW_COLUMNS.items():
        assert columns <= _columns(pg_engine, table), table
    ids = _catalogue(pg_engine)
    with pg_engine.connect() as conn:
        featured, original = conn.execute(
            text(
                "SELECT p.is_featured, i.original_key FROM products p "
                "JOIN product_images i ON i.product_id = p.id WHERE p.id = :id"
            ),
            {"id": ids["product"]},
        ).one()
    assert (featured, original) == (False, None)  # existing rows: defaults, nothing invented

    _alembic(pg_engine, "downgrade", BEFORE)
    for table, columns in NEW_COLUMNS.items():
        assert columns.isdisjoint(_columns(pg_engine, table)), table
    _alembic(pg_engine, "upgrade", MEDIA)
    with pg_engine.connect() as conn:
        key: str = conn.execute(
            text("SELECT storage_key FROM product_images WHERE id = :id"), {"id": ids["image"]}
        ).scalar_one()
    assert key == "products/" + "a" * 32 + ".jpg"


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE categories SET image_key = 'k' WHERE id = :id",  # no size
        "UPDATE categories SET image_key = 'k', image_width = 0, image_height = 5 WHERE id = :id",
        "UPDATE categories SET image_width = 5, image_height = 5 WHERE id = :id",  # no key
        "UPDATE categories SET description = repeat('x', 501) WHERE id = :id",
    ],
)
def test_category_image_constraints(media_engine: Engine, statement: str):
    pg_engine = media_engine
    ids = _catalogue(pg_engine)
    with pytest.raises(Exception), pg_engine.begin() as conn:  # noqa: B017, PT011
        conn.execute(text(statement), {"id": ids["category"]})


def test_brand_logo_constraints(media_engine: Engine):
    pg_engine = media_engine
    ids = _catalogue(pg_engine)
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        conn.execute(text("UPDATE brands SET logo_key = 'k' WHERE id = :id"), {"id": ids["brand"]})
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE brands SET logo_key = 'k', logo_width = 10, logo_height = 10 WHERE id = :id"
            ),
            {"id": ids["brand"]},
        )


def test_the_finance_role_is_accepted_and_blocks_its_own_downgrade(pg_engine: Engine):
    _staff(pg_engine, "finance")
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        conn.execute(
            text("UPDATE staff_role_assignments SET role = 'auditor' WHERE role = 'finance'")
        )
    with pytest.raises(RuntimeError, match="hold the finance role"):
        _alembic(pg_engine, "downgrade", BEFORE)
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE staff_role_assignments SET role = 'management'"))
    _alembic(pg_engine, "downgrade", BEFORE)
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        conn.execute(text("UPDATE staff_role_assignments SET role = 'finance'"))
    _alembic(pg_engine, "upgrade", FINANCE)
    _alembic(pg_engine, "upgrade", MEDIA)


def test_models_match_the_migrated_schema(pg_engine: Engine):
    _alembic(pg_engine, "check")  # raises if autogenerate would find any difference
