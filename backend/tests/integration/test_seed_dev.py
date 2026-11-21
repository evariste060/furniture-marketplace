"""scripts/seed_dev.py (module 12 development placeholders; plan §2 and §5).

Runs on the disposable per-test PostgreSQL schema (tests/conftest.py); it never touches a real
database.
"""

import importlib.util
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import DeliveryFeeRule, DeliveryZone, Setting

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "seed_dev.py"
_spec = importlib.util.spec_from_file_location("seed_dev", SCRIPT)
assert _spec is not None and _spec.loader is not None
seed_dev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_dev)

THRESHOLD = "delivery.free_delivery_threshold"


def _fees(db: Session) -> dict[str, list[tuple[int, bool]]]:
    db.expire_all()
    rows = db.execute(
        select(DeliveryZone.district, DeliveryFeeRule.fee, DeliveryFeeRule.is_active)
        .join(DeliveryFeeRule, DeliveryFeeRule.zone_id == DeliveryZone.id)
        .order_by(DeliveryZone.district, DeliveryFeeRule.created_at)
    )
    fees: dict[str, list[tuple[int, bool]]] = {}
    for district, fee, active in rows:
        fees.setdefault(district, []).append((fee, active))
    return fees


def _threshold(db: Session) -> Setting:
    setting = db.get(Setting, THRESHOLD)
    assert setting is not None
    return setting


def test_seed_adds_the_placeholder_zones_and_threshold_once(db: Session):
    created = seed_dev.seed(db)
    assert len(created) == 4
    assert _fees(db) == {
        "Gasabo": [(2000, True)],
        "Kicukiro": [(2000, True)],
        "Nyarugenge": [(1500, True)],
    }
    assert _threshold(db).value == 50_000
    codes = db.scalars(select(DeliveryZone.code).order_by(DeliveryZone.sort_order)).all()
    assert codes == ["nyarugenge", "kicukiro", "gasabo"]
    assert seed_dev.seed(db) == []  # rerun: nothing duplicated
    assert db.scalar(select(func.count(DeliveryZone.id))) == 3
    assert db.scalar(select(func.count(DeliveryFeeRule.id))) == 3


def test_rerun_never_overwrites_changed_values_or_history(db: Session):
    seed_dev.seed(db)
    gasabo = db.scalar(select(DeliveryZone).where(DeliveryZone.district == "Gasabo"))
    assert gasabo is not None
    rule = db.scalar(select(DeliveryFeeRule).where(DeliveryFeeRule.zone_id == gasabo.id))
    assert rule is not None
    rule.is_active = False
    db.flush()
    db.add(DeliveryFeeRule(zone_id=gasabo.id, fee=2500))
    _threshold(db).value = 150_000
    db.commit()
    assert seed_dev.seed(db) == []
    assert _fees(db)["Gasabo"] == [(2000, False), (2500, True)]
    assert _threshold(db).value == 150_000


def test_seed_fills_only_what_is_missing(db: Session):
    db.add(DeliveryZone(code="kicukiro-east", name="Kicukiro", district="Kicukiro"))
    db.commit()
    created = seed_dev.seed(db)
    assert created == [
        "zone nyarugenge (1500 RWF)",
        "zone gasabo (2000 RWF)",
        f"{THRESHOLD} = 50000",
    ]
    assert "Kicukiro" not in _fees(db)  # the existing zone is left alone, without a fee


@pytest.fixture
def no_app_env(monkeypatch, tmp_path):
    """No APP_ENV in the process environment, and an .env file without it. monkeypatch restores
    both afterwards; the real backend/.env is never read or changed."""
    monkeypatch.delenv("APP_ENV", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("LOG_LEVEL=INFO\n", encoding="utf8")
    monkeypatch.setattr(seed_dev, "ENV_FILE", env_file)
    return env_file


def _no_database(*args, **kwargs):
    raise AssertionError("a refused seed must not load settings or connect to a database")


def test_an_unset_app_env_is_refused_before_settings_or_a_connection(
    no_app_env, monkeypatch, capsys
):
    # With no APP_ENV anywhere, Settings would default to development; the seed must not rely
    # on that default.
    assert Settings(_env_file=None).app_env == "development"  # type: ignore[call-arg]
    monkeypatch.setattr(seed_dev, "get_settings", _no_database)
    monkeypatch.setattr(seed_dev, "create_engine", _no_database)
    assert seed_dev.explicit_app_env() is None
    assert seed_dev.main() == 2
    assert "APP_ENV=development is set explicitly" in capsys.readouterr().err


@pytest.mark.parametrize("where", ["environment", "env_file"])
@pytest.mark.parametrize("value", ["staging", "production", "", "Development"])
def test_any_other_explicit_value_is_refused(no_app_env, monkeypatch, capsys, where, value):
    if where == "environment":
        monkeypatch.setenv("APP_ENV", value)
    else:
        no_app_env.write_text(f"APP_ENV={value}\n", encoding="utf8")
    monkeypatch.setattr(seed_dev, "get_settings", _no_database)
    monkeypatch.setattr(seed_dev, "create_engine", _no_database)
    assert seed_dev.main() == 2
    assert "APP_ENV=development" in capsys.readouterr().err


def test_the_environment_overrides_the_env_file(no_app_env, monkeypatch):
    no_app_env.write_text("APP_ENV=development\n", encoding="utf8")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(seed_dev, "create_engine", _no_database)
    assert seed_dev.explicit_app_env() == "production"
    assert seed_dev.main() == 2


@pytest.mark.parametrize("where", ["environment", "env_file"])
def test_explicit_development_seeds_the_disposable_test_schema(
    no_app_env, monkeypatch, capsys, pg_engine: Engine, where
):
    if where == "environment":
        monkeypatch.setenv("APP_ENV", "development")
    else:
        no_app_env.write_text("APP_ENV=development\n", encoding="utf8")
    url = pg_engine.url
    assert url.database == "rwanda_ecommerce_test"  # only the per-test schema of the test DB
    settings = Settings(
        app_env="development",
        database_url=SecretStr(url.render_as_string(False)),
    )  # type: ignore[call-arg]  # AUDIT_HMAC_KEY comes from the test environment
    monkeypatch.setattr(seed_dev, "get_settings", lambda: settings)
    assert seed_dev.main() == 0
    assert "development placeholders" in capsys.readouterr().out
    with pg_engine.connect() as conn:
        assert conn.execute(select(func.count(DeliveryZone.id))).scalar() == 3
    assert seed_dev.main() == 0  # rerun
    assert "Nothing to seed" in capsys.readouterr().out
