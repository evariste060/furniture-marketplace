"""Logging configuration and redaction (module 1, core)."""

import io
import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.logging import REDACTED, configure_logging, redact
from app.main import app


@pytest.mark.parametrize(
    ("raw", "secret"),
    [
        ("Authorization: Bearer abc.DEF-123_xyz", "abc.DEF-123_xyz"),
        ("headers={'authorization': 'Bearer tok3n'}", "tok3n"),
        ('{"password": "Secret-Pass-1"}', "Secret-Pass-1"),
        ("password=Secret-Pass-1&identifier=x", "Secret-Pass-1"),
        ("new_password: Hunter2!", "Hunter2!"),
        ("session_token=Q9x_LONG-token", "Q9x_LONG-token"),
        ("postgresql+psycopg://rwanda_app:p4ss%40word@127.0.0.1:5432/db", "p4ss%40word"),
        ("redis://:redis-secret@127.0.0.1:6379/0", "redis-secret"),
        ("AUDIT_HMAC_KEY=0123456789abcdef0123456789abcdef", "0123456789abcdef0123456789abcdef"),
        ("reset_code=482913", "482913"),
        ("login failed for alice@example.com", "alice@example.com"),
        ("sms to +250788123456 failed", "788123456"),
        ("sms to 0788123456 failed", "0788123456"),
        ("sms to 250788123456 failed", "250788123456"),
    ],
)
def test_redact_masks_secrets_and_personal_data(raw: str, secret: str):
    assert secret not in redact(raw)


def test_redact_keeps_ordinary_text_and_identifiers():
    line = (
        "Unhandled error on GET /api/v1/staff/orders/0f82f0f1-0788-4234-a123-456789012345 "
        "code=invalid_transition status=409"
    )
    assert redact(line) == line


def test_redaction_keeps_the_key_so_logs_stay_readable():
    assert redact("password=abc") == f"password={REDACTED}"
    assert redact("Bearer abc") == f"Bearer {REDACTED}"


@pytest.fixture
def log_output() -> Iterator[io.StringIO]:
    """Route all logging through the real configuration into a buffer, then restore it."""
    buffer = io.StringIO()
    configure_logging("DEBUG", stream=buffer)
    try:
        yield buffer
    finally:
        configure_logging(get_settings().log_level)


def test_configure_logging_is_idempotent_and_covers_uvicorn(log_output: io.StringIO):
    root = logging.getLogger()
    ours = [h for h in root.handlers if h.get_name() == "app-redacting-handler"]
    assert len(ours) == 1
    assert root.level == logging.DEBUG
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        mine = [h for h in uvicorn_logger.handlers if h.get_name() == "app-redacting-handler"]
        assert mine == ours  # exactly our one handler (pytest may add its capture handlers)
        assert uvicorn_logger.propagate is False  # never printed twice via the root logger

    configure_logging("DEBUG", stream=log_output)  # calling again replaces, never duplicates
    assert len([h for h in root.handlers if h.get_name() == "app-redacting-handler"]) == 1

    logging.getLogger("uvicorn.access").info('"GET /lookup?phone=0788123456 HTTP/1.1" 200')
    assert "0788123456" not in log_output.getvalue()
    assert "[PHONE]" in log_output.getvalue()


def test_lines_use_uvicorns_console_layout(log_output: io.StringIO):
    logging.getLogger("uvicorn.error").info("Application startup complete.")
    logging.getLogger("app.test").warning("disk almost full")
    logging.getLogger("app.test").error("sms to 0788123456 failed")
    assert log_output.getvalue().splitlines() == [
        "INFO:     Application startup complete.",
        "WARNING:  disk almost full",
        "ERROR:    sms to [PHONE] failed",  # still redacted
    ]


def test_tracebacks_are_redacted(log_output: io.StringIO):
    try:
        raise RuntimeError("connect failed: postgresql://app:db-secret@db/x token=abc123")
    except RuntimeError:
        logging.getLogger("app.test").exception("boom")
    output = log_output.getvalue()
    assert "RuntimeError" in output and "boom" in output
    assert "db-secret" not in output and "abc123" not in output


def test_requests_never_put_passwords_tokens_or_phones_in_logs(log_output: io.StringIO):
    password = "Never-Log-This-1"
    token = "never-log-this-token-value"
    client = TestClient(app, raise_server_exceptions=False)

    # Validation failure with a password in the body.
    client.post("/api/v1/auth/login", json={"identifier": "", "password": password})
    # A bearer token on an authenticated route. Whatever happens next (401, or a logged 500 when no
    # database is reachable in unit tests), the token must not appear in the log.
    client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    def crash():
        raise RuntimeError(f"password={password} for +250788123456 using Bearer {token}")

    app.add_api_route("/api/v1/__test/log-crash", crash, methods=["GET"], include_in_schema=False)
    try:
        response = client.get("/api/v1/__test/log-crash")
    finally:
        app.router.routes.pop()
        app.openapi_schema = None
    assert response.status_code == 500

    output = log_output.getvalue()
    assert "Unhandled error on GET /api/v1/__test/log-crash" in output  # the error was logged
    for secret in (password, token, "788123456"):
        assert secret not in output
