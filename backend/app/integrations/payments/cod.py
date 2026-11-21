"""The `cod` provider: cash on delivery (§7 Q13, Q14; TC-12).

No external party and no webhooks. The checkout attempt is 'pending' (payment due on delivery)
and becomes 'succeeded' only when the order is delivered (Q14) or staff with payments:manage
record the cash as collected for a delivered order. Nothing is ever paid at order time.
"""

from app.integrations.payments import (
    Initiation,
    InvalidWebhook,
    OrderForPayment,
    ProviderEvent,
    WebhookRequest,
)


class CodProvider:
    name = "cod"
    idempotent_initiation = True  # no external call; the reference is the order number

    def initiate(self, order: OrderForPayment) -> Initiation:
        return Initiation(
            reference=f"COD-{order.order_number}",
            status="pending",
            instructions="Pay in cash when the order is delivered.",
        )

    def verify_webhook(self, request: WebhookRequest) -> None:
        raise InvalidWebhook("cash on delivery has no webhooks")

    def parse_event(self, request: WebhookRequest) -> ProviderEvent:
        raise InvalidWebhook("cash on delivery has no webhooks")

    def check_status(self, reference: str) -> None:
        return None
