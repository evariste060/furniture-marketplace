"""scripts/mock_payment.py (frontend phase 4, decision 3 of 2026-10-27): settles a mock
mobile-money payment in development through the real webhook handler. Runs on the disposable
per-test PostgreSQL schema; it never touches a real database."""

import importlib.util
import os
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from tests.integration.test_payments_api import delivery, momo_order, started  # noqa: F401

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "mock_payment.py"
_spec = importlib.util.spec_from_file_location("mock_payment", SCRIPT)
assert _spec is not None and _spec.loader is not None
mock_payment = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mock_payment)

SECRET = os.environ["PAYMENT_MOCK_WEBHOOK_SECRET"]


def test_succeed_pays_the_open_request(client, db: Session, delivery):  # noqa: F811
    order, _ = started(client, db)
    line = mock_payment.settle(
        db, order["order_number"].lower(), succeed=True, reason="declined", secret=SECRET
    )
    assert line == f"{order['order_number']}: event processed; payment succeeded."


def test_fail_records_the_reason_code(client, db: Session, delivery):  # noqa: F811
    order, _ = started(client, db)
    line = mock_payment.settle(
        db, order["order_number"], succeed=False, reason="insufficient_funds", secret=SECRET
    )
    assert line.endswith("payment failed.")


def test_an_order_without_an_open_request_is_refused(client, db: Session, delivery):  # noqa: F811
    order = momo_order(client, db)  # placed, never initiated
    with pytest.raises(LookupError, match="no mock mobile-money request"):
        mock_payment.settle(
            db, order["order_number"], succeed=True, reason="declined", secret=SECRET
        )


def test_a_wrong_secret_is_refused_by_the_webhook_check(client, db: Session, delivery):  # noqa: F811
    order, _ = started(client, db)
    with pytest.raises(Exception, match="verified"):
        mock_payment.settle(
            db, order["order_number"], succeed=True, reason="declined", secret="x" * 40
        )


def _no_database(*args, **kwargs):
    raise AssertionError("a refused run must not load settings or connect to a database")


@pytest.mark.parametrize("value", [None, "staging", "production"])
def test_it_runs_only_in_development(monkeypatch, capsys, value):
    monkeypatch.setattr(mock_payment, "explicit_app_env", lambda: value)
    monkeypatch.setattr(mock_payment, "get_settings", _no_database)
    monkeypatch.setattr(mock_payment, "create_engine", _no_database)
    assert mock_payment.main(["ORD-261027-ABCDEF", "--succeed"]) == 2
    assert "APP_ENV=development" in capsys.readouterr().err
