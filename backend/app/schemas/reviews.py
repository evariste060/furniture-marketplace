"""Product review schemas (module 20, scope change SC-01 approved by the project owner 2026-10-27).

Review text is plain text: control and other non-printable characters are removed and the ends
trimmed (as banners), except that the body keeps its line breaks (at most one blank line in a
row); blank becomes null. It is stored and returned as text and the storefront never renders it
as HTML.
"""

import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

from app.models.engagement import (
    MODERATION_REASON_MAX_LENGTH,
    REVIEW_BODY_MAX_LENGTH,
    REVIEW_TITLE_MAX_LENGTH,
)
from app.schemas.banners import plain_text
from app.schemas.images import PublicImage
from app.schemas.order import OrderLookupRequest

ReviewStatus = Literal["pending", "approved", "rejected"]
LinkStatus = Literal["open", "expired", "used"]


def _blank_to_none(value: object) -> object:
    value = plain_text(value)
    return None if value == "" else value


def _paragraphs(value: object) -> object:
    """Plain text per line; line breaks kept, runs of blank lines reduced to one."""
    if not isinstance(value, str):
        return value
    lines = [plain_text(line) for line in value.replace("\r\n", "\n").split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text or None


def _text(max_length: int, *, multiline: bool = False):  # noqa: ANN202 - an Annotated type
    return Annotated[
        Annotated[str, StringConstraints(max_length=max_length)] | None,
        BeforeValidator(_paragraphs if multiline else _blank_to_none),
    ]


# ---- review links ----------------------------------------------------------------------------


class ReviewLinkResponse(BaseModel):
    """A single-use link to review one delivered order item. The token is shown only here; the
    storefront page is /review/{token}."""

    token: str = Field(description="Secret; put it in the link and nowhere else")
    expires_at: datetime = Field(description="90 days after delivery")


class GuestReviewLinkRequest(OrderLookupRequest):
    """The guest's order lookup (order number and phone) plus the delivered item to review."""

    model_config = ConfigDict(extra="forbid")

    order_item_id: uuid.UUID


class ReviewLinkProduct(BaseModel):
    name: str
    slug: str | None = Field(description="null when the product is no longer sold")
    image: PublicImage | None


class ReviewLinkInfo(BaseModel):
    """What the review page shows before the review is sent. `open`: the form; `expired`:
    the link is past its date; `used`: already reviewed."""

    status: LinkStatus
    expires_at: datetime
    product: ReviewLinkProduct
    variant_name: str | None


# ---- submitting ------------------------------------------------------------------------------


class ReviewSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: int = Field(ge=1, le=5, description="Stars, 1 to 5")
    title: _text(REVIEW_TITLE_MAX_LENGTH) = Field(  # type: ignore[valid-type]
        default=None, description=f"Optional, at most {REVIEW_TITLE_MAX_LENGTH} characters"
    )
    body: _text(REVIEW_BODY_MAX_LENGTH, multiline=True) = Field(  # type: ignore[valid-type]
        default=None, description=f"Optional, at most {REVIEW_BODY_MAX_LENGTH} characters"
    )


class ReviewSubmitResponse(BaseModel):
    id: uuid.UUID
    status: ReviewStatus = Field(description="Always pending: a moderator approves it first")


# ---- public list -----------------------------------------------------------------------------


class PublicReview(BaseModel):
    id: uuid.UUID
    rating: int
    title: str | None
    body: str | None
    author_name: str = Field(description="First name and last initial, e.g. 'Aline U.'")
    verified_purchase: bool = Field(
        default=True, description="Always true: only buyers of a delivered item can review"
    )
    created_at: datetime


# ---- moderation ------------------------------------------------------------------------------


class StaffReview(BaseModel):
    id: uuid.UUID
    status: ReviewStatus
    rating: int
    title: str | None
    body: str | None
    author_name: str
    product_id: uuid.UUID
    product_name: str
    product_slug: str
    order_number: str
    moderation_reason: str | None
    moderated_at: datetime | None
    created_at: datetime


class RejectReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: _text(MODERATION_REASON_MAX_LENGTH) = Field(  # type: ignore[valid-type]
        default=None, description="Optional; staff only, never shown to the customer"
    )


class ApproveReviewRequest(RejectReviewRequest):
    pass
