"""ADR-014 phase 6 migration f2a4c6e8b0d1: furniture service icons.

Runs on the disposable per-test schema of the *_test database (tests/conftest.py pg_engine).
"""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from tests.integration.test_image_media_migration import _alembic
from tests.integration.test_products_store_migration import HEAD, _revision

PHASE3 = "c6e8a0b2d4f7"


def _service(engine: Engine, icon: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO service_categories (id, slug, name_en, icon, short_description_en, "
                "intro_en) VALUES (:id, :slug, 'Assembly', :icon, 'Card', 'Intro')"
            ),
            {"id": str(uuid4()), "slug": f"svc-{uuid4().hex[:8]}", "icon": icon},
        )


def test_furniture_icons_are_allowed_and_the_old_ones_stay_valid(pg_engine: Engine):
    assert _revision(pg_engine) == HEAD
    for icon in ("hammer", "truck", "ruler", "sofa", "paintbrush", "wrench", "cctv"):
        _service(pg_engine, icon)
    with pytest.raises(IntegrityError, match="ck_service_categories_icon_valid"):
        _service(pg_engine, "rocket")
    _alembic(pg_engine, "check")  # the models match the migrated schema


def test_the_downgrade_refuses_while_a_service_uses_a_furniture_icon(pg_engine: Engine):
    _service(pg_engine, "sofa")
    with pytest.raises(Exception, match="ck_service_categories_icon_valid"):
        _alembic(pg_engine, "downgrade", PHASE3)
    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM service_categories"))
    _alembic(pg_engine, "downgrade", PHASE3)
    assert _revision(pg_engine) == PHASE3
    _alembic(pg_engine, "upgrade", HEAD)
    assert _revision(pg_engine) == HEAD
