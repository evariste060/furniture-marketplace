"""Continue with Google (ADR-006 amendment 2026-11-11), end to end through the API against
PostgreSQL, with Google's endpoints replaced by tests/support/fake_google.py."""

import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx2 import Response  # what starlette's TestClient returns
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rate_limit import LoginRateLimiter, get_google_auth_rate_limiter
from app.core.security import hash_password
from app.integrations.oauth import get_google_oauth_client
from app.main import app
from app.models.identity import OAuthIdentity, StaffRoleAssignment, User
from app.models.operations import AuditRecord
from app.models.session import OAuthLoginFlow, UserSession
from tests.conftest import make_staff
from tests.support.fake_google import CLIENT_SECRET, FakeGoogle, new_key
from tests.support.memory_rate_limit import FakeClock, MemoryRateLimitStore

START = "/api/v1/auth/google/start"
CALLBACK = "/api/v1/auth/google/callback"
LINK_START = "/api/v1/auth/google/link/start"
LINK_CALLBACK = "/api/v1/auth/google/link/callback"
SUB = "1100000000000000001"


@pytest.fixture
def google(client: TestClient, clock: FakeClock) -> FakeGoogle:
    fake = FakeGoogle()
    settings = get_settings()
    limiter = LoginRateLimiter(
        MemoryRateLimitStore(clock),
        settings,
        prefix="google_auth",
        max_identifier=settings.google_auth_max_per_network,
        max_ip=settings.google_auth_max_per_network,
        window_seconds=settings.google_auth_window_seconds,
    )
    google_client = fake.client()
    app.dependency_overrides[get_google_oauth_client] = lambda: google_client
    app.dependency_overrides[get_google_auth_rate_limiter] = lambda: limiter
    return fake


def start(client: TestClient, path: str = START, headers: dict | None = None) -> dict:
    res = client.post(path, headers=headers or {})
    assert res.status_code == 200, res.text
    return res.json()


def sign_in(client: TestClient, google: FakeGoogle, **claims) -> Response:
    google.claims = claims
    flow = start(client)
    answer = google.authorize(flow["authorization_url"])
    return client.post(CALLBACK, json={**answer, "flow_token": flow["flow_token"]})


def error_code(res: Response) -> str:
    return res.json()["error"]["code"]


def users(db: Session) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(User)) or 0


def audit(db: Session, action: str) -> list[AuditRecord]:
    db.expire_all()
    return list(db.scalars(select(AuditRecord).where(AuditRecord.action == action)))


def register(client: TestClient, email: str, phone: str = "+250788555666") -> dict:
    res = client.post(
        "/api/v1/auth/register",
        json={"email": email, "phone": phone, "full_name": "Existing", "password": "Secure1234!"},
    )
    assert res.status_code == 201, res.text
    return res.json()


# ---- configuration -----------------------------------------------------------------------------
def test_without_google_settings_the_endpoints_answer_503(client: TestClient) -> None:
    app.dependency_overrides[get_google_oauth_client] = lambda: None
    assert error_code(client.post(START)) == "google_auth_unavailable"
    body = {"state": "s", "flow_token": "f", "code": "c"}
    assert error_code(client.post(CALLBACK, json=body)) == "google_auth_unavailable"


# ---- new and returning customers ---------------------------------------------------------------
def test_a_new_google_account_creates_a_customer_and_signs_in(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    res = sign_in(client, google)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["account_created"] is True
    assert body["user"]["email"] == "shopper@gmail.com"
    assert body["user"]["full_name"] == "Shopper Example"
    assert body["user"]["is_staff"] is False and body["user"]["roles"] == ["customer"]
    assert body["token_type"] == "bearer"

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['session_token']}"})
    assert me.status_code == 200 and me.json()["id"] == body["user"]["id"]

    db.expire_all()
    user = db.scalar(select(User).where(User.email == "shopper@gmail.com"))
    assert user is not None and user.password_hash is None and user.is_staff is False
    assert db.scalar(select(func.count()).select_from(StaffRoleAssignment)) == 0
    identity = db.scalar(select(OAuthIdentity))
    assert identity is not None and identity.subject == SUB and identity.user_id == user.id
    [record] = audit(db, "auth.register")
    assert record.change_summary["provider"] == "google"


def test_a_returning_google_account_signs_in_to_the_same_customer(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    first = sign_in(client, google).json()
    second = sign_in(client, google)
    assert second.status_code == 200
    assert second.json()["account_created"] is False
    assert second.json()["user"]["id"] == first["user"]["id"]
    assert second.json()["session_token"] != first["session_token"]
    assert users(db) == 1
    assert [r.change_summary["provider"] for r in audit(db, "auth.login")] == ["google"]


def test_sign_in_follows_the_google_subject_not_the_email(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    first = sign_in(client, google).json()
    # The person changed their Google address: still the same account.
    again = sign_in(client, google, email="new.address@gmail.com")
    assert again.json()["user"]["id"] == first["user"]["id"]
    # Another Google account (another subject) with a new address is another customer.
    other = sign_in(client, google, sub="2200000000000000002", email="other@gmail.com")
    assert other.json()["account_created"] is True
    assert other.json()["user"]["id"] != first["user"]["id"]
    assert users(db) == 2


def test_a_google_customer_has_no_password_until_they_set_one(
    client: TestClient, google: FakeGoogle
) -> None:
    sign_in(client, google)
    res = client.post(
        "/api/v1/auth/login", json={"identifier": "shopper@gmail.com", "password": "Anything1!"}
    )
    assert res.status_code == 401


# ---- existing accounts and duplicates ----------------------------------------------------------
def test_an_existing_password_account_is_never_linked_by_email(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    register(client, "shopper@gmail.com")
    res = sign_in(client, google, email="SHOPPER@gmail.com")
    assert res.status_code == 409
    assert error_code(res) == "google_account_exists"
    assert "session_token" not in res.text
    assert users(db) == 1
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(OAuthIdentity)) == 0


def test_a_second_google_account_cannot_reuse_a_google_customers_email(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    sign_in(client, google)
    res = sign_in(client, google, sub="3300000000000000003")
    assert error_code(res) == "google_account_exists"
    assert users(db) == 1


def test_a_staff_email_gets_the_same_answer_and_no_session(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    make_staff(db, "administrator", "boss@gmail.com", "+250788000009")
    sessions_before = db.scalar(select(func.count()).select_from(UserSession))
    res = sign_in(client, google, email="boss@gmail.com")
    assert res.status_code == 409 and error_code(res) == "google_account_exists"
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(UserSession)) == sessions_before
    assert db.scalar(select(func.count()).select_from(OAuthIdentity)) == 0
    [record] = audit(db, "auth.google")
    assert record.change_summary["reason"] == "staff_email"


def test_a_staff_account_linked_to_google_cannot_sign_in_with_it(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    staff = make_staff(db, "administrator", "boss@example.com", "+250788000009")
    db.add(OAuthIdentity(user_id=staff["user"].id, provider="google", subject=SUB))
    db.commit()
    res = sign_in(client, google)
    assert res.status_code == 403 and error_code(res) == "google_staff_not_allowed"


def test_extra_claims_or_fields_never_grant_staff_rights(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    res = sign_in(client, google, is_staff=True, roles=["administrator"], hd="3sixty.rw")
    assert res.json()["user"]["is_staff"] is False
    assert res.json()["user"]["roles"] == ["customer"]
    flow = start(client)
    answer = google.authorize(flow["authorization_url"], code="c2")
    res = client.post(CALLBACK, json={**answer, "flow_token": flow["flow_token"], "is_staff": True})
    assert res.status_code == 422


def test_a_deactivated_customer_cannot_sign_in_with_google(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    sign_in(client, google)
    db.execute(update(User).values(is_active=False))
    db.commit()
    res = sign_in(client, google)
    assert res.status_code == 403 and error_code(res) == "account_inactive"


# ---- email verification ------------------------------------------------------------------------
@pytest.mark.parametrize("claims", [{"email_verified": False}, {"email": None}])
def test_an_unverified_or_missing_email_is_refused(
    client: TestClient, db: Session, google: FakeGoogle, claims: dict
) -> None:
    res = sign_in(client, google, **claims)
    assert res.status_code == 403 and error_code(res) == "google_email_unverified"
    assert users(db) == 0


# ---- the ID token ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("claims", "reason"),
    [
        ({"aud": "someone-elses-client"}, "id_token_audience"),
        ({"iss": "https://accounts.example.com"}, "id_token_issuer"),
        ({"exp": 1_000_000_000, "iat": 999_990_000}, "id_token_expired"),
        ({"nonce": "not-the-nonce-we-sent"}, "id_token_nonce"),
    ],
)
def test_invalid_id_tokens_are_refused(
    client: TestClient, db: Session, google: FakeGoogle, claims: dict, reason: str
) -> None:
    res = sign_in(client, google, **claims)
    assert res.status_code == 401 and error_code(res) == "google_token_invalid"
    assert users(db) == 0
    [record] = audit(db, "auth.google")
    assert record.change_summary["reason"] == reason


def test_an_id_token_with_a_forged_signature_is_refused(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    flow = start(client)
    answer = google.authorize(flow["authorization_url"])
    nonce = google.codes[answer["code"]]
    forger = FakeGoogle(key=new_key(), kid=google.kid)
    google.token_response = lambda form: httpx.Response(
        200, json={"id_token": forger.id_token(nonce=nonce)}
    )
    res = client.post(CALLBACK, json={**answer, "flow_token": flow["flow_token"]})
    assert res.status_code == 401 and error_code(res) == "google_token_invalid"
    assert audit(db, "auth.google")[0].change_summary["reason"] == "id_token_signature"
    assert users(db) == 0


# ---- state, flow token and replay --------------------------------------------------------------
def test_flows_store_only_digests_and_the_verifier_is_erased_once_used(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    flow = start(client)
    answer = google.authorize(flow["authorization_url"])
    db.expire_all()
    row = db.scalar(select(OAuthLoginFlow))
    assert row is not None and row.purpose == "login" and row.code_verifier
    assert answer["state"] not in (row.state_hash, row.nonce_hash)
    assert flow["flow_token"] != row.flow_token_hash
    client.post(CALLBACK, json={**answer, "flow_token": flow["flow_token"]})
    db.expire_all()
    row = db.scalar(select(OAuthLoginFlow))
    assert row is not None and row.consumed_at is not None and row.code_verifier is None


def test_unknown_or_missing_state_is_refused(client: TestClient, google: FakeGoogle) -> None:
    flow = start(client)
    res = client.post(
        CALLBACK, json={"state": "made-up", "code": "c", "flow_token": flow["flow_token"]}
    )
    assert res.status_code == 422 and error_code(res) == "google_state_invalid"
    res = client.post(CALLBACK, json={"code": "c", "flow_token": flow["flow_token"]})
    assert res.status_code == 422
    assert google.token_requests == []


def test_another_browsers_callback_is_refused_and_does_not_burn_the_flow(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    flow = start(client)
    answer = google.authorize(flow["authorization_url"])
    # Login CSRF: the attacker's state and code arrive without this browser's flow token.
    res = client.post(CALLBACK, json={**answer, "flow_token": "someone-elses-token"})
    assert res.status_code == 422 and error_code(res) == "google_state_invalid"
    assert google.token_requests == []
    assert audit(db, "auth.google")[0].change_summary["reason"] == "flow_token_mismatch"
    # The rightful browser can still finish.
    ok = client.post(CALLBACK, json={**answer, "flow_token": flow["flow_token"]})
    assert ok.status_code == 200


def test_an_expired_flow_is_refused(client: TestClient, db: Session, google: FakeGoogle) -> None:
    flow = start(client)
    answer = google.authorize(flow["authorization_url"])
    db.execute(update(OAuthLoginFlow).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    db.commit()
    res = client.post(CALLBACK, json={**answer, "flow_token": flow["flow_token"]})
    assert res.status_code == 422 and error_code(res) == "google_state_invalid"
    assert google.token_requests == []
    assert audit(db, "auth.google")[0].change_summary["reason"] == "expired"


def test_a_replayed_callback_is_refused_without_calling_google(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    flow = start(client)
    answer = google.authorize(flow["authorization_url"])
    body = {**answer, "flow_token": flow["flow_token"]}
    assert client.post(CALLBACK, json=body).status_code == 200
    replay = client.post(CALLBACK, json=body)
    assert replay.status_code == 422 and error_code(replay) == "google_state_invalid"
    assert len(google.token_requests) == 1
    assert audit(db, "auth.google")[0].change_summary["reason"] == "replayed"


def test_a_flow_expires_after_the_configured_time(client: TestClient, google: FakeGoogle) -> None:
    flow = start(client)
    expires = datetime.fromisoformat(flow["expires_at"])
    ttl = get_settings().google_oauth_flow_ttl_seconds
    assert abs((expires - datetime.now(UTC)).total_seconds() - ttl) < 30


# ---- codes, cancellation and Google failures ---------------------------------------------------
def test_an_invalid_authorization_code_is_refused(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    flow = start(client)
    answer = google.authorize(flow["authorization_url"])
    res = client.post(
        CALLBACK, json={**answer, "code": "forged-code", "flow_token": flow["flow_token"]}
    )
    assert res.status_code == 401 and error_code(res) == "google_code_invalid"
    assert users(db) == 0


def test_the_code_exchange_sends_this_flows_pkce_verifier(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    flow = start(client)
    db.expire_all()
    verifier = db.scalar(select(OAuthLoginFlow.code_verifier))
    answer = google.authorize(flow["authorization_url"])
    client.post(CALLBACK, json={**answer, "flow_token": flow["flow_token"]})
    assert google.token_requests[0]["code_verifier"] == [verifier]


def test_cancelling_at_google_is_reported_and_uses_up_the_flow(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    flow = start(client)
    state = google.authorize(flow["authorization_url"])["state"]
    res = client.post(
        CALLBACK, json={"state": state, "error": "access_denied", "flow_token": flow["flow_token"]}
    )
    assert res.status_code == 422 and error_code(res) == "google_auth_cancelled"
    assert audit(db, "auth.google")[0].change_summary["reason"] == "cancelled"
    retry = client.post(
        CALLBACK, json={"state": state, "code": "good-code", "flow_token": flow["flow_token"]}
    )
    assert error_code(retry) == "google_state_invalid"
    assert google.token_requests == []


def test_other_google_errors_and_malformed_answers(client: TestClient, google: FakeGoogle) -> None:
    flow = start(client)
    state = google.authorize(flow["authorization_url"])["state"]
    res = client.post(
        CALLBACK,
        json={"state": state, "error": "server_error", "flow_token": flow["flow_token"]},
    )
    assert error_code(res) == "google_auth_failed"
    both = {"state": state, "code": "c", "error": "x", "flow_token": flow["flow_token"]}
    assert client.post(CALLBACK, json=both).status_code == 422
    assert client.post(CALLBACK, json={"state": state, "flow_token": "f"}).status_code == 422


@pytest.mark.parametrize(
    "outage",
    [
        "token_500",
        "token_timeout",
        "keys_down",
    ],
)
def test_google_outages_answer_503_and_create_nothing(
    client: TestClient, db: Session, google: FakeGoogle, outage: str
) -> None:
    def timeout(form):
        raise httpx.ReadTimeout("timed out")

    if outage == "token_500":
        google.token_response = lambda form: httpx.Response(500)
    elif outage == "token_timeout":
        google.token_response = timeout
    else:
        google.jwks_response = lambda: httpx.Response(503)
    res = sign_in(client, google)
    assert res.status_code == 503 and error_code(res) == "google_unavailable"
    assert users(db) == 0


def test_a_misconfigured_client_secret_is_an_outage_not_a_user_error(
    client: TestClient, google: FakeGoogle
) -> None:
    google.token_response = lambda form: httpx.Response(401, json={"error": "invalid_client"})
    res = sign_in(client, google)
    assert res.status_code == 503 and error_code(res) == "google_unavailable"


# ---- sessions ----------------------------------------------------------------------------------
def test_logout_revokes_a_google_session(client: TestClient, google: FakeGoogle) -> None:
    token = sign_in(client, google).json()["session_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_logout_everywhere_revokes_every_google_session(
    client: TestClient, google: FakeGoogle
) -> None:
    first = sign_in(client, google).json()["session_token"]
    second = sign_in(client, google).json()["session_token"]
    res = client.post("/api/v1/auth/logout-all", headers={"Authorization": f"Bearer {second}"})
    assert res.status_code == 200
    for token in (first, second):
        res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401


# ---- abuse limits and secrets ------------------------------------------------------------------
def test_starts_and_failed_callbacks_are_rate_limited_per_network(
    client: TestClient, google: FakeGoogle
) -> None:
    limit = get_settings().google_auth_max_per_network
    for _ in range(limit):
        assert client.post(START).status_code == 200
    res = client.post(START)
    assert res.status_code == 429 and int(res.headers["Retry-After"]) > 0
    res = client.post(CALLBACK, json={"state": "s", "code": "c", "flow_token": "f"})
    assert res.status_code == 429


def test_no_token_code_or_secret_reaches_the_logs_or_audit(
    client: TestClient, db: Session, google: FakeGoogle, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    flow = start(client)
    answer = google.authorize(flow["authorization_url"])
    body = client.post(CALLBACK, json={**answer, "flow_token": flow["flow_token"]}).json()
    google.token_response = lambda form: httpx.Response(401, json={"error": "invalid_client"})
    sign_in(client, google)
    db.expire_all()
    stored = " ".join(
        str(r.change_summary) + str(r.entity_id) for r in db.scalars(select(AuditRecord))
    )
    logged = caplog.text
    for secret in (
        answer["code"],
        answer["state"],
        flow["flow_token"],
        body["session_token"],
        CLIENT_SECRET,
        "ya29.",
        "shopper@gmail.com",
        SUB,
    ):
        assert secret not in stored, secret
        assert secret not in logged, secret


# ---- linking Google to an existing account -----------------------------------------------------
def link(client: TestClient, google: FakeGoogle, headers: dict, **claims) -> Response:
    google.claims = claims
    flow = start(client, LINK_START, headers)
    answer = google.authorize(flow["authorization_url"])
    return client.post(
        LINK_CALLBACK, json={**answer, "flow_token": flow["flow_token"]}, headers=headers
    )


def test_a_signed_in_customer_links_google_then_signs_in_with_it(
    client: TestClient, db: Session, google: FakeGoogle, customer_auth: dict
) -> None:
    res = link(client, google, customer_auth["headers"])
    assert res.status_code == 200, res.text
    assert res.json()["provider"] == "google" and res.json()["email"] == "shopper@gmail.com"
    assert len(audit(db, "auth.google_link")) == 1
    # The account's own email is unchanged; Google now signs in to it.
    signed_in = sign_in(client, google)
    assert signed_in.json()["account_created"] is False
    assert signed_in.json()["user"]["id"] == customer_auth["user"]["id"]
    assert signed_in.json()["user"]["email"] == "customer.a@example.com"


def test_linking_needs_a_signed_in_customer(
    client: TestClient, db: Session, google: FakeGoogle, admin_auth: dict
) -> None:
    assert client.post(LINK_START).status_code == 401
    res = client.post(LINK_START, headers=admin_auth["headers"])
    assert res.status_code == 403 and error_code(res) == "google_staff_not_allowed"
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(OAuthLoginFlow)) == 0


def test_an_account_links_at_most_one_google_account(
    client: TestClient, google: FakeGoogle, customer_auth: dict
) -> None:
    assert link(client, google, customer_auth["headers"]).status_code == 200
    res = client.post(LINK_START, headers=customer_auth["headers"])
    assert res.status_code == 409 and error_code(res) == "google_already_linked"


def test_a_google_account_links_to_at_most_one_account(
    client: TestClient,
    google: FakeGoogle,
    customer_auth: dict,
    second_customer_auth: dict,
) -> None:
    assert link(client, google, customer_auth["headers"]).status_code == 200
    res = link(client, google, second_customer_auth["headers"])
    assert res.status_code == 409 and error_code(res) == "google_account_in_use"


def test_link_and_sign_in_flows_cannot_be_swapped_or_shared(
    client: TestClient,
    db: Session,
    google: FakeGoogle,
    customer_auth: dict,
    second_customer_auth: dict,
) -> None:
    # A link flow cannot sign anyone in...
    flow = start(client, LINK_START, customer_auth["headers"])
    answer = google.authorize(flow["authorization_url"])
    res = client.post(CALLBACK, json={**answer, "flow_token": flow["flow_token"]})
    assert error_code(res) == "google_state_invalid"
    # ...a sign-in flow cannot link...
    flow = start(client)
    answer = google.authorize(flow["authorization_url"], code="c2")
    res = client.post(
        LINK_CALLBACK,
        json={**answer, "flow_token": flow["flow_token"]},
        headers=customer_auth["headers"],
    )
    assert error_code(res) == "google_state_invalid"
    # ...and one customer's link flow cannot link another customer.
    flow = start(client, LINK_START, customer_auth["headers"])
    answer = google.authorize(flow["authorization_url"], code="c3")
    res = client.post(
        LINK_CALLBACK,
        json={**answer, "flow_token": flow["flow_token"]},
        headers=second_customer_auth["headers"],
    )
    assert error_code(res) == "google_state_invalid"
    assert google.token_requests == []
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(OAuthIdentity)) == 0


def test_linking_requires_a_verified_google_email(
    client: TestClient, google: FakeGoogle, customer_auth: dict
) -> None:
    res = link(client, google, customer_auth["headers"], email_verified=False)
    assert res.status_code == 403 and error_code(res) == "google_email_unverified"


# ---- races -------------------------------------------------------------------------------------
def test_a_concurrent_sign_up_with_the_same_email_ends_in_a_conflict_not_a_duplicate(
    client: TestClient, db: Session, google: FakeGoogle, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another request registered the email between our check and our insert: the unique index
    refuses the second account and the sign-in is answered as if it had arrived second."""
    from app.repositories.user_repository import UserRepository

    register(client, "shopper@gmail.com")
    real = UserRepository.get_by_email
    calls = {"n": 0}

    def stale_once(db_: Session, email: str):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(db_, email)

    monkeypatch.setattr(UserRepository, "get_by_email", staticmethod(stale_once))
    res = sign_in(client, google)
    assert res.status_code == 409 and error_code(res) == "google_account_exists"
    assert calls["n"] == 2
    assert users(db) == 1
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(OAuthIdentity)) == 0


def test_a_concurrent_first_sign_in_of_the_same_google_account_signs_in_once_created(
    client: TestClient, db: Session, google: FakeGoogle, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two callbacks of one new Google account: the second insert fails and signs in to the
    account the first created."""
    from app.repositories.oauth_repository import OAuthRepository

    first = sign_in(client, google).json()
    real = OAuthRepository.get_identity
    calls = {"n": 0}

    def stale_once(db_: Session, provider: str, subject: str):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(db_, provider, subject)

    monkeypatch.setattr(OAuthRepository, "get_identity", staticmethod(stale_once))
    monkeypatch.setattr(
        "app.repositories.user_repository.UserRepository.get_by_email",
        staticmethod(lambda db_, email: None),
    )
    res = sign_in(client, google)
    assert res.status_code == 200, res.text
    assert res.json()["account_created"] is False
    assert res.json()["user"]["id"] == first["user"]["id"]
    assert users(db) == 1


# ---- review fixes (2026-11-11) -----------------------------------------------------------------
def test_a_google_session_stops_working_when_the_account_is_deactivated(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    token = sign_in(client, google).json()["session_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    db.execute(update(User).values(is_active=False))
    db.commit()
    res = client.get("/api/v1/auth/me", headers=headers)
    assert res.status_code == 403 and error_code(res) == "account_inactive"


@pytest.mark.parametrize("email", ["not-an-email", "a" * 250 + "@gmail.com", "x@@gmail.com"])
def test_a_google_email_outside_the_shops_rules_is_refused(
    client: TestClient, db: Session, google: FakeGoogle, email: str
) -> None:
    res = sign_in(client, google, email=email)
    assert res.status_code == 403 and error_code(res) == "google_email_invalid"
    assert users(db) == 0


@pytest.mark.parametrize(
    ("name", "stored"),
    [
        ("  Ada \t\n Lovelace  ", "Ada Lovelace"),
        ("Bad\x00Name\x1b[31m", "BadName[31m"),
        ("A", "shopper"),  # too short: the email's local part
        (None, "shopper"),
        ("N" * 400, "N" * 255),
    ],
)
def test_googles_display_name_is_cleaned_like_a_typed_one(
    client: TestClient, google: FakeGoogle, name: str | None, stored: str
) -> None:
    res = sign_in(client, google, name=name)
    assert res.json()["user"]["full_name"] == stored


def test_a_concurrent_link_of_the_same_account_reports_already_linked(
    client: TestClient,
    db: Session,
    google: FakeGoogle,
    customer_auth: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another link of this account committed between our checks and our insert: the unique
    (user, provider) constraint refuses ours, and the answer names the real reason."""
    from app.repositories.oauth_repository import OAuthRepository

    flow = start(client, LINK_START, customer_auth["headers"])
    answer = google.authorize(flow["authorization_url"])
    # The other link: a different Google account, committed now.
    db.add(
        OAuthIdentity(
            user_id=customer_auth["user"]["id"], provider="google", subject="9900000000000000009"
        )
    )
    db.commit()
    real = OAuthRepository.get_user_identity
    calls = {"n": 0}

    def stale_once(db_: Session, user_id, provider: str):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return None if calls["n"] == 1 else real(db_, user_id, provider)

    monkeypatch.setattr(OAuthRepository, "get_user_identity", staticmethod(stale_once))
    res = client.post(
        LINK_CALLBACK,
        json={**answer, "flow_token": flow["flow_token"]},
        headers=customer_auth["headers"],
    )
    assert res.status_code == 409 and error_code(res) == "google_already_linked"
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(OAuthIdentity)) == 1


# ---- /auth/me: how the account can sign in ------------------------------------------------------
ME = "/api/v1/auth/me"
ME_FIELDS = {
    "id",
    "email",
    "phone",
    "full_name",
    "is_active",
    "is_staff",
    "roles",
    "created_at",
    "google_linked",
    "has_password",
}


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_me_reports_a_password_account_without_google(
    client: TestClient, customer_auth: dict
) -> None:
    res = client.get(ME, headers=customer_auth["headers"])
    assert res.status_code == 200
    body = res.json()
    assert set(body) == ME_FIELDS  # the existing fields, plus the two flags and nothing else
    assert body["email"] == "customer.a@example.com" and body["roles"] == ["customer"]
    assert body["google_linked"] is False and body["has_password"] is True


def test_me_reports_a_google_customer_without_a_password(
    client: TestClient, google: FakeGoogle
) -> None:
    body = sign_in(client, google).json()
    me = client.get(ME, headers=bearer(body["session_token"])).json()
    assert me["google_linked"] is True and me["has_password"] is False
    assert me["id"] == body["user"]["id"]
    # Nothing about the Google account itself: no subject, email at Google, or any hash.
    assert SUB not in str(me) and "password_hash" not in me and "subject" not in me


def test_me_reports_a_password_account_that_linked_google(
    client: TestClient, google: FakeGoogle, customer_auth: dict
) -> None:
    assert link(client, google, customer_auth["headers"]).status_code == 200
    me = client.get(ME, headers=customer_auth["headers"]).json()
    assert me["google_linked"] is True and me["has_password"] is True
    assert me["email"] == "customer.a@example.com"  # the account's own email, not Google's


def test_me_reports_a_google_customer_after_they_set_a_password(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    body = sign_in(client, google).json()
    # What a reset code does for them (PasswordResetService sets the hash the same way).
    db.execute(
        update(User)
        .where(User.id == body["user"]["id"])
        .values(password_hash=hash_password("Secure1234!"))
    )
    db.commit()
    me = client.get(ME, headers=bearer(body["session_token"])).json()
    assert me["google_linked"] is True and me["has_password"] is True


def test_me_reports_staff_flags_from_their_own_account(
    client: TestClient, admin_auth: dict
) -> None:
    me = client.get(ME, headers=admin_auth["headers"]).json()
    assert me["is_staff"] is True
    assert me["google_linked"] is False and me["has_password"] is True


def test_me_reports_another_accounts_google_link_only_for_that_account(
    client: TestClient, google: FakeGoogle, customer_auth: dict, second_customer_auth: dict
) -> None:
    assert link(client, google, customer_auth["headers"]).status_code == 200
    other = client.get(ME, headers=second_customer_auth["headers"]).json()
    assert other["google_linked"] is False


# ---- email verification (2026-11-12) ------------------------------------------------------------
def test_a_new_google_customer_is_created_with_a_verified_email(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    body = sign_in(client, google).json()
    db.expire_all()
    user = db.scalar(select(User).where(User.id == body["user"]["id"]))
    assert user is not None and user.email_verified_at is not None  # Google proved the address


def test_google_never_verifies_or_takes_over_an_unverified_password_account(
    client: TestClient, db: Session, google: FakeGoogle
) -> None:
    """Someone registered shopper@gmail.com with a password and never verified it. Signing in
    with the Google account for that address neither links it nor marks it verified."""
    register(client, "shopper@gmail.com")
    res = sign_in(client, google)
    assert res.status_code == 409 and error_code(res) == "google_account_exists"
    db.expire_all()
    user = db.scalar(select(User).where(User.email == "shopper@gmail.com"))
    assert user is not None and user.email_verified_at is None
    assert db.scalar(select(func.count()).select_from(OAuthIdentity)) == 0
    # And the password account still cannot sign in until its address is verified.
    login = client.post(
        "/api/v1/auth/login", json={"identifier": "shopper@gmail.com", "password": "Secure1234!"}
    )
    assert login.status_code == 403 and login.json()["error"]["code"] == "email_not_verified"
