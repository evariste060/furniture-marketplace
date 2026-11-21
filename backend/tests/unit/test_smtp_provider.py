"""The SMTP provider against a fake server (tests/support/fake_smtp.py): no real email, no
database. What the server is told, how every failure is classified, and that the server's text,
the recipient and the password never appear in what the provider raises."""

import asyncio
import logging
import socket
import ssl
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

import app.main as app_main
from app.core.config import Settings, get_settings
from app.integrations.notifications import (
    ConsoleProvider,
    DeliveryError,
    MockProvider,
    OutboundMessage,
    SmtpProvider,
    get_message_sender,
    get_notification_provider,
    warn_if_temporary_gmail_smtp,
)
from app.services.notification_service import outcome_unknown, sanitise_error
from tests.support.fake_smtp import DROP, HANG, TAKE_AND_DROP, FakeSmtp, localhost_tls

SENDER = "shop@example.rw"
RECIPIENT = "aline@example.rw"
PASSWORD = "app-password-value"
MESSAGE = OutboundMessage(
    channel="email",
    recipient=RECIPIENT,
    subject="Order ORD-1 confirmed",
    text="Your order ORD-1 is confirmed.",
    idempotency_key="notification:one",
)


@pytest.fixture
def server() -> Iterator[FakeSmtp]:
    with FakeSmtp() as fake:
        yield fake


def provider(fake: FakeSmtp, **options) -> SmtpProvider:
    return SmtpProvider("127.0.0.1", fake.port, SENDER, **{"use_tls": False, **options})


def failure(fake: FakeSmtp, **options) -> DeliveryError:
    with pytest.raises(DeliveryError) as raised:
        provider(fake, timeout=2, **options).send(MESSAGE)
    return raised.value


def test_a_message_reaches_the_server_with_its_headers(server: FakeSmtp):
    message_id = provider(server).send(MESSAGE)
    [mail] = server.messages
    assert (mail.sender, mail.recipients) == (SENDER, [RECIPIENT])
    assert mail.email["From"] == SENDER and mail.email["To"] == RECIPIENT
    assert mail.email["Subject"] == MESSAGE.subject
    assert mail.email["Date"] is not None
    assert mail.email["Message-ID"] == message_id
    assert MESSAGE.text in mail.email.get_content()
    assert server.commands[-1] == "QUIT"


@pytest.mark.parametrize(
    ("name", "header"),
    [
        ("3 Sixty Technologies", f"3 Sixty Technologies <{SENDER}>"),
        ("Orders, 3 Sixty", f'"Orders, 3 Sixty" <{SENDER}>'),  # quoted: the comma is special
        ("  ", SENDER),  # blank: the bare address
    ],
)
def test_the_sender_name_is_shown_beside_the_address(server: FakeSmtp, name: str, header: str):
    provider(server, from_name=name).send(MESSAGE)
    [mail] = server.messages
    assert mail.sender == SENDER  # the envelope sender stays the bare address
    assert mail.email["From"] == header


def test_html_goes_as_an_alternative_after_the_plain_text(server: FakeSmtp):
    html = "<!doctype html><html><body><p>Your order ORD-1 is confirmed.</p></body></html>"
    provider(server).send(OutboundMessage(**{**MESSAGE.__dict__, "html": html}))
    [mail] = server.messages
    assert mail.email.get_content_type() == "multipart/alternative"
    plain, rich = mail.email.iter_parts()
    assert plain.get_content_type() == "text/plain" and MESSAGE.text in plain.get_content()
    assert rich.get_content_type() == "text/html" and html in rich.get_content()


def test_every_attempt_of_a_message_keeps_its_message_id_and_others_differ(server: FakeSmtp):
    smtp = provider(server)
    first, again = smtp.send(MESSAGE), smtp.send(MESSAGE)
    other = OutboundMessage(**{**MESSAGE.__dict__, "idempotency_key": "notification:two"})
    assert first == again and first != smtp.send(other)
    assert first.endswith("@example.rw>") and len(first) <= 128  # the log column's limit


def test_starttls_comes_before_credentials_and_mail(tmp_path: Path):
    context, certificate = localhost_tls(tmp_path)
    with FakeSmtp(tls_context=context, accounts={"user": PASSWORD}) as fake:
        client = ssl.create_default_context(cafile=str(certificate))
        smtp = provider(fake, use_tls=True, username="user", password=PASSWORD, tls_context=client)
        smtp.send(MESSAGE)
    assert fake.logins == [("user", PASSWORD)]
    assert fake.messages[0].over_tls
    assert (
        fake.commands.index("STARTTLS") < fake.commands.index("AUTH") < fake.commands.index("MAIL")
    )


def test_an_untrusted_certificate_is_refused_before_credentials_or_mail(tmp_path: Path):
    context, _ = localhost_tls(tmp_path)
    with FakeSmtp(tls_context=context, accounts={"user": PASSWORD}) as fake:
        error = failure(fake, use_tls=True, username="user", password=PASSWORD)
    assert error.code == "tls_failed" and error.retryable
    assert fake.logins == [] and fake.messages == [] and "MAIL" not in fake.commands


def test_a_server_without_starttls_is_never_used_in_plain_text():
    with FakeSmtp(accounts={"user": PASSWORD}) as fake:
        error = failure(fake, use_tls=True, username="user", password=PASSWORD)
    assert error.code == "smtp_not_supported"
    assert fake.logins == [] and fake.messages == [] and "AUTH" not in fake.commands


def test_the_default_tls_context_verifies_the_server():
    context = ssl.create_default_context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname


def test_a_wrong_password_is_reported_and_stays_out_of_the_error():
    with FakeSmtp(accounts={"user": "the-right-one"}) as fake:
        error = failure(fake, username="user", password=PASSWORD)
    assert error.code == "auth_failed" and error.retryable  # correcting the settings saves it
    assert PASSWORD not in str(error) and "secret-server-text" not in str(error)
    assert fake.messages == []


@pytest.mark.parametrize(
    ("verb", "answer", "code", "retryable"),
    [
        ("RCPT", "550 5.1.1 aline@example.rw no such user", "recipient_refused", False),
        ("RCPT", "451 4.3.0 mailbox busy", "recipient_refused", True),
        ("MAIL", "553 5.1.8 sender not allowed", "sender_refused", False),
        ("MAIL", "421 4.7.0 try again later", "sender_refused", True),
        ("DATA_END", "554 5.7.1 message rejected", "message_refused", False),
        ("DATA_END", "452 4.5.3 too many messages today", "message_refused", True),
    ],
)
def test_refusals_are_final_or_temporary_as_the_server_says(
    server: FakeSmtp, verb, answer, code, retryable
):
    server.script(verb, answer)
    error = failure(server)
    assert (error.code, error.retryable) == (code, retryable)
    assert RECIPIENT not in str(error) and "5." not in str(error)
    assert server.messages == []


def test_a_server_that_refuses_the_connection_at_once():
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        port = unused.getsockname()[1]
    with pytest.raises(DeliveryError) as raised:
        SmtpProvider("127.0.0.1", port, SENDER, use_tls=False, timeout=2).send(MESSAGE)
    assert raised.value.code == "connection_failed" and raised.value.retryable
    assert not outcome_unknown(raised.value.code)  # nothing can have been sent


def test_a_connection_lost_mid_conversation_may_have_sent_the_message(server: FakeSmtp):
    server.script("RCPT", DROP)
    error = failure(server)
    assert error.code == "connection_lost" and error.retryable
    assert outcome_unknown(error.code)


def test_a_silent_server_is_bounded_by_the_timeout(server: FakeSmtp):
    server.script("DATA_END", HANG)
    with pytest.raises(DeliveryError) as raised:
        provider(server, timeout=0.3).send(MESSAGE)
    code, retryable = sanitise_error(raised.value)
    assert retryable and outcome_unknown(code)


def test_a_retry_after_an_unanswered_send_carries_the_same_message_id(server: FakeSmtp):
    server.script("DATA_END", TAKE_AND_DROP)
    smtp = provider(server, timeout=2)
    with pytest.raises(DeliveryError) as raised:
        smtp.send(MESSAGE)
    assert raised.value.code == "connection_lost"
    smtp.send(MESSAGE)
    first, second = server.messages
    assert first.email["Message-ID"] == second.email["Message-ID"]


@pytest.mark.parametrize("answer", ["500 no", DROP])
def test_a_failed_goodbye_after_acceptance_is_a_success(server: FakeSmtp, answer):
    server.script("QUIT", answer)
    assert provider(server, timeout=2).send(MESSAGE)
    assert len(server.messages) == 1


def test_only_email_can_be_sent(server: FakeSmtp):
    sms = OutboundMessage(**{**MESSAGE.__dict__, "channel": "sms", "recipient": "+250788123456"})
    with pytest.raises(DeliveryError) as raised:
        provider(server).send(sms)
    assert (raised.value.code, raised.value.retryable) == ("channel_unsupported", False)
    assert server.commands == []  # never connected
    assert provider(server).channels == ("email",)


@pytest.mark.parametrize(
    "change",
    [
        {"recipient": "aline@example.rw\r\nBcc: other@example.rw"},
        {"subject": "Order\r\nBcc: other@example.rw"},
    ],
)
def test_a_line_break_in_a_header_is_refused_without_sending(server: FakeSmtp, change):
    message = OutboundMessage(**{**MESSAGE.__dict__, **change})
    with pytest.raises(DeliveryError) as raised:
        provider(server).send(message)
    assert (raised.value.code, raised.value.retryable) == ("invalid_message", False)
    assert server.commands == []


def test_existing_providers_keep_both_channels():
    assert ConsoleProvider.channels == ("sms", "email")
    assert MockProvider.channels == ("sms", "email")


def settings(**overrides) -> Settings:
    base: dict = {
        "database_url": SecretStr("postgresql+psycopg://u:p@localhost/db"),
        "audit_hmac_key": SecretStr("x" * 32),
        "notification_provider": "smtp",
        "smtp_host": "smtp.gmail.com",
        "smtp_from_email": SENDER,
        "smtp_username": SENDER,
        "smtp_password": SecretStr(PASSWORD),
        "email_allowed_recipients": RECIPIENT,
    }
    return Settings(_env_file=None, **{**base, **overrides})  # type: ignore[call-arg]


def test_complete_settings_are_accepted_and_the_password_stays_hidden():
    configured = settings()
    assert (configured.smtp_port, configured.smtp_use_tls) == (587, True)
    assert PASSWORD not in repr(configured)


@pytest.mark.parametrize(
    "overrides",
    [
        {"smtp_host": None},
        {"smtp_host": ""},
        {"smtp_from_email": None},
        {"smtp_from_email": "not-an-address"},
        {"smtp_from_email": "a b@example.rw"},
        {"smtp_from_name": "3 Sixty" + chr(13) + chr(10) + "Bcc: x@example.rw"},  # injection
        {"smtp_from_name": "x" * 65},
        {"smtp_username": None},
        {"smtp_password": None},
        {"smtp_password": SecretStr("")},
        {"smtp_use_tls": False},  # credentials are never sent in plain text
        {"smtp_port": 0},
        {"smtp_timeout_seconds": 0},
    ],
)
def test_incomplete_or_unsafe_settings_are_refused(overrides):
    with pytest.raises(ValidationError):
        settings(**overrides)


def test_smtp_is_refused_in_production_and_allowed_in_staging():
    with pytest.raises(ValidationError, match="ADR-005"):
        settings(
            app_env="production",
            image_public_base_url="https://media.example.rw/m",
            payment_mock_webhook_secret=None,
        )
    assert settings(
        app_env="staging",
        image_public_base_url="https://media.example.rw/m",
        payment_mock_webhook_secret=None,
    )


def production(**overrides) -> Settings:
    """Production settings on the temporary Gmail route; a test can switch it off or change it."""
    base: dict = {
        "app_env": "production",
        "image_public_base_url": "https://media.example.rw/m",
        "payment_mock_webhook_secret": None,
        "temporary_gmail_smtp_enabled": True,
    }
    return settings(**{**base, **overrides})


def test_the_temporary_setting_allows_gmail_in_production():
    configured = production()
    assert configured.temporary_gmail_smtp_active
    assert (configured.smtp_host, configured.smtp_port) == ("smtp.gmail.com", 587)
    assert PASSWORD not in repr(configured)


def test_the_temporary_setting_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("TEMPORARY_GMAIL_SMTP_ENABLED", "true")
    configured = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url=SecretStr("postgresql+psycopg://u:p@localhost/db"),
        audit_hmac_key=SecretStr("x" * 32),
    )
    assert configured.temporary_gmail_smtp_enabled


def test_the_temporary_setting_is_off_by_default_and_production_still_refuses_smtp():
    assert settings().temporary_gmail_smtp_enabled is False
    with pytest.raises(ValidationError, match="ADR-005"):
        production(temporary_gmail_smtp_enabled=False)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"smtp_host": None}, "SMTP_HOST is required"),
        ({"smtp_host": "smtp.example.rw"}, "SMTP_HOST=smtp.gmail.com"),
        ({"smtp_port": 465}, "SMTP_PORT=587"),
        ({"smtp_port": 0}, "smtp_port"),
        ({"smtp_timeout_seconds": 0}, "smtp_timeout_seconds"),
        ({"smtp_timeout_seconds": 61}, "smtp_timeout_seconds"),
        ({"smtp_from_email": None}, "SMTP_FROM_EMAIL"),
        ({"smtp_from_email": "not-an-address"}, "SMTP_FROM_EMAIL"),
        ({"smtp_username": None}, "set together"),
        ({"smtp_password": None}, "set together"),
        ({"smtp_username": None, "smtp_password": None}, "SMTP_USERNAME and SMTP_PASSWORD"),
        ({"smtp_use_tls": False}, "SMTP_USE_TLS"),
        (
            {"smtp_use_tls": False, "smtp_username": None, "smtp_password": None},
            "SMTP_USE_TLS=true",
        ),
    ],
)
def test_the_temporary_route_refuses_incomplete_or_other_smtp_settings(overrides, message):
    with pytest.raises(ValidationError, match=message):
        production(**overrides)


def test_a_refused_setting_does_not_print_the_password(monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", PASSWORD)
    monkeypatch.setenv("SMTP_USERNAME", SENDER)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.rw")
    monkeypatch.setenv("SMTP_FROM_EMAIL", SENDER)
    monkeypatch.setenv("NOTIFICATION_PROVIDER", "smtp")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TEMPORARY_GMAIL_SMTP_ENABLED", "true")
    monkeypatch.setenv("IMAGE_PUBLIC_BASE_URL", "https://media.example.rw/m")
    monkeypatch.delenv("PAYMENT_MOCK_WEBHOOK_SECRET", raising=False)
    with pytest.raises(ValidationError) as refused:
        Settings(_env_file=None)  # type: ignore[call-arg]
    assert "SMTP_HOST=smtp.gmail.com" in str(refused.value)
    assert PASSWORD not in str(refused.value)


def test_the_temporary_setting_keeps_the_other_production_safeguards():
    with pytest.raises(ValidationError, match="PAYMENT_MOCK_WEBHOOK_SECRET"):
        production(payment_mock_webhook_secret=SecretStr("m" * 32))
    with pytest.raises(ValidationError, match="NOTIFICATION_PROVIDER=mock"):
        production(notification_provider="mock")
    with pytest.raises(ValidationError, match="NOTIFICATION_PROVIDER=console"):
        production(notification_provider="console")
    with pytest.raises(ValidationError, match="IMAGE_PUBLIC_BASE_URL"):
        production(image_public_base_url="http://localhost:8000/media")


def test_the_temporary_setting_changes_nothing_for_other_providers_or_environments():
    configured = production(notification_provider="none", smtp_host=None, smtp_password=None)
    assert not configured.temporary_gmail_smtp_active
    mock = settings(notification_provider="mock", temporary_gmail_smtp_enabled=True)
    assert not mock.temporary_gmail_smtp_active
    console = settings(notification_provider="console", temporary_gmail_smtp_enabled=True)
    assert not console.temporary_gmail_smtp_active
    staging = settings(
        app_env="staging",
        image_public_base_url="https://media.example.rw/m",
        payment_mock_webhook_secret=None,
        temporary_gmail_smtp_enabled=True,
        smtp_host="smtp.example.rw",  # staging keeps its existing rules
    )
    assert not staging.temporary_gmail_smtp_active


def test_the_temporary_route_builds_the_smtp_provider(monkeypatch):
    live = get_settings()
    configured = production()
    for name in (
        "app_env",
        "notification_provider",
        "smtp_host",
        "smtp_port",
        "smtp_use_tls",
        "smtp_username",
        "smtp_password",
        "smtp_from_email",
        "smtp_from_name",
        "temporary_gmail_smtp_enabled",
    ):
        monkeypatch.setattr(live, name, getattr(configured, name))
    assert isinstance(get_notification_provider(), SmtpProvider)
    assert isinstance(get_message_sender(), SmtpProvider)


def test_the_startup_warning_names_the_route_and_no_credentials(monkeypatch, caplog):
    live = get_settings()
    monkeypatch.setattr(live, "app_env", "production")
    monkeypatch.setattr(live, "notification_provider", "smtp")
    monkeypatch.setattr(live, "temporary_gmail_smtp_enabled", True)
    monkeypatch.setattr(live, "smtp_username", SENDER)
    monkeypatch.setattr(live, "smtp_password", SecretStr(PASSWORD))
    with caplog.at_level(logging.WARNING, logger="app.integrations.notifications"):
        warn_if_temporary_gmail_smtp()
    assert "Temporary Gmail SMTP is active" in caplog.text
    assert PASSWORD not in caplog.text and SENDER not in caplog.text


def test_no_startup_warning_without_the_temporary_route(monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "temporary_gmail_smtp_enabled", False)
    with caplog.at_level(logging.WARNING, logger="app.integrations.notifications"):
        warn_if_temporary_gmail_smtp()
    assert caplog.text == ""


def test_the_api_runs_the_warning_at_startup(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(app_main, "check_at_startup", lambda: None)
    monkeypatch.setattr(app_main, "warn_if_temporary_gmail_smtp", lambda: calls.append("warned"))

    async def start() -> None:
        async with app_main.lifespan(app_main.app):
            pass

    asyncio.run(start())
    assert calls == ["warned"]


def test_smtp_settings_are_ignored_by_other_providers():
    assert settings(notification_provider="none", smtp_host=None, smtp_password=None)


def test_the_configured_provider_reaches_the_person(monkeypatch):
    live = get_settings()
    monkeypatch.setattr(live, "notification_provider", "smtp")
    monkeypatch.setattr(live, "smtp_host", "smtp.example.rw")
    monkeypatch.setattr(live, "smtp_from_email", SENDER)
    assert isinstance(get_notification_provider(), SmtpProvider)
    assert isinstance(get_message_sender(), SmtpProvider)  # password reset works with it


# ---- transactional email settings (docs/deployment/email.md) ----------------------------------
def test_real_email_in_development_needs_an_allowlist():
    with pytest.raises(ValidationError, match="EMAIL_ALLOWED_RECIPIENTS is required"):
        settings(email_allowed_recipients="")
    configured = settings(email_allowed_recipients=" Aline@Example.rw, test@example.rw,, ")
    assert configured.allowed_email_recipients == ("aline@example.rw", "test@example.rw")
    staging = settings(
        app_env="staging",
        image_public_base_url="https://m.example.rw/m",
        email_allowed_recipients="",
    )
    assert staging.allowed_email_recipients == ()  # outside development: everyone


@pytest.mark.parametrize(
    "overrides",
    [
        {"email_allowed_recipients": "not-an-address"},
        {"staff_order_alert_emails": "orders@example.rw, two words@example.rw"},
        {"site_url": "shop.example.rw"},
        {"site_url": "https://shop.example.rw/en"},
        {
            "site_url": "http://shop.example.rw",
            "app_env": "staging",
            "image_public_base_url": "https://m.example.rw/m",
        },
    ],
)
def test_unusable_email_settings_are_refused(overrides):
    with pytest.raises(ValidationError):
        settings(**overrides)


def test_site_url_and_staff_alerts_are_normalised():
    configured = settings(
        site_url="https://shop.example.rw/", staff_order_alert_emails="A@x.rw, a@x.rw, b@x.rw"
    )
    assert configured.public_site_url == "https://shop.example.rw"
    assert configured.staff_order_alert_recipients == ("a@x.rw", "b@x.rw")
    assert settings().public_site_url is None
