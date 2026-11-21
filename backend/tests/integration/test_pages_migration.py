"""Module 19 migrations on a disposable per-test schema of the *_test database (tests/conftest.py
pg_engine):

- edebaf558c2d (the module 19 first merged into dev) creates `pages` after e4b9c1f7a3d6;
- b2f6d8e4a1c9 joins that head with the frontend phase 1 head, gives `pages` the module 19 shape
  that replaced it (owner decision 2026-10-29) and adds `quote_requests`. Pages written before
  it are kept."""

import uuid

import pytest
from sqlalchemy import String, inspect, text
from sqlalchemy.engine import Engine

from tests.integration.test_payment_migration import _alembic

BEFORE = "e4b9c1f7a3d6"
DEV_PAGES = "edebaf558c2d"
MODULE_19 = "b2f6d8e4a1c9"


def _checks(engine: Engine) -> set[str | None]:
    return {c["name"] for c in inspect(engine).get_check_constraints("pages")}


def _uniques(engine: Engine) -> set[tuple[str | None, tuple[str, ...]]]:
    return {
        (u["name"], tuple(u["column_names"]))
        for u in inspect(engine).get_unique_constraints("pages")
    }


def test_dev_pages_table_is_created_and_removed_by_a_round_trip(pg_engine: Engine):
    assert "pages" in inspect(pg_engine).get_table_names()
    _alembic(pg_engine, "downgrade", BEFORE)
    assert "pages" not in inspect(pg_engine).get_table_names()
    _alembic(pg_engine, "upgrade", DEV_PAGES)
    assert ("uq_pages_slug_locale", ("slug", "locale")) in _uniques(pg_engine)
    [fk] = inspect(pg_engine).get_foreign_keys("pages")
    assert fk["referred_table"] == "users" and fk["constrained_columns"] == ["updated_by_user_id"]
    assert fk["options"].get("ondelete") == "SET NULL"  # deleting an editor keeps the page
    assert {
        "ck_pages_slug_format",
        "ck_pages_valid_locale",
        "ck_pages_title_not_blank",
        "ck_pages_body_length",
    } <= _checks(pg_engine)


def test_module_19_reshapes_pages_keeps_their_rows_and_adds_quote_requests(pg_engine: Engine):
    _alembic(pg_engine, "downgrade", DEV_PAGES)
    assert "quote_requests" not in inspect(pg_engine).get_table_names()
    page_id = uuid.uuid4()
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO pages (id, slug, locale, title, body) "
                "VALUES (:id, 'warranty', 'en', 'Warranty', 'Text.')"
            ),
            {"id": page_id},
        )
    _alembic(pg_engine, "upgrade", MODULE_19)
    assert ("slug_locale", ("slug", "locale")) in _uniques(pg_engine)
    checks = _checks(pg_engine)
    assert {"ck_pages_locale_valid", "ck_pages_title_present", "ck_pages_slug_format"} <= checks
    assert not {"ck_pages_valid_locale", "ck_pages_title_not_blank"} & checks
    columns = {c["name"]: c for c in inspect(pg_engine).get_columns("pages")}
    slug_type, title_type = columns["slug"]["type"], columns["title"]["type"]
    assert isinstance(slug_type, String) and isinstance(title_type, String)
    assert slug_type.length == 60 and title_type.length == 120
    assert "quote_requests" in inspect(pg_engine).get_table_names()
    with pg_engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT title FROM pages WHERE id = :id"), {"id": page_id}
            ).scalar_one()
            == "Warranty"
        )

    _alembic(pg_engine, "downgrade", DEV_PAGES)  # back to the dev shape, rows kept
    assert ("uq_pages_slug_locale", ("slug", "locale")) in _uniques(pg_engine)
    assert "ck_pages_title_not_blank" in _checks(pg_engine)
    assert "quote_requests" not in inspect(pg_engine).get_table_names()
    with pg_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM pages")).scalar_one() == 1


def test_module_19_refuses_pages_that_do_not_fit(pg_engine: Engine):
    _alembic(pg_engine, "downgrade", DEV_PAGES)
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO pages (id, slug, locale, title, body) "
                "VALUES (:id, 'warranty', 'en', :title, 'Text.')"
            ),
            {"id": uuid.uuid4(), "title": "T" * 150},
        )
    with pytest.raises(RuntimeError, match="shorten them before upgrading"):
        _alembic(pg_engine, "upgrade", MODULE_19)


def test_alembic_check_finds_no_drift(pg_engine: Engine):
    _alembic(pg_engine, "check")
