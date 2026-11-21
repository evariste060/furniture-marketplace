"""Homepage banner schemas (approved 2026-10-26, checkpoint 1b topic 9; 'content:manage').

All text is plain text: control and other non-printable characters are removed, outer whitespace
is trimmed, and the storefront renders it as text (never as HTML). The CTA URL must be an
on-site path: it starts with a single "/", uses only URL-safe characters, and is checked again
after one round of percent-decoding, so "//host", "/\\host", backslashes, whitespace, control
characters and schemes (javascript:, https:) are refused, encoded or not.

starts_at and ends_at are Africa/Kigali local time when sent without an offset (as promotions);
stored in UTC and shown in Kigali time. A banner shows while starts_at <= now < ends_at (null is
open-ended).
"""

import re
import uuid
from datetime import datetime
from typing import Annotated, Any
from urllib.parse import unquote

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.core.kigali_time import local_to_utc, to_kigali
from app.models.content import (
    CTA_LABEL_MAX_LENGTH,
    CTA_URL_MAX_LENGTH,
    OVERLINE_MAX_LENGTH,
    SUBTITLE_MAX_LENGTH,
    TITLE_MAX_LENGTH,
)
from app.schemas.images import PublicImage

CTA_PATTERN = re.compile(r"^/(?![/\\])[A-Za-z0-9\-._~/%?=&#]*$")
CTA_RULE = (
    "cta_url must be a path on this site, starting with a single '/' (e.g. /category/phones), "
    "with no scheme, '//', backslash, space or control character."
)
LOCAL_TIME = (
    "Africa/Kigali local time when sent without an offset (e.g. 2026-11-01T00:00:00); "
    "stored in UTC. null: open-ended."
)


def plain_text(value: Any) -> Any:
    """Remove control and other non-printable characters (keeping spaces), trim the ends."""
    if not isinstance(value, str):
        return value
    return "".join(ch for ch in value if ch.isprintable() or ch == " ").strip()


def _cta_path_ok(value: str) -> bool:
    if "//" in value or "\\" in value:
        return False
    if any(not ch.isprintable() or ch.isspace() for ch in value):
        return False
    return CTA_PATTERN.fullmatch(value) is not None


def check_cta_url(value: str) -> str:
    if len(value) > CTA_URL_MAX_LENGTH or not _cta_path_ok(value):
        raise ValueError(CTA_RULE)
    decoded = unquote(value)
    if decoded != value and not _cta_path_ok(decoded):
        raise ValueError(CTA_RULE)
    return value


Title = Annotated[
    str, BeforeValidator(plain_text), Field(min_length=1, max_length=TITLE_MAX_LENGTH)
]
Overline = Annotated[
    str, BeforeValidator(plain_text), Field(min_length=1, max_length=OVERLINE_MAX_LENGTH)
]
Subtitle = Annotated[
    str, BeforeValidator(plain_text), Field(min_length=1, max_length=SUBTITLE_MAX_LENGTH)
]
CtaLabel = Annotated[
    str, BeforeValidator(plain_text), Field(min_length=1, max_length=CTA_LABEL_MAX_LENGTH)
]
CtaUrl = Annotated[str, Field(max_length=CTA_URL_MAX_LENGTH), AfterValidator(check_cta_url)]
Position = Annotated[int, Field(ge=0, le=2**31 - 1)]


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return local_to_utc(value)


def window_problem(starts_at: datetime | None, ends_at: datetime | None) -> str | None:
    if starts_at is not None and ends_at is not None and ends_at <= starts_at:
        return "ends_at must be after starts_at."
    return None


def cta_problem(url: str | None, label_en: str | None, label_rw: str | None) -> str | None:
    if url is not None and (label_en is None or label_rw is None):
        return "A banner with cta_url needs cta_label_en and cta_label_rw."
    return None


class BannerCreateRequest(BaseModel):
    """A new banner is inactive: upload its image, then activate it."""

    model_config = ConfigDict(extra="forbid")

    title_en: Title
    title_rw: Title
    overline_en: Overline | None = None
    overline_rw: Overline | None = None
    subtitle_en: Subtitle | None = None
    subtitle_rw: Subtitle | None = None
    cta_label_en: CtaLabel | None = None
    cta_label_rw: CtaLabel | None = None
    cta_url: CtaUrl | None = None
    position: Position = 0
    starts_at: datetime | None = Field(default=None, description=LOCAL_TIME)
    ends_at: datetime | None = Field(default=None, description=LOCAL_TIME)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def as_utc(cls, value: datetime | None) -> datetime | None:
        return _utc(value)

    @model_validator(mode="after")
    def check_rules(self) -> "BannerCreateRequest":
        problem = window_problem(self.starts_at, self.ends_at) or cta_problem(
            self.cta_url, self.cta_label_en, self.cta_label_rw
        )
        if problem:
            raise ValueError(problem)
        return self


class BannerUpdateRequest(BaseModel):
    """Partial update. Nullable fields accept null to clear them; is_active true needs an image
    (409 banner_needs_image). The result is checked against the stored banner."""

    model_config = ConfigDict(extra="forbid")

    title_en: Title | None = None
    title_rw: Title | None = None
    overline_en: Overline | None = None
    overline_rw: Overline | None = None
    subtitle_en: Subtitle | None = None
    subtitle_rw: Subtitle | None = None
    cta_label_en: CtaLabel | None = None
    cta_label_rw: CtaLabel | None = None
    cta_url: CtaUrl | None = None
    position: Position | None = None
    is_active: bool | None = None
    starts_at: datetime | None = Field(default=None, description=LOCAL_TIME)
    ends_at: datetime | None = Field(default=None, description=LOCAL_TIME)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def as_utc(cls, value: datetime | None) -> datetime | None:
        return _utc(value)

    @model_validator(mode="after")
    def check_fields(self) -> "BannerUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change.")
        required = ("title_en", "title_rw", "position", "is_active")
        nulls = [f for f in required if f in self.model_fields_set and getattr(self, f) is None]
        if nulls:
            raise ValueError(f"These fields cannot be null: {', '.join(nulls)}.")
        return self


class LocalizedText(BaseModel):
    en: str | None
    rw: str | None


class _Times(BaseModel):
    starts_at: datetime | None
    ends_at: datetime | None

    @field_serializer("starts_at", "ends_at")
    def _kigali(self, value: datetime | None) -> datetime | None:
        return to_kigali(value)


class PublicBanner(_Times):
    id: uuid.UUID
    title: LocalizedText
    overline: LocalizedText | None = Field(
        default=None,
        description="Short line above the title (at most 40 characters); null when neither "
        "language has one",
    )
    subtitle: LocalizedText | None = Field(description="null when neither language has one")
    cta_label: LocalizedText | None
    cta_url: str | None = Field(description="An on-site path, e.g. /category/phones")
    image: PublicImage


class StaffBannerResponse(_Times):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title_en: str
    title_rw: str
    overline_en: str | None
    overline_rw: str | None
    subtitle_en: str | None
    subtitle_rw: str | None
    cta_label_en: str | None
    cta_label_rw: str | None
    cta_url: str | None
    position: int
    is_active: bool
    image: PublicImage | None = None
    shown_now: bool = Field(default=False, description="Active and within its window right now")
    created_at: datetime
    updated_at: datetime
