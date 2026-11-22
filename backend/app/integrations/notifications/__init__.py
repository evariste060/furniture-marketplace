"""Outbound messages (SMS and email): password-reset codes (module 2) and order notifications
(module 17; plan §5 "17 — notifications"; §7 Q22).

Every provider implements NotificationProvider. No production SMS or email provider is
integrated: ADR-005 (the provider choice, credentials and delivery reports) is not decided.
NOTIFICATION_PROVIDER selects one of:
- `none`: nothing is sent. Order notifications are off; password reset answers 503.
- `console` (development only, enforced by Settings): prints each message to the process's
  terminal so the flows can be tried by hand.
- `mock`: a stand-in that accepts every order notification and delivers nothing (refused in
  production). It does not reach a person, so password reset still answers 503 with it.
- `smtp` (refused in production until ADR-005): real email through an SMTP server such as Gmail,
  for development and staging tests. Email only, so it can send no SMS. The one exception is the
  temporary Gmail test route (TEMPORARY_GMAIL_SMTP_ENABLED, enforced by Settings), which Resend
  will replace.

Provider calls happen outside database transactions; the notification service records their
results in short transactions. Providers must bound every call with a timeout (raising
DeliveryTimeout) and must never put the message text, the recipient or credentials in an
exception message: callers store and log only DeliveryError.code.
"""

import hashlib
import logging
import re
import smtplib
import ssl
import sys
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from typing import Literal, Protocol, TextIO

from app.core.config import get_settings

logger = logging.getLogger(__name__)

Channel = Literal["email", "sms"]

ERROR_CODE = re.compile(r"^[a-z0-9_]{1,64}$")


@dataclass(frozen=True)
class OutboundMessage:
    channel: Channel
    recipient: str  # canonical phone (+2507XXXXXXXX) or email address; never logged
    subject: str  # email subject; SMS providers ignore it
    text: str  # can hold a password-reset code: never logged or stored
    # Stable for every attempt of one message: providers that support idempotency must send it,
    # so a retried call for one message is delivered once.
    idempotency_key: str
    # Email only: the HTML version of `text` (sent as multipart/alternative, text first). SMS
    # providers ignore it.
    html: str | None = None


class DeliveryError(Exception):
    """The provider did not accept the message. `code` is a short fixed reason (lowercase
    letters, digits and underscores) and is the only part that is stored or logged."""

    def __init__(self, code: str, *, retryable: bool = True) -> None:
        super().__init__(code)
        self.code = code if ERROR_CODE.match(code) else "provider_error"
        self.retryable = retryable


class DeliveryTimeout(DeliveryError):
    """No answer within the provider's timeout: the message may or may not have been accepted."""

    def __init__(self) -> None:
        super().__init__("timeout", retryable=True)


class NotificationProvider(Protocol):
    name: str
    # True only when messages actually reach the person (a real provider, or the console in
    # development). Password reset requires it: a code that reaches nobody must not be issued.
    reaches_recipient: bool
    # True only when sending again with the same idempotency_key delivers nothing new. Without
    # it, a retry after a timeout or a stopped worker can deliver a message twice.
    idempotent_delivery: bool
    # The channels this provider can deliver.
    channels: tuple[Channel, ...]

    def send(self, message: OutboundMessage) -> str:
        """Hand the message to the provider and return its message ID. Raises DeliveryError
        (DeliveryTimeout when no answer came back in time)."""


class ConsoleProvider:
    """Development only (enforced by Settings): prints messages to the process's terminal. Uses
    print, not logging, on purpose: a reset code must be readable here, and log redaction would
    hide it."""

    name = "console"
    reaches_recipient = True
    idempotent_delivery = False
    channels: tuple[Channel, ...] = ("sms", "email")

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream or sys.stderr

    def send(self, message: OutboundMessage) -> str:
        print(
            f"[DEV ONLY - not sent] {message.channel} to {message.recipient}: "
            f"{message.subject}\n{message.text}",
            file=self._stream,
            flush=True,
        )
        return f"console-{uuid.uuid4().hex}"


class MockProvider:
    """§7 Q22 stand-in until ADR-005: accepts every message and delivers nothing. Its message ID
    is derived from the idempotency key, so a repeated send returns the same ID."""

    name = "mock"
    reaches_recipient = False
    idempotent_delivery = True
    channels: tuple[Channel, ...] = ("sms", "email")

    def send(self, message: OutboundMessage) -> str:
        return f"mock-{uuid.uuid5(uuid.NAMESPACE_URL, message.idempotency_key).hex}"


def _refused(code: str, status: int) -> DeliveryError:
    """An SMTP refusal: 4xx is temporary and may be retried, anything else is final."""
    return DeliveryError(code, retryable=400 <= status < 500)


class SmtpProvider:
    """Email through an SMTP server (Gmail: smtp.gmail.com, 587, STARTTLS, an app password).

    With use_tls, STARTTLS with a verified certificate comes before credentials or mail, and a
    server without it is refused, never used in plain text. Every network operation is bounded
    by `timeout`. Failures become DeliveryError with a fixed code (the server's text and the
    recipient are dropped), retryable when temporary and final when the server refuses for
    good. Once the server has accepted the message the send has succeeded, whatever happens to
    the rest of the conversation, so a failed QUIT cannot cause a second copy.

    SMTP has no idempotent delivery: if the connection is lost after the message was sent and
    before the server answered, a retry can deliver it twice. Every attempt of one message
    carries the same Message-ID, derived from its idempotency key, so a mail system that drops
    repeated IDs can recognise the copy."""

    name = "smtp"
    reaches_recipient = True
    idempotent_delivery = False
    channels: tuple[Channel, ...] = ("email",)

    def __init__(
        self,
        host: str,
        port: int,
        from_email: str,
        *,
        use_tls: bool = True,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 10,
        tls_context: ssl.SSLContext | None = None,
        from_name: str | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._from_email = from_email
        self._from_name = from_name.strip() if from_name else None
        self._use_tls = use_tls
        self._username = username
        self._password = password
        self._timeout = timeout
        self._tls_context = tls_context or ssl.create_default_context()

    def _message_id(self, key: str) -> str:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return f"<{digest}@{self._from_email.rsplit('@', 1)[-1]}>"

    def _build(self, message: OutboundMessage) -> EmailMessage:
        email = EmailMessage()
        # "FurniHub <orders@...>"; formataddr quotes and encodes the name.
        email["From"] = (
            formataddr((self._from_name, self._from_email)) if self._from_name else self._from_email
        )
        email["To"] = message.recipient
        email["Subject"] = message.subject
        email["Date"] = formatdate(usegmt=True)
        email["Message-ID"] = self._message_id(message.idempotency_key)
        email.set_content(message.text)
        if message.html:
            email.add_alternative(message.html, subtype="html")
        return email

    def _deliver(self, email: EmailMessage) -> None:
        """Connect, send and leave. A failure before the connection exists is certain; one
        during the conversation may have come after the server took the message."""
        try:
            server = smtplib.SMTP(self._host, self._port, timeout=self._timeout)
        except smtplib.SMTPResponseException as exc:
            raise _refused("connection_refused", exc.smtp_code) from None
        except OSError:
            raise DeliveryError("connection_failed") from None
        try:
            if self._use_tls:
                server.starttls(context=self._tls_context)
            if self._username and self._password:
                server.login(self._username, self._password)
            server.send_message(email)
        except BaseException:
            server.close()
            raise
        try:
            server.quit()
        except (smtplib.SMTPException, OSError):
            server.close()  # the message was accepted: this is not a failed delivery

    def send(self, message: OutboundMessage) -> str:
        if message.channel != "email":
            raise DeliveryError("channel_unsupported", retryable=False)
        try:
            email = self._build(message)
        except ValueError:  # a line break or an unusable address in a header
            raise DeliveryError("invalid_message", retryable=False) from None
        try:
            self._deliver(email)
        except DeliveryError:
            raise
        except smtplib.SMTPRecipientsRefused as exc:
            status = max((reply[0] for reply in exc.recipients.values()), default=550)
            raise _refused("recipient_refused", status) from None
        except smtplib.SMTPSenderRefused as exc:
            raise _refused("sender_refused", exc.smtp_code) from None
        except smtplib.SMTPDataError as exc:
            raise _refused("message_refused", exc.smtp_code) from None
        except smtplib.SMTPAuthenticationError:
            # Retried while attempts remain: correcting the settings can still save the message.
            raise DeliveryError("auth_failed") from None
        except smtplib.SMTPNotSupportedError:
            raise DeliveryError("smtp_not_supported") from None
        except smtplib.SMTPServerDisconnected:
            raise DeliveryError("connection_lost") from None
        except smtplib.SMTPException:
            raise DeliveryError("smtp_error") from None
        except TimeoutError:
            raise DeliveryTimeout() from None
        except ssl.SSLError:
            raise DeliveryError("tls_failed") from None
        except OSError:
            raise DeliveryError("connection_lost") from None
        except ValueError:  # an address smtplib cannot encode for this server
            raise DeliveryError("invalid_message", retryable=False) from None
        return str(email["Message-ID"])


def _smtp_provider() -> SmtpProvider:
    settings = get_settings()
    assert settings.smtp_host and settings.smtp_from_email  # enforced by Settings
    password = settings.smtp_password
    return SmtpProvider(
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_from_email,
        use_tls=settings.smtp_use_tls,
        username=settings.smtp_username,
        password=password.get_secret_value() if password else None,
        timeout=settings.smtp_timeout_seconds,
        from_name=settings.smtp_from_name,
    )


def warn_if_temporary_gmail_smtp() -> None:
    """At API startup: production is sending through the temporary Gmail test route."""
    if get_settings().temporary_gmail_smtp_active:
        logger.warning(
            "Temporary Gmail SMTP is active with APP_ENV=production: owner testing only. "
            "Replace it with Resend before launch."
        )


def get_notification_provider() -> NotificationProvider | None:
    """FastAPI dependency (and the retry script): the configured provider, or None for `none`."""
    match get_settings().notification_provider:
        case "console":
            return ConsoleProvider()
        case "mock":
            return MockProvider()
        case "smtp":
            return _smtp_provider()
        case _:
            return None


def email_allowed(recipient: str) -> bool:
    """EMAIL_ALLOWED_RECIPIENTS: when set, email may reach those addresses only (development
    tests with real Gmail). Empty: every address."""
    allowed = get_settings().allowed_email_recipients
    return not allowed or recipient.strip().lower() in allowed


def get_message_sender() -> NotificationProvider | None:
    """FastAPI dependency for password reset: the configured provider only when it reaches the
    person (never the mock), else None (the reset endpoints then answer 503)."""
    provider = get_notification_provider()
    return provider if provider is not None and provider.reaches_recipient else None
