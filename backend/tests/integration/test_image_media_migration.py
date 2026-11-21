"""Product image media columns migration (module 7, revision 76768b844c03).

Runs on the disposable per-test schema of the *_test database (tests/conftest.py pg_engine).
These columns were replaced by the media registry (revision c4e8f2a6b9d1), so the tests run at
the last revision that has them.
"""

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
BEFORE = "37b61c6765c1"
MEDIA = "76768b844c03"
NEW_COLUMNS = {"thumbnail_key", "width", "height"}
BEFORE_REGISTRY = "b8d3f5a1c2e7"  # the last revision with these columns


def _alembic(engine: Engine, action: str, *args: str) -> None:
    previous = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = engine.url.render_as_string(hide_password=False)
    get_settings.cache_clear()
    try:
        getattr(command, action)(Config(str(ALEMBIC_INI)), *args)
    finally:
        os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


def _columns(engine: Engine) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns("product_images")}


def _legacy_image(engine: Engine) -> str:
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
                "INSERT INTO product_images (id, product_id, storage_key, alt_text) "
                "VALUES (:id, :product, 'product/legacy.jpg', 'Legacy')"
            ),
            {"id": ids[2], "product": ids[1]},
        )
    return ids[2]


@pytest.fixture
def module_7_engine(pg_engine: Engine) -> Engine:
    _alembic(pg_engine, "downgrade", BEFORE_REGISTRY)
    return pg_engine


def test_upgrade_downgrade_upgrade_keeps_existing_images(module_7_engine: Engine):
    pg_engine = module_7_engine
    assert NEW_COLUMNS <= _columns(pg_engine)
    image_id = _legacy_image(pg_engine)

    _alembic(pg_engine, "downgrade", BEFORE)
    assert NEW_COLUMNS.isdisjoint(_columns(pg_engine))
    with pg_engine.connect() as conn:
        row = conn.execute(
            text("SELECT storage_key, alt_text FROM product_images WHERE id = :id"),
            {"id": image_id},
        ).one()
    assert tuple(row) == ("product/legacy.jpg", "Legacy")

    _alembic(pg_engine, "upgrade", MEDIA)
    assert NEW_COLUMNS <= _columns(pg_engine)
    with pg_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT storage_key, thumbnail_key, width, height FROM product_images "
                "WHERE id = :id"
            ),
            {"id": image_id},
        ).one()
    assert tuple(row) == ("product/legacy.jpg", None, None, None)


@pytest.mark.parametrize(
    "assignment",
    ["width = 0, height = 10", "width = 10, height = -1", "width = 10, height = NULL"],
    ids=["zero-width", "negative-height", "width-without-height"],
)
def test_constraints_reject_invalid_dimensions(module_7_engine: Engine, assignment: str):
    pg_engine = module_7_engine
    image_id = _legacy_image(pg_engine)
    with pytest.raises(IntegrityError):
        with pg_engine.begin() as conn:
            conn.execute(
                text(f"UPDATE product_images SET {assignment} WHERE id = :id"), {"id": image_id}
            )


def test_valid_dimensions_and_thumbnail_are_accepted(module_7_engine: Engine):
    pg_engine = module_7_engine
    image_id = _legacy_image(pg_engine)
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE product_images SET width = 1600, height = 900, "
                "thumbnail_key = 'products/x_thumb.jpg' WHERE id = :id"
            ),
            {"id": image_id},
        )


def test_models_match_the_migrated_schema(pg_engine: Engine):
    _alembic(pg_engine, "check")  # raises if autogenerate would find any difference
