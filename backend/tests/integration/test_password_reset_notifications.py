"""Module 17 × module 2: password-reset codes go through the notification provider abstraction
without weakening the reset rules. Codes reach nobody through the mock, are never logged or
written to notification_logs, and a delivery failure leaves the issued code valid."""

import logging
import re
from collections.abc import Iterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.notifications import (
    ConsoleProvider,
    DeliveryTimeout,
    get_message_sender,
    get_notification_provider,
)
from app.main import app
from app.models import NotificationLog
from app.models.operations import AuditRecord
from app.models.session import PasswordResetCode
from tests.integration.test_password_reset_api import EMAIL, FORGOT, PHONE, reset
from tests.support.messages import ScriptedProvider


@pytest.fixture
def failing_sender(client) -> Iterator[ScriptedProvider]:
    provider = ScriptedProvider()
    app.dependency_overrides[get_message_sender] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_message_sender, None)


def sent_code(provider: ScriptedProvider) -> str:
    match = re.search(r"\b(\d{6})\b", provider.messages[-1].text)
    assert match
    return match.group(1)


@pytest.mark.parametrize("failure", [RuntimeError("smtp said: bad auth"), DeliveryTimeout()])
def test_a_delivery_failure_keeps_the_reply_and_the_code_valid_and_leaks_nothing(
    client, db: Session, customer_auth: dict, failing_sender: ScriptedProvider, caplog, failure
):
    failing_sender.outcomes = [failure]
    with caplog.at_level(logging.DEBUG):
        res = client.post(FORGOT, json={"identifier": EMAIL})
    assert res.status_code == 202  # same reply as a successful send: nothing to enumerate
    code = sent_code(failing_sender)  # the provider received it, then failed
    assert failing_sender.messages[-1].idempotency_key.startswith("password-reset:")
    assert code not in caplog.text and EMAIL not in caplog.text and "bad auth" not in caplog.text
    assert "Password reset code not delivered" in caplog.text
    assert reset(client, code).status_code == 200  # the issued code still works, once
    assert reset(client, code).status_code == 422


def test_reset_codes_are_never_stored_in_the_notification_log_or_audit(
    client, db: Session, customer_auth: dict, failing_sender: ScriptedProvider
):
    assert client.post(FORGOT, json={"identifier": PHONE}).status_code == 202
    code = sent_code(failing_sender)
    assert failing_sender.messages[-1].channel == "sms"
    assert reset(client, code).status_code == 200
    db.expire_all()
    assert db.scalar(select(func.count(NotificationLog.id))) == 0
    summaries = " ".join(str(a.change_summary) for a in db.scalars(select(AuditRecord)))
    assert code not in summaries
    assert all(code not in row.code_hash for row in db.scalars(select(PasswordResetCode)))


def test_the_mock_provider_cannot_deliver_reset_codes(
    client, db: Session, customer_auth, monkeypatch
):
    monkeypatch.setattr(get_settings(), "notification_provider", "mock")
    assert get_notification_provider() is not None  # order notifications use the mock...
    forgot = client.post(FORGOT, json={"identifier": EMAIL})
    reset_res = reset(client, "123456")
    for res in (forgot, reset_res):  # ...but a reset code must reach the person: 503
        assert res.status_code == 503
        assert res.json()["error"]["code"] == "password_reset_unavailable"
    db.expire_all()
    assert db.scalar(select(func.count(PasswordResetCode.id))) == 0


@pytest.mark.parametrize(
    ("configured", "expected"), [("none", None), ("mock", None), ("console", ConsoleProvider)]
)
def test_only_a_provider_that_reaches_the_person_sends_reset_codes(
    monkeypatch, configured, expected
):
    monkeypatch.setattr(get_settings(), "notification_provider", configured)
    sender = get_message_sender()
    assert (sender is None) if expected is None else isinstance(sender, expected)
