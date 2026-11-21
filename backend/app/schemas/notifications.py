"""Staff view of the message outbox (module 17; docs/deployment/email.md). Operational facts
only: the recipient is masked and no message text is exposed (none is stored); last_error is a
sanitised code."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

NotificationEvent = Literal[
    "received",
    "staff_new_order",
    "payment_succeeded",
    "confirmed",
    "dispatched",
    "delivered",
    "cancelled",
    "welcome",
    "quote_received",
    "review_thanks",
    "support_reply",
]
NotificationSubject = Literal["order", "user", "quote", "review", "support"]
NotificationChannel = Literal["sms", "email"]
NotificationStatus = Literal["pending", "sent", "failed"]


class NotificationItem(BaseModel):
    id: UUID
    subject_type: NotificationSubject = Field(
        description="What the message is about: an order, a new account (welcome), a quote "
        "request or a review"
    )
    order_id: UUID | None = Field(description="Set for order messages only")
    order_number: str | None = Field(description="Set for order messages only")
    event: NotificationEvent
    channel: NotificationChannel
    recipient: str = Field(
        description="Masked: phone prefix and last 3 digits, or the email's first letter and "
        "domain. The full value is on the order."
    )
    status: NotificationStatus = Field(
        description="pending: no attempt finished yet; sent: accepted by the provider; failed: "
        "the last attempt failed (retried at next_attempt_at while attempts remain, final when "
        "next_attempt_at is null)."
    )
    attempts: int = Field(ge=0, description="Delivery attempts used")
    max_attempts: int = Field(description="Attempts allowed in all (3)")
    in_progress: bool = Field(description="A worker is sending it now")
    last_error: str | None = Field(
        description="Sanitised code of the last failure; never provider text. timeout, "
        "invalid_provider_response, unexpected_error:<type> and outcome_unknown mean the outcome "
        "is unknown (the provider may have accepted the message); recipient_not_allowed: the "
        "address is not in EMAIL_ALLOWED_RECIPIENTS (never sent); subject_missing: the record "
        "the message is about no longer exists; any other code is a refusal by the provider"
    )
    provider_message_id: str | None
    next_attempt_at: datetime | None
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime
