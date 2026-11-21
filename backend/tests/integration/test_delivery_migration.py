"""Delivery zones, fee history and settings migration (module 12, revision b6f1d3a9c8e4).

Runs on the disposable per-test schema of the *_test database (tests/conftest.py pg_engine).
"""

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from alembic import command
from app.core.config import get_settings

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
BEFORE = "a3b4d2f1d8e6"
DELIVERY = "b6f1d3a9c8e4"
NEW_ZONE_COLUMNS = {"district", "cod_available", "sort_order"}


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


def _legacy_zone(engine: Engine, name: str, code: str, coverage: dict | None = None) -> str:
    zone_id = str(uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO delivery_zones (id, code, name, coverage) "
                "VALUES (:id, :code, :name, CAST(:coverage AS jsonb))"
            ),
            {"id": zone_id, "code": code, "name": name, "coverage": json.dumps(coverage or {})},
        )
    return zone_id


def _legacy_rule(engine: Engine, zone_id: str, fee: int, *, active=True, data=None) -> str:
    rule_id = str(uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO delivery_fee_rules (id, zone_id, fee, is_active, rule_data) "
                "VALUES (:id, :zone, :fee, :active, CAST(:data AS jsonb))"
            ),
            {
                "id": rule_id,
                "zone": zone_id,
                "fee": fee,
                "active": active,
                "data": json.dumps(data or {}),
            },
        )
    return rule_id


def test_head_has_the_approved_columns_indexes_and_settings_table(pg_engine: Engine):
    inspector = inspect(pg_engine)
    assert NEW_ZONE_COLUMNS <= _columns(pg_engine, "delivery_zones")
    assert "coverage" not in _columns(pg_engine, "delivery_zones")
    assert "rule_data" not in _columns(pg_engine, "delivery_fee_rules")
    assert _columns(pg_engine, "settings") == {"key", "value", "updated_by_user_id", "updated_at"}
    uniques = {u["name"] for u in inspector.get_unique_constraints("delivery_zones")}
    assert {"delivery_zone_code", "delivery_zone_district"} <= uniques
    indexes = {i["name"]: i for i in inspector.get_indexes("delivery_fee_rules")}
    one_active = indexes["uq_delivery_fee_rules_one_active_per_zone"]
    assert one_active["unique"] and one_active["column_names"] == ["zone_id"]
    assert "is_active" in str(one_active["dialect_options"]["postgresql_where"])
    assert "ix_delivery_fee_rules_zone_active" not in indexes
    checks = {c["name"] for c in inspector.get_check_constraints("delivery_zones")}
    assert "ck_delivery_zones_supported_district" in checks
    with pg_engine.connect() as conn:  # no seed data in the migration
        assert conn.execute(text("SELECT count(*) FROM delivery_zones")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM settings")).scalar() == 0


def test_alembic_check_finds_no_drift(pg_engine: Engine):
    _alembic(pg_engine, "check")


def test_downgrade_then_upgrade_keeps_legacy_zones_and_fee_history(pg_engine: Engine):
    _alembic(pg_engine, "downgrade", BEFORE)
    assert NEW_ZONE_COLUMNS.isdisjoint(_columns(pg_engine, "delivery_zones"))
    assert "settings" not in inspect(pg_engine).get_table_names()
    zone_id = _legacy_zone(pg_engine, " kicukiro ", "zone-k")  # matched by name
    by_code = _legacy_zone(pg_engine, "Southern Kigali", "Gasabo")  # matched by code
    old_rule = _legacy_rule(pg_engine, zone_id, 1800, active=False)
    new_rule = _legacy_rule(pg_engine, zone_id, 2000)

    _alembic(pg_engine, "upgrade", DELIVERY)
    with pg_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, district, cod_available, sort_order FROM delivery_zones ORDER BY code")
        ).all()
        assert [(str(r.id), r.district, r.cod_available, r.sort_order) for r in rows] == [
            (by_code, "Gasabo", True, 0),
            (zone_id, "Kicukiro", True, 0),
        ]
        kept = conn.execute(
            text("SELECT id, fee, is_active FROM delivery_fee_rules ORDER BY fee")
        ).all()
    assert [(str(r.id), r.fee, r.is_active) for r in kept] == [
        (old_rule, 1800, False),
        (new_rule, 2000, True),
    ]

    _alembic(pg_engine, "downgrade", BEFORE)  # and back again, still keeping the rows
    with pg_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM delivery_fee_rules")).scalar() == 2
        assert conn.execute(text("SELECT coverage FROM delivery_zones LIMIT 1")).scalar() == {}
    _alembic(pg_engine, "upgrade", DELIVERY)
    assert _version(pg_engine) == DELIVERY


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        (lambda e: _legacy_zone(e, "Kigali City", "kigali"), "district cannot be determined"),
        (
            lambda e: _legacy_zone(e, "Gasabo", "gasabo", coverage={"sectors": ["Remera"]}),
            "coverage holds data",
        ),
        (
            lambda e: _legacy_rule(e, _legacy_zone(e, "Gasabo", "g"), 1, data={"min": 1}),
            "rule_data holds data",
        ),
        (
            lambda e: [
                _legacy_rule(e, z, f) for z in [_legacy_zone(e, "Gasabo", "g")] for f in (1, 2)
            ],
            "more than one active fee rule",
        ),
    ],
)
def test_upgrade_refuses_data_it_cannot_carry_over_and_changes_nothing(
    pg_engine: Engine, setup, reason
):
    _alembic(pg_engine, "downgrade", BEFORE)
    setup(pg_engine)
    with pytest.raises(RuntimeError, match=reason):
        _alembic(pg_engine, "upgrade", DELIVERY)
    assert _version(pg_engine) == BEFORE
    assert "coverage" in _columns(pg_engine, "delivery_zones")
    assert "rule_data" in _columns(pg_engine, "delivery_fee_rules")
    assert NEW_ZONE_COLUMNS.isdisjoint(_columns(pg_engine, "delivery_zones"))
