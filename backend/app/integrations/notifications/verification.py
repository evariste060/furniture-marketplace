"""The mailer for email verification links (ADR-006 amendment 2026-11-12).

It wraps the configured notification provider (app.integrations.notifications) and the
storefront page that receives the link. Verification needs both: a provider that actually
reaches people by email (the console in development, SMTP in development and staging), and
SITE_URL to build the link from. Without either, registration with an email address and resend
answer 503 instead of creating a link nobody can receive. Tests override the dependency with a
recording provider.

The token travels in the URL fragment (`#token=…`), which browsers never send to servers or in
the Referer header, so it stays out of access logs; the storefront page reads it and POSTs it to
/api/v1/auth/email/verify.
"""

from dataclasses import dataclass

from app.core.config import get_settings
from app.integrations.notifications import NotificationProvider, get_message_sender

VERIFY_PATH = "/verify-email"


@dataclass(frozen=True)
class VerificationMailer:
    sender: NotificationProvider
    # The storefront's verification page, e.g. https://shop.example.rw/verify-email.
    page_url: str

    def link(self, token: str) -> str:
        return f"{self.page_url}#token={token}"


def get_verification_mailer() -> VerificationMailer | None:
    """FastAPI dependency: the mailer, or None while verification email cannot be delivered."""
    sender = get_message_sender()
    site = get_settings().public_site_url
    if sender is None or "email" not in sender.channels or not site:
        return None
    return VerificationMailer(sender=sender, page_url=f"{site}{VERIFY_PATH}")
