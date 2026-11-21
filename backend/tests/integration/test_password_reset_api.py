"""Forgot / reset password (module 2). Customers only; codes are 6 digits, 15 minutes, 5 tries."""

import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.notifications import get_message_sender
from app.main import app
from app.models.identity import User
from app.models.operations import AuditRecord
from app.models.session import PasswordResetCode
from tests.conftest import make_staff
from tests.support.memory_rate_limit import FakeClock
from tests.support.messages import RecordingSender

FORGOT = "/api/v1/auth/forgot-password"
RESET = "/api/v1/auth/reset-password"
LOGIN = "/api/v1/auth/login"
EMAIL = "customer.a@example.com"
PHONE = "+250788111222"
OLD_PASSWORD = "SecurePassword123!"
NEW_PASSWORD = "Brand-New-Pass-42"
GENERIC_REPLY = (
    "If an account matches this email or phone number, a reset code has been sent. "
    "It expires in 15 minutes."
)


@pytest.fixture
def sender() -> Iterator[RecordingSender]:
    recording = RecordingSender()
    app.dependency_overrides[get_message_sender] = lambda: recording
    yield recording
    app.dependency_overrides.pop(get_message_sender, None)


def code_from(sender: RecordingSender) -> str:
    match = re.search(r"\b(\d{6})\b", sender.messages[-1].text)
    assert match, sender.messages[-1].text
    return match.group(1)


def codes(db: Session) -> list[PasswordResetCode]:
    db.expire_all()
    return list(db.scalars(select(PasswordResetCode).order_by(PasswordResetCode.created_at)))


def audit(db: Session, action: str) -> list[AuditRecord]:
    db.expire_all()
    return list(db.scalars(select(AuditRecord).where(AuditRecord.action == action)))


def reset(client: TestClient, code: str, password: str = NEW_PASSWORD, identifier: str = EMAIL):
    return client.post(
        RESET, json={"identifier": identifier, "code": code, "new_password": password}
    )


def test_customer_gets_a_code_by_email_and_only_its_hash_is_stored(
    client: TestClient, db: Session, customer_auth: dict, sender: RecordingSender
):
    res = client.post(FORGOT, json={"identifier": "  Customer.A@Example.com "})
    assert res.status_code == 202 and res.json() == {"message": GENERIC_REPLY}

    [message] = sender.messages
    assert (message.channel, message.recipient) == ("email", EMAIL)
    code = code_from(sender)
    [row] = codes(db)
    assert row.channel == "email" and row.attempts == 0 and row.consumed_at is None
    assert code not in row.code_hash and len(row.code_hash) == 64
    assert timedelta(minutes=14) < row.expires_at - datetime.now(UTC) <= timedelta(minutes=15)
    [record] = audit(db, "auth.password_reset_request")
    assert record.change_summary["status"] == "success"
    assert code not in str(record.change_summary)


def test_phone_identifier_sends_an_sms_to_the_canonical_number(
    client: TestClient, db: Session, customer_auth: dict, sender: RecordingSender
):
    assert client.post(FORGOT, json={"identifier": "0788 111 222"}).status_code == 202
    [message] = sender.messages
    assert (message.channel, message.recipient) == ("sms", PHONE)


@pytest.mark.parametrize(
    ("kind", "identifier", "reason"),
    [
        ("unknown", "nobody@example.com", "unknown_identifier"),
        ("staff", "admin@example.com", "staff_account"),
        ("inactive", EMAIL, "account_inactive"),
    ],
)
def test_ineligible_accounts_get_the_same_reply_and_no_code(
    client: TestClient,
    db: Session,
    customer_auth: dict,
    sender: RecordingSender,
    kind: str,
    identifier: str,
    reason: str,
):
    if kind == "staff":
        make_staff(db, "administrator", "admin@example.com", "+250788000001")
    if kind == "inactive":
        user = db.scalar(select(User).where(User.email == EMAIL))
        assert user is not None
        user.is_active = False
        db.commit()

    res = client.post(FORGOT, json={"identifier": identifier})
    assert res.status_code == 202 and res.json() == {"message": GENERIC_REPLY}
    assert sender.messages == [] and codes(db) == []
    [record] = audit(db, "auth.password_reset_request")
    assert record.change_summary["status"] == "ignored"
    assert record.change_summary["reason"] == reason


def test_reset_sets_the_password_revokes_sessions_and_is_single_use(
    client: TestClient, db: Session, customer_auth: dict, sender: RecordingSender
):
    client.post(FORGOT, json={"identifier": EMAIL})
    code = code_from(sender)

    res = reset(client, code)
    assert res.status_code == 200
    assert res.json()["message"].startswith("Your password has been reset")

    # Old session revoked, old password refused, new password works.
    assert client.get("/api/v1/auth/me", headers=customer_auth["headers"]).status_code == 401
    assert (
        client.post(LOGIN, json={"identifier": EMAIL, "password": OLD_PASSWORD}).status_code == 401
    )
    assert (
        client.post(LOGIN, json={"identifier": EMAIL, "password": NEW_PASSWORD}).status_code == 200
    )

    again = reset(client, code, password="Another-Pass-77")
    assert again.status_code == 422 and again.json()["error"]["code"] == "reset_code_invalid"

    success = [
        r for r in audit(db, "auth.password_reset") if r.change_summary["status"] == "success"
    ]
    assert len(success) == 1 and success[0].change_summary["sessions_revoked"] == 1
    for record in audit(db, "auth.password_reset"):
        assert NEW_PASSWORD not in str(record.change_summary) and code not in str(
            record.change_summary
        )


def test_wrong_codes_are_limited_to_five_attempts(
    client: TestClient,
    db: Session,
    customer_auth: dict,
    sender: RecordingSender,
    clock: FakeClock,
):
    client.post(FORGOT, json={"identifier": EMAIL})
    code = code_from(sender)
    wrong = f"{(int(code) + 1) % 1_000_000:06d}"
    for _ in range(5):
        res = reset(client, wrong)
        assert res.status_code == 422 and res.json()["error"]["code"] == "reset_code_invalid"
    [row] = codes(db)
    assert row.attempts == 5 and row.consumed_at is not None

    # A sixth try is rate-limited, even with the correct code...
    blocked = reset(client, code)
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "rate_limited"
    # ...and after the window the code is still dead: its five attempts are used up.
    clock.advance(get_settings().login_window_seconds + 1)
    res = reset(client, code)
    assert res.status_code == 422 and res.json()["error"]["code"] == "reset_code_invalid"


def test_requesting_codes_does_not_use_up_the_attempts_for_entering_one(
    client: TestClient, customer_auth: dict, sender: RecordingSender
):
    for _ in range(4):
        assert client.post(FORGOT, json={"identifier": EMAIL}).status_code == 202
    code = code_from(sender)
    wrong = f"{(int(code) + 1) % 1_000_000:06d}"
    for _ in range(4):
        assert reset(client, wrong).status_code == 422
    assert reset(client, code).status_code == 200  # fifth attempt, newest code


def test_expired_codes_are_refused(
    client: TestClient, db: Session, customer_auth: dict, sender: RecordingSender
):
    client.post(FORGOT, json={"identifier": EMAIL})
    code = code_from(sender)
    [row] = codes(db)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    res = reset(client, code)
    assert res.status_code == 422 and res.json()["error"]["code"] == "reset_code_invalid"


def test_a_new_request_invalidates_the_previous_code(
    client: TestClient, db: Session, customer_auth: dict, sender: RecordingSender
):
    client.post(FORGOT, json={"identifier": EMAIL})
    first = code_from(sender)
    client.post(FORGOT, json={"identifier": EMAIL})
    second = code_from(sender)

    rows = codes(db)
    assert len(rows) == 2 and rows[0].consumed_at is not None and rows[1].consumed_at is None
    if first != second:
        assert reset(client, first).status_code == 422
    assert reset(client, second).status_code == 200


def test_unknown_identifier_and_bad_codes_look_identical(
    client: TestClient, customer_auth: dict, sender: RecordingSender
):
    unknown = reset(client, "123456", identifier="nobody@example.com")
    no_code_requested = reset(client, "123456")
    assert unknown.status_code == no_code_requested.status_code == 422
    assert unknown.json() == no_code_requested.json()


def test_forgot_password_is_rate_limited_per_identifier(
    client: TestClient, customer_auth: dict, sender: RecordingSender
):
    statuses = [client.post(FORGOT, json={"identifier": EMAIL}).status_code for _ in range(6)]
    assert statuses == [202] * 5 + [429]
    blocked = client.post(FORGOT, json={"identifier": EMAIL})
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["retry-after"]) > 0
    assert len(sender.messages) == 5


def test_weak_new_password_is_rejected_without_echo(
    client: TestClient, customer_auth: dict, sender: RecordingSender
):
    client.post(FORGOT, json={"identifier": EMAIL})
    res = reset(client, code_from(sender), password="weakpass")
    assert res.status_code == 422 and res.json()["error"]["code"] == "validation_error"
    assert "weakpass" not in res.text
    # The code was not spent by a request that failed validation.
    assert reset(client, code_from(sender)).status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {"identifier": EMAIL, "code": "12345", "new_password": NEW_PASSWORD},
        {"identifier": EMAIL, "code": "12a456", "new_password": NEW_PASSWORD},
        {"identifier": "not-an-identifier", "code": "123456", "new_password": NEW_PASSWORD},
    ],
)
def test_malformed_reset_requests_are_422(client: TestClient, body: dict):
    assert client.post(RESET, json=body).status_code == 422


def test_without_a_message_provider_both_endpoints_answer_503(
    client: TestClient, customer_auth: dict
):
    app.dependency_overrides[get_message_sender] = lambda: None
    try:
        forgot = client.post(FORGOT, json={"identifier": EMAIL})
        reset_res = reset(client, "123456")
    finally:
        app.dependency_overrides.pop(get_message_sender, None)
    for res in (forgot, reset_res):
        assert res.status_code == 503
        assert res.json()["error"]["code"] == "password_reset_unavailable"
