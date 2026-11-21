"""Payment providers (module 15; plan §5 "15 — payments"; §7 Q21; ADR-002 payment consistency).

Every provider implements PaymentProvider. Until ADR-003 chooses real providers and sandbox
credentials exist (§7 Q21):
- `mock` serves mobile money (`mtn_momo`, `airtel_money`). It is a stand-in, not an MTN MoMo or
  Airtel Money integration: it moves no money, and its webhooks are HMAC-SHA256 signed with
  PAYMENT_MOCK_WEBHOOK_SECRET (configuration only; refused in production).
- `cod` serves cash on delivery: no external call; the attempt stays pending until delivery.
- Card payments stay disabled: no provider is registered for `card`.

Provider calls happen outside database transactions (ADR-002); the payment service applies
their results in short transactions.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

EventStatus = Literal["pending", "succeeded", "failed", "cancelled"]


class ProviderError(Exception):
    """The provider definitely started no payment: it refused the request, or the request
    never left (safe message). The attempt is marked failed."""


class ProviderNotConfigured(ProviderError):
    pass


class ProviderOutcomeUnknown(Exception):  # deliberately not a ProviderError
    """The request may have reached the provider, but no answer came back (a timeout or a
    transport error after sending): a payment may have started. Never treated as a failure."""


class InvalidWebhook(Exception):
    """Authenticity could not be verified (bad or missing signature, stale timestamp)."""


class MalformedWebhook(Exception):
    """The verified payload is not a valid event."""


@dataclass(frozen=True)
class WebhookRequest:
    headers: Mapping[str, str]  # lower-cased names
    body: bytes


@dataclass(frozen=True)
class OrderForPayment:
    order_id: str
    order_number: str
    amount: int
    currency_code: str
    method: str
    phone: str  # canonical; never logged or stored by providers
    # The attempt's idempotency key: real adapters must send it to the provider (as its
    # idempotency or merchant reference), so a retried call for one attempt is one payment.
    idempotency_key: str


@dataclass(frozen=True)
class Initiation:
    reference: str  # the provider's transaction reference
    status: EventStatus
    instructions: str  # shown to the customer


@dataclass(frozen=True)
class ProviderEvent:
    event_key: str  # provider-scoped, stable: the deduplication key
    reference: str
    status: EventStatus
    amount: int
    currency_code: str
    metadata: dict  # sanitised, allow-listed facts only


class PaymentProvider(Protocol):
    name: str
    # True only when the adapter guarantees that initiate() called again with the same
    # idempotency_key starts no second payment (it returns, or is refused for, the first one).
    # Only then may a stale initiation claim be retried; real adapters default to False until
    # their provider's idempotency support is confirmed (ADR-003).
    idempotent_initiation: bool

    def initiate(self, order: OrderForPayment) -> Initiation:
        """Start a payment; raises ProviderError."""

    def verify_webhook(self, request: WebhookRequest) -> None:
        """Raise InvalidWebhook unless the request comes from the provider."""

    def parse_event(self, request: WebhookRequest) -> ProviderEvent:
        """The event of a verified request; raises MalformedWebhook."""

    def check_status(self, reference: str) -> EventStatus | None:
        """The provider's current status for a reference, or None when it cannot tell."""


METHOD_PROVIDERS: dict[str, str] = {  # §7 Q21; card has none (disabled)
    "mtn_momo": "mock",
    "airtel_money": "mock",
    "cash_on_delivery": "cod",
}


def get_provider(name: str) -> PaymentProvider | None:
    """The configured provider by name, or None for an unknown one."""
    from app.integrations.payments.cod import CodProvider
    from app.integrations.payments.mock import MockProvider

    providers: dict[str, PaymentProvider] = {"mock": MockProvider(), "cod": CodProvider()}
    return providers.get(name)
