"""Technical services schemas (ADR-013, SC-02, approved 2026-11-17).

Text is plain text: control and other non-printable characters are removed and the ends trimmed;
the intro and the request message keep their line breaks. Blank optional fields become null.
The phone is a Rwandan mobile number in any accepted form and is stored canonical
(+2507XXXXXXXX); the email, when given, is stored in lower case. No prices: services are not sold
online.
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
    field_validator,
)

from app.core.identifiers import validate_email_format, validate_rwanda_phone
from app.core.slugs import SLUG_PATTERN
from app.models.services import (
    REQUEST_EMAIL_MAX_LENGTH,
    REQUEST_LOCATION_MAX_LENGTH,
    REQUEST_MESSAGE_MAX_LENGTH,
    REQUEST_NAME_MAX_LENGTH,
    REQUEST_NOTES_MAX_LENGTH,
    SERVICE_INTRO_MAX_LENGTH,
    SERVICE_ITEM_MAX_LENGTH,
    SERVICE_NAME_MAX_LENGTH,
    SERVICE_SHORT_MAX_LENGTH,
    SERVICE_SLUG_MAX_LENGTH,
)
from app.schemas.banners import plain_text
from app.schemas.images import PublicImage
from app.schemas.reviews import _blank_to_none, _paragraphs

ServiceIcon = Literal[
    "cctv", "gate", "fingerprint", "network", "wrench", "graduation-cap", "shield", "cpu"
]
ClientType = Literal["home", "business", "institution"]
RequestStatus = Literal["new", "contacted", "scheduled", "completed", "cancelled"]
Locale = Literal["en", "rw"]
HONEYPOT_MAX_LENGTH = 200


def _len(min_length: int, max_length: int) -> StringConstraints:
    return StringConstraints(min_length=min_length, max_length=max_length)


def _email(value: str | None) -> str | None:
    return None if value is None else validate_email_format(value)


Slug = Annotated[
    str, StringConstraints(min_length=1, max_length=SERVICE_SLUG_MAX_LENGTH, pattern=SLUG_PATTERN)
]
Name = Annotated[str, BeforeValidator(plain_text), _len(2, SERVICE_NAME_MAX_LENGTH)]
Short = Annotated[str, BeforeValidator(plain_text), _len(2, SERVICE_SHORT_MAX_LENGTH)]
Intro = Annotated[str, BeforeValidator(_paragraphs), _len(2, SERVICE_INTRO_MAX_LENGTH)]
ItemTitle = Annotated[str, BeforeValidator(plain_text), _len(2, SERVICE_ITEM_MAX_LENGTH)]
FullName = Annotated[str, BeforeValidator(plain_text), _len(2, REQUEST_NAME_MAX_LENGTH)]
OptionalName = Annotated[
    Annotated[str, _len(0, SERVICE_NAME_MAX_LENGTH)] | None, BeforeValidator(_blank_to_none)
]
OptionalShort = Annotated[
    Annotated[str, _len(0, SERVICE_SHORT_MAX_LENGTH)] | None, BeforeValidator(_blank_to_none)
]
OptionalIntro = Annotated[
    Annotated[str, _len(0, SERVICE_INTRO_MAX_LENGTH)] | None, BeforeValidator(_paragraphs)
]
OptionalItemTitle = Annotated[
    Annotated[str, _len(0, SERVICE_ITEM_MAX_LENGTH)] | None, BeforeValidator(_blank_to_none)
]
OptionalLocation = Annotated[
    Annotated[str, _len(0, REQUEST_LOCATION_MAX_LENGTH)] | None, BeforeValidator(_blank_to_none)
]
OptionalMessage = Annotated[
    Annotated[str, _len(0, REQUEST_MESSAGE_MAX_LENGTH)] | None, BeforeValidator(_paragraphs)
]
OptionalNotes = Annotated[
    Annotated[str, _len(0, REQUEST_NOTES_MAX_LENGTH)] | None, BeforeValidator(_paragraphs)
]
SLUG_DESCRIPTION = (
    "Lowercase letters, digits and single hyphens; generated from the English name when omitted"
)


# ---- public ------------------------------------------------------------------------------------
class PublicServiceItem(BaseModel):
    id: uuid.UUID
    title: str


class PublicServiceSummary(BaseModel):
    """A service card: texts in the asked language (English where no Kinyarwanda is written)."""

    slug: str
    name: str
    short_description: str
    icon: ServiceIcon
    image: PublicImage | None


class PublicService(PublicServiceSummary):
    intro: str
    items: list[PublicServiceItem]


class PublicServiceWithItems(PublicServiceSummary):
    items: list[PublicServiceItem]


class ServiceRequestCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "full_name": "Aline Uwase",
                    "phone": "0788123456",
                    "email": "aline@example.rw",
                    "location": "Kicukiro, Kigali",
                    "client_type": "business",
                    "message": "Eight cameras for our shop.",
                    "preferred_date": "2026-12-01",
                    "locale": "en",
                }
            ]
        },
    )

    full_name: FullName
    phone: Annotated[
        str, StringConstraints(max_length=32), AfterValidator(validate_rwanda_phone)
    ] = Field(description="Rwandan mobile number: +2507XXXXXXXX, 2507XXXXXXXX or 07XXXXXXXX")
    email: Annotated[
        Annotated[str, StringConstraints(max_length=REQUEST_EMAIL_MAX_LENGTH)] | None,
        BeforeValidator(_blank_to_none),
        AfterValidator(_email),
    ] = None
    location: OptionalLocation = None
    client_type: ClientType
    message: OptionalMessage = None
    preferred_date: date | None = Field(
        default=None, description="From today (Kigali time) up to one year ahead"
    )
    locale: Locale = Field(default="en", description="The language to reply in")
    website: Annotated[str, StringConstraints(max_length=HONEYPOT_MAX_LENGTH)] | None = Field(
        default=None,
        description="Leave empty. A hidden field: a request that fills it is not stored.",
    )


class ServiceRequestCreated(BaseModel):
    reference: str = Field(description="SR-YYMMDD-XXXXXX, to quote when calling the store")


# ---- staff: services ---------------------------------------------------------------------------
class StaffServiceItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title_en: str
    title_rw: str | None
    sort_order: int


class StaffService(BaseModel):
    id: uuid.UUID
    slug: str
    name_en: str
    name_rw: str | None
    short_description_en: str
    short_description_rw: str | None
    intro_en: str
    intro_rw: str | None
    icon: ServiceIcon
    image: PublicImage | None
    sort_order: int
    is_active: bool
    items: list[StaffServiceItem]
    request_count: int = Field(description="Requests for this service; one or more blocks delete")
    created_at: datetime
    updated_at: datetime


class ServiceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: Slug | None = Field(default=None, description=SLUG_DESCRIPTION)
    name_en: Name
    name_rw: OptionalName = None
    short_description_en: Short
    short_description_rw: OptionalShort = None
    intro_en: Intro
    intro_rw: OptionalIntro = None
    icon: ServiceIcon
    is_active: bool = True


class ServiceUpdateRequest(BaseModel):
    """Only the fields sent change. The English texts, slug, icon and is_active cannot be null;
    a Kinyarwanda text sent as null or blank is removed."""

    model_config = ConfigDict(extra="forbid")

    slug: Slug | None = None
    name_en: Name | None = None
    name_rw: OptionalName = None
    short_description_en: Short | None = None
    short_description_rw: OptionalShort = None
    intro_en: Intro | None = None
    intro_rw: OptionalIntro = None
    icon: ServiceIcon | None = None
    is_active: bool | None = None

    @field_validator("slug", "name_en", "short_description_en", "intro_en", "icon", "is_active")
    @classmethod
    def not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("This field cannot be empty.")
        return value


class ServiceOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_ids: list[uuid.UUID] = Field(
        min_length=1, max_length=200, description="Every service, in the new order"
    )


class ServiceItemCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title_en: ItemTitle
    title_rw: OptionalItemTitle = None


class ServiceItemUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title_en: ItemTitle | None = None
    title_rw: OptionalItemTitle = None

    @field_validator("title_en")
    @classmethod
    def not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("This field cannot be empty.")
        return value


class ServiceItemOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_ids: list[uuid.UUID] = Field(
        min_length=1, max_length=100, description="Every item of the service, in the new order"
    )


# ---- staff: requests ---------------------------------------------------------------------------
class ServiceRef(BaseModel):
    id: uuid.UUID
    slug: str
    name: str


class StaffRef(BaseModel):
    id: uuid.UUID
    name: str


class StaffServiceRequest(BaseModel):
    id: uuid.UUID
    reference: str
    service: ServiceRef
    full_name: str
    phone: str
    email: str | None
    location: str | None
    client_type: ClientType
    message: str | None
    preferred_date: date | None
    locale: Locale
    status: RequestStatus
    status_changed_at: datetime | None
    assigned_to: StaffRef | None
    internal_notes: str | None
    created_at: datetime
    updated_at: datetime


class ServiceRequestUpdate(BaseModel):
    """Only the fields sent change: status, the assignee (null unassigns) and the notes (null
    or blank clears them)."""

    model_config = ConfigDict(extra="forbid")

    status: RequestStatus | None = None
    assigned_to_user_id: uuid.UUID | None = None
    internal_notes: OptionalNotes = None

    @field_validator("status")
    @classmethod
    def status_not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("This field cannot be empty.")
        return value
