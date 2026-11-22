"""Email verification of new customer accounts (ADR-006 amendment 2026-11-12), end to end
through the API against PostgreSQL. Verification emails are captured by the recording mailer
that tests/conftest.py installs; nothing is sent."""

import hashlib
import logging
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.session import get_db
from app.integrations.notifications import DeliveryError
from app.integrations.notifications.verification import VerificationMailer, get_verification_mailer
from app.main import app
from app.models.identity import User
from app.models.operations import AuditRecord
from app.models.session import EmailVerificationToken, UserSession
from app.repositories.email_verification_repository import EmailVerificationRepository
from app.services import auth_service, email_verification_service
from tests.conftest import VERIFY_PAGE, make_staff
from tests.support.messages import RecordingSender, ScriptedProvider, verification_token

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
VERIFY = "/api/v1/auth/email/verify"
RESEND = "/api/v1/auth/email/verification/resend"
PASSWORD = "SecurePassword123!"
EMAIL = "aline@example.com"
EMAIL_W = "waiting@example.com"
RESEND_REPLY = {
    "message": (
        "If an account with this email address is waiting for verification, a new link has "
        "been sent."
    )
}


def register(client: TestClient, email: str = EMAIL, phone: str | None = None) -> dict:
    body: dict[str, Any] = {"email": email, "full_name": "Aline Uwase", "password": PASSWORD}
    if phone:
        body["phone"] = phone
    res = client.post(REGISTER, json=body)
    assert res.status_code == 201, res.text
    return res.json()


def login(client: TestClient, identifier: str = EMAIL, password: str = PASSWORD):
    return client.post(LOGIN, json={"identifier": identifier, "password": password})


def user_row(db: Session, email: str = EMAIL) -> User:
    db.expire_all()
    user = db.scalar(select(User).where(User.email == email))
    assert user is not None
    return user


def tokens(db: Session, user: User) -> list[EmailVerificationToken]:
    db.expire_all()
    return list(
        db.scalars(
            select(EmailVerificationToken)
            .where(EmailVerificationToken.user_id == user.id)
            .order_by(EmailVerificationToken.created_at)
        )
    )


def sessions(db: Session, user: User) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).where(UserSession.user_id == user.id)) or 0


def audits(db: Session, action: str) -> list[AuditRecord]:
    db.expire_all()
    return list(db.scalars(select(AuditRecord).where(AuditRecord.action == action)))


def code(res) -> str:
    return res.json()["error"]["code"]


def age_tokens(db: Session, user: User, by: timedelta) -> None:
    """Pretend the user's links were issued `by` earlier (the resend cooldown)."""
    db.execute(
        update(EmailVerificationToken)
        .where(EmailVerificationToken.user_id == user.id)
        .values(created_at=EmailVerificationToken.created_at - by)
    )
    db.commit()


@pytest.fixture
def welcome_emails(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Every welcome email recorded for the outbox, wherever it comes from."""
    recorded: list[tuple[str, Any]] = []

    def spy(db: Session, event: str, subject_id: Any, recipient: str | None) -> None:
        recorded.append((event, recipient))

    monkeypatch.setattr(auth_service, "record_email_event", spy)
    monkeypatch.setattr(email_verification_service, "record_email_event", spy)
    return recorded


# ---- registration ------------------------------------------------------------------------------
def test_registration_with_an_email_creates_an_unverified_customer_and_sends_one_link(
    client: TestClient, db: Session, verification_mail: RecordingSender, welcome_emails: list
) -> None:
    body = register(client, phone="+250788100200")
    assert body["verification_required"] is True
    assert body["session_token"] is None and body["token_type"] is None
    assert body["expires_at"] is None
    assert body["user"]["roles"] == ["customer"] and body["user"]["is_staff"] is False

    user = user_row(db)
    assert user.email_verified_at is None and not user.is_staff
    assert sessions(db, user) == 0  # no session before verification
    assert welcome_emails == []  # the welcome email waits for verification

    [message] = verification_mail.messages
    assert message.recipient == EMAIL and message.channel == "email"
    assert get_settings().marketplace_name in message.subject
    assert f"{VERIFY_PAGE}#token=" in message.text and message.html and VERIFY_PAGE in message.html
    assert "24 hours" in message.text
    assert "because this address was used to register" in message.text
    assert PASSWORD not in message.text and PASSWORD not in (message.html or "")

    token = verification_token(verification_mail, EMAIL)
    [row] = tokens(db, user)
    # Only the digest is stored; the expiry is the configured 24 hours.
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert row.email == EMAIL and row.consumed_at is None and row.revoked_at is None
    lifetime = row.expires_at - row.created_at
    assert timedelta(hours=23, minutes=59) < lifetime <= timedelta(hours=24, seconds=5)


def test_the_raw_token_is_never_in_the_response_the_database_logs_or_audit(
    client: TestClient,
    db: Session,
    verification_mail: RecordingSender,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    res = client.post(REGISTER, json={"email": EMAIL, "full_name": "Aline", "password": PASSWORD})
    token = verification_token(verification_mail, EMAIL)
    assert token not in res.text
    assert client.post(VERIFY, json={"token": token}).status_code == 200
    assert token not in caplog.text
    dump = db.execute(text("SELECT row_to_json(t)::text FROM email_verification_tokens t"))
    assert all(token not in r[0] for r in dump)
    for record in [*audits(db, "auth.register"), *audits(db, "auth.email_verify")]:
        assert token not in str(record.change_summary)


def test_phone_only_registration_is_unchanged_and_signed_in(
    client: TestClient, db: Session, verification_mail: RecordingSender, welcome_emails: list
) -> None:
    res = client.post(
        REGISTER, json={"phone": "0788100300", "full_name": "Phone Only", "password": PASSWORD}
    )
    assert res.status_code == 201
    body = res.json()
    assert body["verification_required"] is False and body["session_token"]
    assert verification_mail.messages == []
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['session_token']}"})
    assert me.status_code == 200
    assert login(client, "0788100300").status_code == 200


def test_without_a_mailer_registration_with_an_email_creates_nothing(
    client: TestClient, db: Session
) -> None:
    app.dependency_overrides[get_verification_mailer] = lambda: None
    res = client.post(REGISTER, json={"email": EMAIL, "full_name": "Aline", "password": PASSWORD})
    assert res.status_code == 503 and code(res) == "email_verification_unavailable"
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(User)) == 0
    # Phone-only registration needs no email and still works.
    phone_only = {"phone": "0788100301", "full_name": "Phone", "password": PASSWORD}
    assert client.post(REGISTER, json=phone_only).status_code == 201
    assert code(client.post(RESEND, json={"email": EMAIL})) == "email_verification_unavailable"


def test_a_failure_while_creating_the_account_rolls_everything_back(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch, verification_mail
) -> None:
    def broken(*args: Any, **kwargs: Any):
        raise RuntimeError("token store down")

    monkeypatch.setattr(email_verification_service.EmailVerificationService, "issue", broken)
    with pytest.raises(RuntimeError):
        client.post(REGISTER, json={"email": EMAIL, "full_name": "Aline", "password": PASSWORD})
    db.rollback()
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(User)) == 0
    assert db.scalar(select(func.count()).select_from(EmailVerificationToken)) == 0
    assert verification_mail.messages == []


def test_a_failed_delivery_leaves_the_account_unverified_and_logs_no_secret(
    client: TestClient, db: Session, caplog: pytest.LogCaptureFixture
) -> None:
    failing = ScriptedProvider([DeliveryError("connection_failed")])
    mailer = VerificationMailer(sender=failing, page_url=VERIFY_PAGE)
    app.dependency_overrides[get_verification_mailer] = lambda: mailer
    caplog.set_level(logging.INFO)
    body = register(client)
    assert body["verification_required"] is True  # the account exists; the email failed
    user = user_row(db)
    assert user.email_verified_at is None
    assert "Verification email not delivered" in caplog.text and "DeliveryError" in caplog.text
    token = verification_token(failing, EMAIL)  # what the provider was handed
    assert token not in caplog.text and EMAIL not in caplog.text
    # The customer can ask for a new link once the cooldown has passed.
    age_tokens(db, user, timedelta(minutes=5))
    assert client.post(RESEND, json={"email": EMAIL}).status_code == 202
    assert len(failing.messages) == 2


# ---- verify ------------------------------------------------------------------------------------
def test_a_valid_link_verifies_once_then_the_customer_signs_in(
    client: TestClient, db: Session, verification_mail: RecordingSender, welcome_emails: list
) -> None:
    register(client)
    token = verification_token(verification_mail, EMAIL)
    assert code(login(client)) == "email_not_verified"

    res = client.post(VERIFY, json={"token": token})
    assert res.status_code == 200
    assert res.json() == {"message": "Your email address is verified. You can now sign in."}
    assert "token" not in res.text and "session" not in res.text
    user = user_row(db)
    assert user.email_verified_at is not None
    assert sessions(db, user) == 0  # verifying does not sign in
    [row] = tokens(db, user)
    assert row.consumed_at is not None
    assert welcome_emails == [("welcome", EMAIL)]  # now that the address is proven
    assert len(audits(db, "auth.email_verify")) == 1

    signed_in = login(client)
    assert signed_in.status_code == 200 and signed_in.json()["session_token"]

    again = client.post(VERIFY, json={"token": token})
    assert again.status_code == 422 and code(again) == "verification_token_used"
    assert welcome_emails == [("welcome", EMAIL)]  # not twice


@pytest.mark.parametrize(
    "token",
    ["x" * 43, "short", "a" * 129, "tok en with spaces and more characters!!!!"],
)
def test_unknown_or_malformed_tokens_are_invalid(client: TestClient, token: str) -> None:
    res = client.post(VERIFY, json={"token": token})
    assert res.status_code == 422 and code(res) == "verification_token_invalid"


def test_the_request_must_be_exactly_a_token(client: TestClient) -> None:
    for body in ({}, {"token": ""}, {"token": "x" * 43, "email": EMAIL}, {"token": 7}):
        res = client.post(VERIFY, json=body)
        assert res.status_code == 422 and code(res) == "validation_error", body


def test_an_expired_link_is_refused_and_the_account_stays_unverified(
    client: TestClient, db: Session, verification_mail: RecordingSender
) -> None:
    register(client)
    token = verification_token(verification_mail, EMAIL)
    user = user_row(db)
    db.execute(
        update(EmailVerificationToken)
        .where(EmailVerificationToken.user_id == user.id)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db.commit()
    res = client.post(VERIFY, json={"token": token})
    assert res.status_code == 422 and code(res) == "verification_token_expired"
    assert user_row(db).email_verified_at is None
    [failure] = audits(db, "auth.email_verify")
    assert failure.change_summary["status"] == "failure"
    assert failure.change_summary["reason"] == "expired"


def test_a_new_link_supersedes_the_old_one(
    client: TestClient, db: Session, verification_mail: RecordingSender
) -> None:
    register(client)
    first = verification_token(verification_mail, EMAIL)
    age_tokens(db, user_row(db), timedelta(minutes=5))
    assert client.post(RESEND, json={"email": EMAIL}).json() == RESEND_REPLY
    second = verification_token(verification_mail, EMAIL)
    assert first != second
    old = client.post(VERIFY, json={"token": first})
    assert old.status_code == 422 and code(old) == "verification_token_invalid"
    assert client.post(VERIFY, json={"token": second}).status_code == 200
    rows = tokens(db, user_row(db))
    states = [(t.consumed_at is not None, t.revoked_at is not None) for t in rows]
    assert states == [(False, True), (True, False)]  # the old one revoked, the new one used


def test_a_link_for_an_address_the_account_no_longer_has_is_invalid(
    client: TestClient, db: Session, verification_mail: RecordingSender
) -> None:
    register(client)
    token = verification_token(verification_mail, EMAIL)
    db.execute(update(User).where(User.email == EMAIL).values(email="changed@example.com"))
    db.commit()
    res = client.post(VERIFY, json={"token": token})
    assert code(res) == "verification_token_invalid"
    assert user_row(db, "changed@example.com").email_verified_at is None


def test_failed_verification_attempts_are_rate_limited_per_network(client: TestClient) -> None:
    limit = get_settings().email_verification_max_failures_per_ip
    for _ in range(limit):
        assert client.post(VERIFY, json={"token": "y" * 43}).status_code == 422
    res = client.post(VERIFY, json={"token": "y" * 43})
    assert res.status_code == 429 and code(res) == "rate_limited"
    assert int(res.headers["Retry-After"]) > 0


@pytest.fixture
def own_sessions(pg_engine: Engine) -> Iterator[None]:
    """Each request its own session and connection, like separate API workers."""
    factory = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)

    def own_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = own_session
    yield


def test_simultaneous_uses_of_one_link_verify_exactly_once(
    client: TestClient, pg_engine: Engine, verification_mail: RecordingSender, own_sessions: None
) -> None:
    register(client)
    token = verification_token(verification_mail, EMAIL)
    barrier = threading.Barrier(8)
    results: list[str] = []
    errors: list[BaseException] = []
    guard = threading.Lock()

    def attempt() -> None:
        try:
            barrier.wait(timeout=10)
            res = client.post(VERIFY, json={"token": token})
            outcome = "200" if res.status_code == 200 else res.json()["error"]["code"]
            with guard:
                results.append(outcome)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors
    assert not any(t.is_alive() for t in threads), "a request hung"
    assert sorted(results) == ["200"] + ["verification_token_used"] * 7
    with Session(pg_engine) as db:
        consumed = db.scalar(
            select(func.count())
            .select_from(EmailVerificationToken)
            .where(EmailVerificationToken.consumed_at.is_not(None))
        )
        assert consumed == 1
        statuses: list[str] = sorted(
            db.scalars(
                select(AuditRecord.change_summary["status"].astext).where(
                    AuditRecord.action == "auth.email_verify"
                )
            )
        )
        assert statuses == ["failure"] * 7 + ["success"]  # verified once; seven refused


# ---- login ---------------------------------------------------------------------------------------
def test_an_unverified_customer_cannot_sign_in_by_email_or_phone(
    client: TestClient, db: Session
) -> None:
    register(client, phone="+250788100400")
    for identifier in (EMAIL, "0788100400"):
        res = login(client, identifier)
        assert res.status_code == 403 and code(res) == "email_not_verified"
        assert "session_token" not in res.text
    # A wrong password still says only that the credentials are wrong: nothing about the state.
    wrong = login(client, password="Wrong-Password-1")
    assert wrong.status_code == 401 and code(wrong) == "invalid_credentials"
    assert sessions(db, user_row(db)) == 0
    reasons = [a.change_summary for a in audits(db, "auth.login")]
    assert any("email_not_verified" in str(r) for r in reasons)


def test_existing_and_verified_accounts_sign_in_as_before(
    client: TestClient, customer_auth: dict
) -> None:
    # customer_auth registered, verified through the link and signed in (tests/conftest.py).
    me = client.get("/api/v1/auth/me", headers=customer_auth["headers"])
    assert me.status_code == 200
    assert login(client, "customer.a@example.com").status_code == 200


def test_staff_sign_in_is_unchanged_and_never_asks_for_verification(
    client: TestClient, db: Session, verification_mail: RecordingSender
) -> None:
    staff = make_staff(db, "administrator", "sales.verify@example.com", "+250788100500")
    db.execute(update(User).where(User.id == staff["user"].id).values(email_verified_at=None))
    db.commit()
    res = login(client, "sales.verify@example.com", staff["password"])
    assert res.status_code == 200, res.text
    assert client.post(RESEND, json={"email": "sales.verify@example.com"}).json() == RESEND_REPLY
    assert verification_mail.messages == []


# ---- resend ------------------------------------------------------------------------------------
def test_resend_answers_the_same_for_every_kind_of_address(
    client: TestClient, db: Session, verification_mail: RecordingSender, customer_auth: dict
) -> None:
    register(client, EMAIL_W)
    age_tokens(db, user_row(db, EMAIL_W), timedelta(minutes=5))
    make_staff(db, "administrator", "staff.enum@example.com", "+250788100600")
    inactive = register(client, "inactive@example.com")
    db.execute(update(User).where(User.id == inactive["user"]["id"]).values(is_active=False))
    db.commit()
    before = len(verification_mail.messages)

    answers = {
        email: client.post(RESEND, json={"email": email})
        for email in (
            EMAIL_W,  # unverified: a new link
            "customer.a@example.com",  # already verified
            "nobody@example.com",  # no account
            "staff.enum@example.com",  # staff
            "inactive@example.com",  # deactivated (and still in its cooldown)
        )
    }
    assert {(r.status_code, r.text) for r in answers.values()} == {(202, answers[EMAIL_W].text)}
    assert answers[EMAIL_W].json() == RESEND_REPLY
    sent = [m.recipient for m in verification_mail.messages[before:]]
    assert sent == [EMAIL_W]


def test_resend_respects_the_cooldown(
    client: TestClient, db: Session, verification_mail: RecordingSender
) -> None:
    register(client)
    assert client.post(RESEND, json={"email": EMAIL}).json() == RESEND_REPLY
    assert len(verification_mail.messages) == 1  # the registration link is still fresh
    age_tokens(db, user_row(db), timedelta(seconds=61))
    assert client.post(RESEND, json={"email": EMAIL}).json() == RESEND_REPLY
    assert len(verification_mail.messages) == 2
    assert client.post(RESEND, json={"email": EMAIL}).json() == RESEND_REPLY
    assert len(verification_mail.messages) == 2  # cooling down again


def test_resend_is_rate_limited_per_address_whether_or_not_it_exists(client: TestClient) -> None:
    limit = get_settings().email_verification_resend_max_per_email
    for email in (EMAIL, "nobody@example.com"):
        if email == EMAIL:
            register(client)
        for _ in range(limit):
            assert client.post(RESEND, json={"email": email}).status_code == 202
        res = client.post(RESEND, json={"email": email})
        assert res.status_code == 429 and code(res) == "rate_limited"
        assert int(res.headers["Retry-After"]) > 0


def test_resend_is_rate_limited_per_ip(client: TestClient) -> None:
    limit = get_settings().email_verification_resend_max_per_ip
    for i in range(limit):
        assert client.post(RESEND, json={"email": f"n{i}@example.com"}).status_code == 202
    res = client.post(RESEND, json={"email": "one-more@example.com"})
    assert res.status_code == 429 and code(res) == "rate_limited"


def test_resend_validates_the_address(client: TestClient) -> None:
    for body in ({}, {"email": "not-an-email"}, {"email": EMAIL, "token": "x"}):
        res = client.post(RESEND, json=body)
        assert res.status_code == 422 and code(res) == "validation_error", body


def _lock_waiters(engine: Engine) -> int:
    """Other transactions currently blocked on a lock while touching the token table."""
    with engine.connect() as conn:
        return conn.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND pid <> pg_backend_pid() AND wait_event_type = 'Lock' "
                "AND query ILIKE '%email_verification_tokens%'"
            )
        )


def test_a_second_use_waits_for_the_first_and_then_finds_the_link_used(
    client: TestClient,
    pg_engine: Engine,
    verification_mail: RecordingSender,
    own_sessions: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first request to lock the token keeps its transaction open until PostgreSQL shows the
    second one waiting for that row lock: the overlap is proven, not hoped for."""
    register(client)
    token = verification_token(verification_mail, EMAIL)
    original = EmailVerificationRepository.lock_by_hash
    state = {"gated": False, "overlapped": False}
    guard = threading.Lock()

    def gated(db: Session, token_hash: str):
        row = original(db, token_hash)
        with guard:
            first = row is not None and not state["gated"]
            state["gated"] = state["gated"] or first
        if first:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if _lock_waiters(pg_engine) > 0:
                    state["overlapped"] = True
                    break
                time.sleep(0.02)
        return row

    monkeypatch.setattr(EmailVerificationRepository, "lock_by_hash", staticmethod(gated))
    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def attempt() -> None:
        barrier.wait(timeout=10)
        res = client.post(VERIFY, json={"token": token})
        outcomes.append("200" if res.status_code == 200 else res.json()["error"]["code"])

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert state["overlapped"], "the second request never waited for the first one's lock"
    assert sorted(outcomes) == ["200", "verification_token_used"]
    with Session(pg_engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(EmailVerificationToken)
                .where(EmailVerificationToken.consumed_at.is_not(None))
            )
            == 1
        )
