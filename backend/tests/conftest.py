"""Shared fixtures.

Database-backed tests run on PostgreSQL only (the schema uses JSONB, partial indexes, CHECK
regexes and triggers). Like the commerce tests, each test gets its own schema in the database
named by TEST_DATABASE_URL, migrated with Alembic to head and dropped afterwards. Without
TEST_DATABASE_URL these tests are skipped; pure unit tests still run. (The commerce tests in
tests/integration/test_commerce_database.py instead fail without it, and require the database
to be named rwanda_ecommerce_test.)

TEST_DATABASE_URL may come from the shell or backend/.env. Settings the app reads are forced
below, after .env is loaded, so a local .env can never point tests at a real database. A
'localhost' host in TEST_DATABASE_URL is rewritten to 127.0.0.1 for every fixture and subprocess
(see tests/support/database_url.py).
"""

import os
from collections.abc import Generator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import load_dotenv

from tests.support.database_url import prefer_ipv4_loopback

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

TEST_DATABASE_URL = prefer_ipv4_loopback(os.environ.get("TEST_DATABASE_URL"))
if TEST_DATABASE_URL:
    os.environ["TEST_DATABASE_URL"] = TEST_DATABASE_URL  # read by tests/postgres and commerce tests

os.environ["DATABASE_URL"] = TEST_DATABASE_URL or "postgresql+psycopg://unset:unset@127.0.0.1:1/x"
# Never let a MIGRATION_DATABASE_URL from backend/.env redirect test migrations to a real DB.
os.environ["MIGRATION_DATABASE_URL"] = ""
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["AUDIT_HMAC_KEY"] = "test-only-audit-hmac-key-0123456789abcdef"
# Module 15: the mock payment provider is configured in tests (a test-only secret).
os.environ["PAYMENT_MOCK_WEBHOOK_SECRET"] = "test-only-mock-payment-secret-0123456789abcdef"
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"  # unused: the limiter is overridden in tests
# Images go to MEDIA_ROOT on local disk, never to a cloud bucket configured in backend/.env.
os.environ["STORAGE_BACKEND"] = "local"
# No real email or SMS from tests, whatever backend/.env configures: tests that need a provider
# set one themselves, and the email tests capture messages (tests/support/email_capture.py).
os.environ["NOTIFICATION_PROVIDER"] = "none"
# Email verification links in tests point at this page (the mailer is overridden in `client`).
VERIFY_PAGE = "https://shop.test/verify-email"
for name in ("EMAIL_ALLOWED_RECIPIENTS", "STAFF_ORDER_ALERT_EMAILS", "SITE_URL"):
    os.environ[name] = ""
# Never a real Google OAuth client from backend/.env (its secret, or a development-only http
# redirect that every non-development Settings would refuse): empty means off. Tests that need
# Google use tests/support/fake_google.py or set these themselves.
for name in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REDIRECT_URI"):
    os.environ[name] = ""
# The client IP is the transport peer unless a test enables signed client IPs itself
# (tests/support/client_ip.py): never a signing secret from backend/.env.
os.environ["CLIENT_IP_SOURCE"] = "peer"
for name in ("CLIENT_IP_SIGNING_SECRET", "CLIENT_IP_SIGNING_SECRET_NEXT"):
    os.environ[name] = ""

from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.engine import Engine, make_url  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.schema import CreateSchema, DropSchema  # noqa: E402

from alembic import command  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.rate_limit import (  # noqa: E402
    CartRateLimiter,
    LoginRateLimiter,
    get_cart_rate_limiter,
    get_email_verify_rate_limiter,
    get_login_rate_limiter,
    get_order_lookup_rate_limiter,
    get_password_reset_rate_limiter,
    get_quote_request_rate_limiter,
    get_reset_code_rate_limiter,
    get_review_submit_rate_limiter,
    get_service_request_rate_limiter,
    get_support_message_rate_limiter,
    get_verification_resend_rate_limiter,
)
from app.core.security import (  # noqa: E402
    generate_session_token,
    hash_password,
    hash_session_token,
)
from app.db.session import get_db  # noqa: E402
from app.integrations.notifications.verification import (  # noqa: E402
    VerificationMailer,
    get_verification_mailer,
)
from app.main import app  # noqa: E402
from app.models.identity import StaffRoleAssignment, User  # noqa: E402
from app.models.session import UserSession  # noqa: E402
from tests.support.credentials import random_password  # noqa: E402
from tests.support.memory_rate_limit import FakeClock, MemoryRateLimitStore  # noqa: E402
from tests.support.messages import RecordingSender, verification_token  # noqa: E402

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest.fixture
def pg_engine() -> Iterator[Engine]:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not configured")
    admin = create_engine(TEST_DATABASE_URL, connect_args={"connect_timeout": 5})
    schema = f"test_{uuid4().hex}"
    with admin.begin() as conn:
        conn.execute(CreateSchema(schema))
    engine = None
    try:
        url = make_url(TEST_DATABASE_URL).update_query_dict({"options": f"-csearch_path={schema}"})
        previous = os.environ["DATABASE_URL"]
        os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
        get_settings.cache_clear()
        try:
            command.upgrade(Config(str(ALEMBIC_INI)), "head")
        finally:
            os.environ["DATABASE_URL"] = previous
            get_settings.cache_clear()
        engine = create_engine(url, connect_args={"connect_timeout": 5})
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin.begin() as conn:
            conn.execute(DropSchema(schema, cascade=True))
        admin.dispose()


@pytest.fixture
def db(pg_engine: Engine) -> Generator[Session, None, None]:
    session = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def rate_limiter(clock: FakeClock) -> LoginRateLimiter:
    return LoginRateLimiter(MemoryRateLimitStore(clock), get_settings())


@pytest.fixture
def reset_limiter(clock: FakeClock) -> LoginRateLimiter:
    return LoginRateLimiter(MemoryRateLimitStore(clock), get_settings(), prefix="reset")


@pytest.fixture
def reset_code_limiter(clock: FakeClock) -> LoginRateLimiter:
    return LoginRateLimiter(MemoryRateLimitStore(clock), get_settings(), prefix="reset_code")


@pytest.fixture
def lookup_limiter(clock: FakeClock) -> LoginRateLimiter:
    settings = get_settings()
    return LoginRateLimiter(
        MemoryRateLimitStore(clock),
        settings,
        prefix="order_lookup",
        max_identifier=settings.order_lookup_max_failures_per_order,
        max_ip=settings.order_lookup_max_failures_per_ip,
        window_seconds=settings.order_lookup_window_seconds,
    )


@pytest.fixture
def review_limiter(clock: FakeClock) -> LoginRateLimiter:
    settings = get_settings()
    return LoginRateLimiter(
        MemoryRateLimitStore(clock),
        settings,
        prefix="review_submit",
        max_identifier=settings.review_submit_max_per_token,
        max_ip=settings.review_submit_max_per_ip,
        window_seconds=settings.review_submit_window_seconds,
    )


@pytest.fixture
def quote_limiter(clock: FakeClock) -> LoginRateLimiter:
    settings = get_settings()
    return LoginRateLimiter(
        MemoryRateLimitStore(clock),
        settings,
        prefix="quote_request",
        max_identifier=settings.quote_request_max_per_phone,
        max_ip=settings.quote_request_max_per_ip,
        window_seconds=settings.quote_request_window_seconds,
    )


@pytest.fixture
def service_limiter(clock: FakeClock) -> LoginRateLimiter:
    settings = get_settings()
    return LoginRateLimiter(
        MemoryRateLimitStore(clock),
        settings,
        prefix="service_request",
        max_identifier=settings.service_request_max_per_phone,
        max_ip=settings.service_request_max_per_ip,
        window_seconds=settings.service_request_window_seconds,
    )


@pytest.fixture
def support_limiter(clock: FakeClock) -> LoginRateLimiter:
    settings = get_settings()
    return LoginRateLimiter(
        MemoryRateLimitStore(clock),
        settings,
        prefix="support_message",
        max_identifier=settings.support_message_max_per_sender,
        max_ip=settings.support_message_max_per_ip,
        window_seconds=settings.support_message_window_seconds,
    )


@pytest.fixture
def resend_limiter(clock: FakeClock) -> LoginRateLimiter:
    settings = get_settings()
    return LoginRateLimiter(
        MemoryRateLimitStore(clock),
        settings,
        prefix="verify_resend",
        max_identifier=settings.email_verification_resend_max_per_email,
        max_ip=settings.email_verification_resend_max_per_ip,
        window_seconds=settings.email_verification_resend_window_seconds,
    )


@pytest.fixture
def verify_limiter(clock: FakeClock) -> LoginRateLimiter:
    settings = get_settings()
    return LoginRateLimiter(
        MemoryRateLimitStore(clock),
        settings,
        prefix="verify_email",
        max_identifier=settings.email_verification_max_failures_per_ip,
        max_ip=settings.email_verification_max_failures_per_ip,
        window_seconds=settings.email_verification_failure_window_seconds,
    )


@pytest.fixture
def verification_mail() -> RecordingSender:
    """Every verification email of the test (the mailer is overridden in `client`)."""
    return RecordingSender()


@pytest.fixture
def cart_limiter(clock: FakeClock) -> CartRateLimiter:
    return CartRateLimiter(MemoryRateLimitStore(clock), get_settings())


@pytest.fixture
def client(
    db: Session,
    rate_limiter: LoginRateLimiter,
    reset_limiter: LoginRateLimiter,
    reset_code_limiter: LoginRateLimiter,
    cart_limiter: CartRateLimiter,
    lookup_limiter: LoginRateLimiter,
    review_limiter: LoginRateLimiter,
    quote_limiter: LoginRateLimiter,
    service_limiter: LoginRateLimiter,
    support_limiter: LoginRateLimiter,
    resend_limiter: LoginRateLimiter,
    verify_limiter: LoginRateLimiter,
    verification_mail: RecordingSender,
) -> Generator[TestClient, None, None]:
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_login_rate_limiter] = lambda: rate_limiter
    app.dependency_overrides[get_password_reset_rate_limiter] = lambda: reset_limiter
    app.dependency_overrides[get_reset_code_rate_limiter] = lambda: reset_code_limiter
    app.dependency_overrides[get_cart_rate_limiter] = lambda: cart_limiter
    app.dependency_overrides[get_order_lookup_rate_limiter] = lambda: lookup_limiter
    app.dependency_overrides[get_review_submit_rate_limiter] = lambda: review_limiter
    app.dependency_overrides[get_quote_request_rate_limiter] = lambda: quote_limiter
    app.dependency_overrides[get_service_request_rate_limiter] = lambda: service_limiter
    app.dependency_overrides[get_support_message_rate_limiter] = lambda: support_limiter
    app.dependency_overrides[get_verification_resend_rate_limiter] = lambda: resend_limiter
    app.dependency_overrides[get_email_verify_rate_limiter] = lambda: verify_limiter
    mailer = VerificationMailer(sender=verification_mail, page_url=VERIFY_PAGE)
    app.dependency_overrides[get_verification_mailer] = lambda: mailer
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _register(client: TestClient, email: str, phone: str, name: str) -> dict:
    """Register, verify the email with the link that was sent, and sign in (2026-11-12): the
    signed-in customer most tests start from."""
    password = "SecurePassword123!"
    res = client.post(
        "/api/v1/auth/register",
        json={"email": email, "phone": phone, "full_name": name, "password": password},
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["verification_required"] is True and data["session_token"] is None
    verify_email(client, email)
    login = client.post("/api/v1/auth/login", json={"identifier": email, "password": password})
    assert login.status_code == 200, login.text
    token = login.json()["session_token"]
    return {"user": data["user"], "token": token, "headers": {"Authorization": f"Bearer {token}"}}


def verify_email(client: TestClient, email: str) -> None:
    """Use the newest verification link sent to `email` (from the overridden mailer)."""
    mailer = app.dependency_overrides[get_verification_mailer]()
    token = verification_token(mailer.sender, email)
    res = client.post("/api/v1/auth/email/verify", json={"token": token})
    assert res.status_code == 200, res.text


@pytest.fixture
def customer_auth(client: TestClient) -> dict:
    """Register customer A and return user dict, token, and auth headers."""
    return _register(client, "customer.a@example.com", "+250788111222", "Customer Alice")


@pytest.fixture
def second_customer_auth(client: TestClient) -> dict:
    """Register customer B and return user dict, token, and auth headers."""
    return _register(client, "customer.b@example.com", "+250788333444", "Customer Bob")


def make_staff(db: Session, role: str, email: str, phone: str, password: str | None = None) -> dict:
    """Staff accounts cannot be created through the public API; insert directly for tests.

    The password is random per test unless given; read it from the returned dict.
    """
    password = password or random_password()
    user = User(
        email=email,
        phone=phone,
        full_name=f"Test {role}",
        password_hash=hash_password(password),
        is_active=True,
        is_staff=True,
    )
    db.add(user)
    db.flush()
    db.add(StaffRoleAssignment(user_id=user.id, role=role))
    raw_token = generate_session_token()
    now = datetime.now(UTC)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_session_token(raw_token),
            last_active_at=now,
            expires_at=now + timedelta(days=1),
        )
    )
    db.commit()
    return {
        "user": user,
        "token": raw_token,
        "password": password,
        "headers": {"Authorization": f"Bearer {raw_token}"},
    }


@pytest.fixture
def admin_auth(client: TestClient, db: Session) -> dict:
    return make_staff(db, "administrator", "admin@example.com", "+250788000001")


@pytest.fixture
def second_admin_auth(client: TestClient, db: Session) -> dict:
    """Another Marketplace Administrator, the only staff role (SC-05): for tests that need two
    distinct staff members, such as an order assignee."""
    return make_staff(db, "administrator", "admin.two@example.com", "+250788000002")
