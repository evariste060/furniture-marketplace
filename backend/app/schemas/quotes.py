"""Business quote request schemas (module 19; Contact page, PR-01).

Text is plain text: control and other non-printable characters are removed and the ends trimmed;
the message keeps its line breaks. Blank optional fields become null. The phone is a Rwandan
mobile number in any accepted form and is stored canonical (+2507XXXXXXXX); the email, when
given, is stored in lower case. No prices: staff reply outside the store.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
)

from app.core.identifiers import validate_email_format, validate_rwanda_phone
from app.models.content import (
    QUOTE_COMPANY_MAX_LENGTH,
    QUOTE_CONTACT_MAX_LENGTH,
    QUOTE_LINES_MAX,
    QUOTE_LOCATION_MAX_LENGTH,
    QUOTE_MESSAGE_MAX_LENGTH,
    QUOTE_PRODUCT_MAX_LENGTH,
    QUOTE_QUANTITY_MAX,
)
from app.schemas.banners import plain_text
from app.schemas.reviews import _blank_to_none, _paragraphs

QuoteStatus = Literal["new", "contacted", "closed"]
QuoteLocale = Literal["en", "rw"]


def _email(value: str | None) -> str | None:
    return None if value is None else validate_email_format(value)


def _phone(value: str) -> str:
    return validate_rwanda_phone(value)


def _plain(min_length: int, max_length: int) -> object:
    return StringConstraints(min_length=min_length, max_length=max_length)


ProductText = Annotated[str, BeforeValidator(plain_text), _plain(1, QUOTE_PRODUCT_MAX_LENGTH)]
CompanyText = Annotated[str, BeforeValidator(plain_text), _plain(2, QUOTE_COMPANY_MAX_LENGTH)]
ContactText = Annotated[str, BeforeValidator(plain_text), _plain(2, QUOTE_CONTACT_MAX_LENGTH)]
OptionalEmail = Annotated[
    Annotated[str, StringConstraints(max_length=254)] | None,
    BeforeValidator(_blank_to_none),
    AfterValidator(_email),
]
OptionalLocation = Annotated[
    Annotated[str, StringConstraints(max_length=QUOTE_LOCATION_MAX_LENGTH)] | None,
    BeforeValidator(_blank_to_none),
]
OptionalMessage = Annotated[
    Annotated[str, StringConstraints(max_length=QUOTE_MESSAGE_MAX_LENGTH)] | None,
    BeforeValidator(_paragraphs),
]


class QuoteLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: ProductText = Field(description="Product name or model, as the buyer writes it")
    quantity: int = Field(strict=True, ge=1, le=QUOTE_QUANTITY_MAX)


class QuoteRequestCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "company": "Green Hills Academy",
                    "contact_name": "Aline Uwase",
                    "phone": "0788123456",
                    "email": "procurement@example.rw",
                    "lines": [{"product": "HP Pavilion 15 Laptop", "quantity": 25}],
                    "delivery_location": "Gasabo",
                    "needed_by": "2026-12-01",
                    "message": "We need invoices with our TIN.",
                    "locale": "en",
                }
            ]
        },
    )

    company: CompanyText
    contact_name: ContactText
    phone: Annotated[str, StringConstraints(max_length=32), AfterValidator(_phone)] = Field(
        description="Rwandan mobile number: +2507XXXXXXXX, 2507XXXXXXXX or 07XXXXXXXX"
    )
    email: OptionalEmail = None
    lines: list[QuoteLine] = Field(min_length=1, max_length=QUOTE_LINES_MAX)
    delivery_location: OptionalLocation = None
    needed_by: date | None = Field(
        default=None, description="From today (Kigali time) up to one year ahead"
    )
    message: OptionalMessage = None
    locale: QuoteLocale = Field(default="en", description="The language to reply in")


class QuoteRequestCreated(BaseModel):
    reference: str = Field(description="Q-YYMMDD-XXXXXX, to quote when calling the store")


class StaffQuoteRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference: str
    company: str
    contact_name: str
    phone: str
    email: str | None
    lines: list[QuoteLine]
    delivery_location: str | None
    needed_by: date | None
    message: str | None
    locale: QuoteLocale
    status: QuoteStatus
    handled_by_user_id: uuid.UUID | None
    handled_at: datetime | None
    created_at: datetime


class QuoteStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: QuoteStatus
