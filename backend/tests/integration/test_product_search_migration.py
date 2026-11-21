"""Product full-text search migration (module 9, revision a3b4d2f1d8e6).

Runs on the disposable per-test schema of the *_test database (tests/conftest.py pg_engine).
"""

from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from tests.integration.test_image_media_migration import _alembic

BEFORE = "9d820b74f718"
SEARCH = "a3b4d2f1d8e6"
FUNCTIONS = {
    "product_search_text",
    "product_search_document",
    "products_search_vector_refresh",
    "brands_search_vector_refresh",
}
TRIGGERS = {"products_search_vector", "brands_search_vector"}


def _objects(engine: Engine) -> tuple[set[str], set[str], set[str]]:
    with engine.connect() as conn:
        functions: set[str] = set(
            conn.execute(
                text(
                    "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = current_schema()"
                )
            ).scalars()
        )
        triggers: set[str] = set(
            conn.execute(
                text(
                    "SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = current_schema() AND NOT t.tgisinternal"
                )
            ).scalars()
        )
    columns = {c["name"] for c in inspect(engine).get_columns("products")}
    return functions & FUNCTIONS, triggers & TRIGGERS, columns


def _legacy_product(engine: Engine) -> str:
    ids = [str(uuid4()) for _ in range(3)]
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO categories (id, name, slug) VALUES (:id, 'Phones', :slug)"),
            {"id": ids[0], "slug": f"phones-{ids[0]}"},
        )
        conn.execute(
            text("INSERT INTO brands (id, name, slug) VALUES (:id, 'Tecno', :slug)"),
            {"id": ids[1], "slug": f"tecno-{ids[1]}"},
        )
        conn.execute(
            text(
                "INSERT INTO products (id, name, slug, model, category_id, brand_id) "
                "VALUES (:id, 'Spark 20', :slug, 'KJ-5', :category, :brand)"
            ),
            {"id": ids[2], "slug": f"spark-{ids[2]}", "category": ids[0], "brand": ids[1]},
        )
    return ids[2]


def test_upgrade_backfills_existing_products_and_downgrade_removes_everything(
    pg_engine: Engine,
):
    _alembic(pg_engine, "downgrade", BEFORE)
    assert _objects(pg_engine)[:2] == (set(), set())
    assert "search_vector" not in _objects(pg_engine)[2]
    product_id = _legacy_product(pg_engine)

    _alembic(pg_engine, "upgrade", SEARCH)
    functions, triggers, columns = _objects(pg_engine)
    assert (functions, triggers) == (FUNCTIONS, TRIGGERS) and "search_vector" in columns
    with pg_engine.connect() as conn:
        stored = conn.execute(
            text("SELECT name, model, search_vector::text FROM products WHERE id = :id"),
            {"id": product_id},
        ).one()
    assert stored[:2] == ("Spark 20", "KJ-5")  # data unchanged
    assert stored[2] == "'-5':4B '20':2A '5':6B 'kj':3B,5B 'kj5':7B 'spark':1A 'tecno':8C"

    _alembic(pg_engine, "downgrade", BEFORE)
    assert _objects(pg_engine)[:2] == (set(), set())
    with pg_engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT name FROM products WHERE id = :id"), {"id": product_id}
            ).scalar_one()
            == "Spark 20"
        )
    _alembic(pg_engine, "upgrade", "head")


def test_models_match_the_migrated_schema(pg_engine: Engine):
    _alembic(pg_engine, "check")
