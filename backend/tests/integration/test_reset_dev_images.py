"""scripts/reset_dev_images.py (approved 2026-10-26): development only, local host only, needs
--confirm, and deletes image rows and image files only.

Runs on the disposable per-test PostgreSQL schema (tests/conftest.py); it never touches a real
database.
"""

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import Brand, Category, MediaObject, Product, ProductImage
from tests.integration.test_image_media_migration import _alembic
from tests.support.media import image_row, media_pair
from tests.support.sellers import new_store

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "reset_dev_images.py"
_spec = importlib.util.spec_from_file_location("reset_dev_images", SCRIPT)
assert _spec is not None and _spec.loader is not None
reset_dev_images = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reset_dev_images)


def settings(monkeypatch, **values: str | None) -> None:
    defaults: dict[str, str | None] = {
        "APP_ENV": "development",
        "MIGRATION_DATABASE_URL": "postgresql+psycopg://owner:secret@127.0.0.1:5432/dev",
    }
    defaults.update(values)
    monkeypatch.setattr(reset_dev_images, "explicit_setting", lambda name: defaults.get(name))


@pytest.mark.parametrize(
    ("values", "args", "reason"),
    [
        ({"APP_ENV": None}, ["--confirm"], "APP_ENV=development"),
        ({"APP_ENV": "staging"}, ["--confirm"], "APP_ENV=development"),
        (
            {"MIGRATION_DATABASE_URL": "postgresql+psycopg://o:s@db.example.com:5432/x"},
            ["--confirm"],
            "not local",
        ),
        ({"MIGRATION_DATABASE_URL": None}, ["--confirm"], "MIGRATION_DATABASE_URL"),
        ({}, [], "--confirm"),
    ],
    ids=["no-app-env", "staging", "remote-host", "no-owner-url", "no-confirm"],
)
def test_it_refuses_unless_development_local_and_confirmed(
    monkeypatch, capsys, values, args, reason
):
    settings(monkeypatch, **values)
    connected = []
    monkeypatch.setattr(reset_dev_images, "create_engine", lambda *a, **k: connected.append(1))
    assert reset_dev_images.main(args) == 2
    captured = capsys.readouterr()
    assert reason in captured.err
    assert "secret" not in captured.out + captured.err
    assert connected == []  # refused before any connection


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1", "db"])
def test_local_hosts_include_the_compose_database_service(host):
    assert reset_dev_images.is_local_host(host)


@pytest.mark.parametrize("host", [None, "10.0.0.5", "postgres.internal", "db.example.com"])
def test_other_hosts_are_not_local(host):
    assert not reset_dev_images.is_local_host(host)


def test_it_deletes_image_rows_and_links_only(db: Session, pg_engine: Engine):
    category = Category(name="Phones", slug="phones")
    brand = Brand(name="Tecno", slug="tecno")
    product = Product(store=new_store(), name="Spark", slug="spark", category=category, brand=brand)
    image = image_row(None, 0)
    image.product = product
    logo, logo_original = media_pair("brands/logo.png", "brands", uuid.uuid4())
    logo.id, logo_original.id = uuid.uuid4(), uuid.uuid4()
    db.add_all([logo, logo_original])
    db.flush()
    brand.logo_media_id, brand.logo_original_media_id = logo.id, logo_original.id
    db.add_all([category, brand, product, image])
    db.commit()

    with pg_engine.begin() as conn:
        counts = reset_dev_images.reset(conn)
    assert counts == {
        "product images": 1,
        "categories images": 0,
        "brands logos": 1,
        "media registry rows": 4,
    }
    db.expire_all()
    assert db.scalar(select(func.count(ProductImage.id))) == 0
    assert db.scalar(select(func.count(MediaObject.id))) == 0
    assert db.scalar(select(func.count(Product.id))) == 1  # products, brands, categories stay
    kept = db.get(Brand, brand.id)
    assert kept is not None and kept.logo_media_id is None


def test_it_also_works_on_the_schema_before_the_registry(pg_engine: Engine):
    _alembic(pg_engine, "downgrade", "b8d3f5a1c2e7")
    with pg_engine.begin() as conn:
        category = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO categories (id, name, slug, image_key, image_width, image_height) "
                "VALUES (:id, 'Phones', 'phones', 'c.png', 5, 5)"
            ),
            {"id": category},
        )
    with pg_engine.begin() as conn:
        counts = reset_dev_images.reset(conn)
    assert counts == {"product images": 0, "categories images": 1, "brands logos": 0}
    with pg_engine.connect() as conn:
        assert conn.execute(text("SELECT image_key FROM categories")).scalar() is None
    _alembic(pg_engine, "upgrade", "head")  # the registry migration now runs
