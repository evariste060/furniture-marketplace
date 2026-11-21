"""Customer support message schemas (approved 2026-11-11).

Text is plain text: control and other non-printable characters are removed and the ends trimmed;
message bodies keep their line breaks. Blank optional fields become null. A phone, when given, is
a Rwandan mobile number stored canonical (+2507XXXXXXXX); an email is stored in lower case. A new
message needs a phone or an email so staff can answer it.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.core.identifiers import validate_email_format, validate_rwanda_phone
from app.models.support import (
    SUPPORT_BODY_MAX_LENGTH,
    SUPPORT_NAME_MAX_LENGTH,
    SUPPORT_ORDER_NUMBER_MAX_LENGTH,
    SUPPORT_SUBJECT_MAX_LENGTH,
)
from app.schemas.banners import plain_text
from app.schemas.reviews import _blank_to_none, _paragraphs

SupportStatus = Literal["open", "answered", "closed"]
SupportAuthor = Literal["customer", "staff"]
SupportLocale = Literal["en", "rw"]
SupportTopic = Literal["order", "product", "payment", "warranty", "returns", "other"]


def _email(value: str | None) -> str | None:
    return None if value is None else validate_email_format(value)


def _phone(value: str | None) -> str | None:
    return None if value is None else validate_rwanda_phone(value)


def _upper(value: str | None) -> str | None:
    return None if value is None else value.upper()


NameText = Annotated[
    str,
    BeforeValidator(plain_text),
    StringConstraints(min_length=2, max_length=SUPPORT_NAME_MAX_LENGTH),
]
SubjectText = Annotated[
    str,
    BeforeValidator(plain_text),
    StringConstraints(min_length=3, max_length=SUPPORT_SUBJECT_MAX_LENGTH),
]
BodyText = Annotated[
    str,
    BeforeValidator(_paragraphs),
    StringConstraints(min_length=2, max_length=SUPPORT_BODY_MAX_LENGTH),
]
OptionalPhone = Annotated[
    Annotated[str, StringConstraints(max_length=32)] | None,
    BeforeValidator(_blank_to_none),
    AfterValidator(_phone),
]
OptionalEmail = Annotated[
    Annotated[str, StringConstraints(max_length=254)] | None,
    BeforeValidator(_blank_to_none),
    AfterValidator(_email),
]
OptionalOrderNumber = Annotated[
    Annotated[str, StringConstraints(max_length=SUPPORT_ORDER_NUMBER_MAX_LENGTH)] | None,
    BeforeValidator(_blank_to_none),
    AfterValidator(_upper),
]


class SupportMessageCreate(BaseModel):
    """A new question from the Contact page."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "topic": "order",
                    "name": "Aline Uwase",
                    "phone": "0788123456",
                    "email": "aline@example.rw",
                    "subject": "Delivery to Musanze",
                    "order_number": "3S-260101-0001",
                    "body": "Hello, when will my order reach Musanze?",
                    "locale": "en",
                }
            ]
        },
    )

    topic: SupportTopic = Field(description="What the question is about")
    name: NameText
    phone: OptionalPhone = Field(
        default=None, description="Rwandan mobile number: +2507XXXXXXXX, 2507XXXXXXXX or 07XXXXXXXX"
    )
    email: OptionalEmail = Field(default=None, description="Replies are emailed here")
    subject: SubjectText
    order_number: OptionalOrderNumber = Field(default=None, description="When it is about an order")
    body: BodyText
    locale: SupportLocale = Field(default="en", description="The language to reply in")

    @model_validator(mode="after")
    def _needs_contact(self) -> "SupportMessageCreate":
        if self.phone is None and self.email is None:
            raise ValueError("Give a phone number or an email address so we can reply.")
        return self


class SupportReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: BodyText


class SupportStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SupportStatus


class SupportCreated(BaseModel):
    reference: str = Field(description="M-YYMMDD-XXXXXX, to quote when contacting the store")
    access_key: str = Field(
        description=(
            "Secret: with the reference it opens the conversation without an account "
            "(GET /support-messages/{reference}/{access_key}); the reply email links to it too"
        )
    )


class SupportMessageItem(BaseModel):
    id: uuid.UUID
    author: SupportAuthor
    body: str
    created_at: datetime


class StaffSupportMessageItem(SupportMessageItem):
    staff_name: str | None = Field(description="The staff member who wrote a staff message")


class SupportThreadSummary(BaseModel):
    """A conversation in a list: its last message is cut to 160 characters."""

    id: uuid.UUID
    reference: str
    topic: SupportTopic
    subject: str
    order_number: str | None
    status: SupportStatus
    message_count: int
    last_author: SupportAuthor
    last_preview: str
    last_message_at: datetime
    created_at: datetime


class StaffSupportThreadSummary(SupportThreadSummary):
    name: str
    phone: str | None
    email: str | None
    has_account: bool


class SupportThreadDetail(SupportThreadSummary):
    messages: list[SupportMessageItem]


class StaffSupportThreadDetail(StaffSupportThreadSummary):
    locale: SupportLocale
    messages: list[StaffSupportMessageItem]
