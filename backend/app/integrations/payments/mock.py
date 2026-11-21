"""The `mock` payment provider (§7 Q21): a stand-in for mobile money until ADR-003.

It moves no money and calls nothing outside the API. Initiation returns a fresh reference and
'pending'; the outcome arrives as a webhook the test harness or an operator sends, signed with
PAYMENT_MOCK_WEBHOOK_SECRET:

    X-Mock-Timestamp: <unix seconds>
    X-Mock-Signature: sha256=<hex HMAC-SHA256 of "<timestamp>.<raw body>">

Body (JSON): {"event_id", "reference", "status": "pending"|"succeeded"|"failed"|"cancelled",
"amount" (whole RWF), "currency": "RWF", optional "payer_phone", "occurred_at", "reason"}.
"reason" is kept only as one of REASON_CODES (anything else becomes "other"): free text from a
provider could carry personal data.
A missing or wrong signature, or a timestamp outside PAYMENT_WEBHOOK_TOLERANCE_SECONDS, is
refused. Only allow-listed fields reach payload_metadata; the payer phone is masked.
"""

import hashlib
import hmac
import json
import re
import time
from typing import cast

from app.core.config import get_settings
from app.core.identifiers import validate_rwanda_phone
from app.integrations.payments import (
    EventStatus,
    Initiation,
    InvalidWebhook,
    MalformedWebhook,
    OrderForPayment,
    ProviderEvent,
    ProviderNotConfigured,
    WebhookRequest,
)

STATUSES = {"pending", "succeeded", "failed", "cancelled"}
REASON_CODES = {
    "insufficient_funds",
    "declined",
    "cancelled_by_payer",
    "timeout",
    "expired",
    "provider_error",
}
REFERENCE = re.compile(r"^[A-Za-z0-9_.:-]{6,180}$")
EVENT_ID = re.compile(r"^[A-Za-z0-9_.:-]{6,200}$")
MAX_BODY = 16 * 1024


def _secret() -> bytes:
    secret = get_settings().payment_mock_webhook_secret
    value = secret.get_secret_value() if secret is not None else ""
    if not value:
        raise ProviderNotConfigured("The mock payment provider is not configured.")
    return value.encode("utf8")


def sign(body: bytes, timestamp: int, secret: str) -> str:
    """The signature header value for a body (used by tests and operators)."""
    mac = hmac.new(secret.encode("utf8"), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def mask_phone(value: object) -> str | None:
    """Keep the country prefix and the last 3 digits only (e.g. +250******456). A Rwandan
    number in any accepted format is made canonical first, so it always masks the same way."""
    if not isinstance(value, str):
        return None
    try:
        value = validate_rwanda_phone(value)
    except ValueError:
        pass
    digits = re.sub(r"\D", "", value)
    if len(digits) < 6:
        return None
    return f"+{digits[:3]}{'*' * (len(digits) - 6)}{digits[-3:]}"


def _reason_code(value: object) -> str:
    """An allow-listed reason code, or "other": provider free text is never stored."""
    return value if isinstance(value, str) and value in REASON_CODES else "other"


class MockProvider:
    name = "mock"
    # The reference is derived from the idempotency key: initiating again for the same attempt
    # returns the same reference, never a second payment.
    idempotent_initiation = True

    def initiate(self, order: OrderForPayment) -> Initiation:
        _secret()  # refuse to start what no webhook could ever complete
        digest = hashlib.sha256(order.idempotency_key.encode("utf8")).hexdigest()
        return Initiation(
            reference=f"MOCK-{digest[:24].upper()}",
            status="pending",
            instructions=(
                "Test payment: no real mobile-money request is sent. The result arrives through "
                "the mock provider's signed webhook."
            ),
        )

    def verify_webhook(self, request: WebhookRequest) -> None:
        key = _secret()
        timestamp = request.headers.get("x-mock-timestamp", "")
        signature = request.headers.get("x-mock-signature", "")
        if not timestamp.isdigit() or not signature.startswith("sha256="):
            raise InvalidWebhook("missing signature")
        tolerance = get_settings().payment_webhook_tolerance_seconds
        if abs(time.time() - int(timestamp)) > tolerance:
            raise InvalidWebhook("stale timestamp")
        expected = hmac.new(key, f"{timestamp}.".encode() + request.body, hashlib.sha256)
        if not hmac.compare_digest(f"sha256={expected.hexdigest()}", signature):
            raise InvalidWebhook("bad signature")

    def parse_event(self, request: WebhookRequest) -> ProviderEvent:
        if len(request.body) > MAX_BODY:
            raise MalformedWebhook("payload too large")
        try:
            data = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            raise MalformedWebhook("not JSON") from None
        if not isinstance(data, dict):
            raise MalformedWebhook("not an object")
        event_id, reference = data.get("event_id"), data.get("reference")
        status, amount, currency = data.get("status"), data.get("amount"), data.get("currency")
        if not isinstance(event_id, str) or not EVENT_ID.match(event_id):
            raise MalformedWebhook("event_id")
        if not isinstance(reference, str) or not REFERENCE.match(reference):
            raise MalformedWebhook("reference")
        if not isinstance(status, str) or status not in STATUSES:
            raise MalformedWebhook("status")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            raise MalformedWebhook("amount")
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            raise MalformedWebhook("currency")
        metadata = {
            "event_type": status,
            "reference": reference,
            "amount": amount,
            "currency": currency,
            "payer_phone_masked": mask_phone(data.get("payer_phone")),
            "occurred_at": str(data["occurred_at"])[:40] if "occurred_at" in data else None,
            "reason": _reason_code(data.get("reason")) if "reason" in data else None,
        }
        return ProviderEvent(
            event_key=event_id,
            reference=reference,
            status=cast(EventStatus, status),  # checked against STATUSES above
            amount=amount,
            currency_code=currency,
            metadata={k: v for k, v in metadata.items() if v is not None},
        )

    def check_status(self, reference: str) -> None:
        """The mock keeps no remote state: it cannot tell (the stored attempt is authoritative)."""
        return None
