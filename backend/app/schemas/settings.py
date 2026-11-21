"""Settings schemas (module 12; plan §5). Module 12 exposes delivery.free_delivery_threshold;
module 16 adds the seller details printed on invoices (seller.legal_name, seller.tin,
seller.address); module 19 adds the public store contact (store.name, contact.*) and the
announcement bar (announcement.*); the store's social media links (social.*, owner 2026-11-18)
are public too. Unknown keys are refused (422)."""

import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from app.core.identifiers import EMAIL_MAX_LENGTH, validate_email_format
from app.models.common import MAX_MONEY_RWF

FREE_DELIVERY_THRESHOLD = "delivery.free_delivery_threshold"
SELLER_LEGAL_NAME = "seller.legal_name"
SELLER_TIN = "seller.tin"
SELLER_ADDRESS = "seller.address"
SELLER_KEYS = (SELLER_LEGAL_NAME, SELLER_TIN, SELLER_ADDRESS)
# Module 19: public keys, served by GET /settings.
STORE_NAME = "store.name"
CONTACT_PHONE = "contact.phone"
CONTACT_WHATSAPP = "contact.whatsapp"
CONTACT_EMAIL = "contact.email"
CONTACT_ADDRESS = "contact.address"
CONTACT_HOURS = "contact.hours"
ANNOUNCEMENT_ENABLED = "announcement.enabled"
ANNOUNCEMENT_TEXT_EN = "announcement.text_en"
ANNOUNCEMENT_TEXT_RW = "announcement.text_rw"
# The store's social media profiles (owner, 2026-11-18), shown as icons in the store footer. Each
# is an https link on its network's own site (the hosts below, or their subdomains, e.g.
# www.facebook.com). An empty string takes a link off the store again.
SOCIAL_NETWORKS: dict[str, tuple[str, ...]] = {
    "facebook": ("facebook.com", "fb.com"),
    "instagram": ("instagram.com",),
    "x": ("x.com", "twitter.com"),
    "youtube": ("youtube.com", "youtu.be"),
    "tiktok": ("tiktok.com",),
    "linkedin": ("linkedin.com",),
}
SOCIAL_KEYS = {name: f"social.{name}" for name in SOCIAL_NETWORKS}
SOCIAL_URL_MAX = 300

# Seller details (module 16). Only shape is checked: no TIN format is assumed (Finance, PR-14).
LEGAL_NAME_MAX = 200
TIN_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9 -]{0,39}$"
ADDRESS_MAX = 500
# Store contact (module 19). Numbers in international form with single spaces allowed, e.g.
# "+250 788 123 456": 8 to 15 digits after the plus (E.164).
STORE_NAME_MAX = 80
INTERNATIONAL_PHONE_PATTERN = r"^\+[1-9]( ?[0-9]){7,14}$"
CONTACT_ADDRESS_MAX = 200
CONTACT_HOURS_MAX = 100
ANNOUNCEMENT_MAX = 120


def has_control_characters(value: str, *, allow_newlines: bool = False) -> bool:
    allowed = {"\n"} if allow_newlines else set()
    return any(ch not in allowed and (ord(ch) < 32 or ord(ch) == 127) for ch in value)


def social_url_problem(value: str, hosts: tuple[str, ...]) -> str | None:
    """Why a social link is refused, or None when it is fine ("" is fine: no link)."""
    if value == "":
        return None
    if len(value) > SOCIAL_URL_MAX:
        return f"Use at most {SOCIAL_URL_MAX} characters."
    if any(ch.isspace() for ch in value) or has_control_characters(value):
        return "A link has no spaces."
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return "Use a full https:// link."
    if parts.scheme != "https" or not parts.hostname:
        return "Use a full https:// link."
    if parts.username or parts.password or port is not None:
        return "Use the profile's plain link."
    host = parts.hostname.lower()
    if not any(host == h or host.endswith(f".{h}") for h in hosts):
        return f"Use a link on {hosts[0]}."
    return None


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        json_schema_extra={"examples": [{FREE_DELIVERY_THRESHOLD: 200000}]},
    )

    free_delivery_threshold: int | None = Field(
        default=None,
        alias="delivery.free_delivery_threshold",
        strict=True,
        ge=0,
        le=MAX_MONEY_RWF,
        description="Whole RWF. Delivery is free when the merchandise subtotal after discount "
        "is at least this amount (RE-026 B1).",
    )
    seller_legal_name: str | None = Field(
        default=None,
        alias="seller.legal_name",
        strict=True,
        min_length=2,
        max_length=LEGAL_NAME_MAX,
        description="The seller's legal name, printed on invoices (module 16). Required before "
        "any invoice can be issued.",
    )
    seller_tin: str | None = Field(
        default=None,
        alias="seller.tin",
        strict=True,
        pattern=TIN_PATTERN,
        description="The seller's taxpayer identification number (TIN), printed on invoices. "
        "Letters, digits, spaces and hyphens, at most 40; no format is assumed.",
    )
    seller_address: str | None = Field(
        default=None,
        alias="seller.address",
        strict=True,
        min_length=3,
        max_length=ADDRESS_MAX,
        description="The seller's address, printed on invoices; line breaks are kept.",
    )

    store_name: str | None = Field(
        default=None,
        alias="store.name",
        strict=True,
        min_length=2,
        max_length=STORE_NAME_MAX,
        description="The store's name as customers see it (public).",
    )
    contact_phone: str | None = Field(
        default=None,
        alias="contact.phone",
        strict=True,
        pattern=INTERNATIONAL_PHONE_PATTERN,
        description="The store's phone number (public), international form, e.g. "
        "'+250 788 123 456'; shown as written.",
    )
    contact_whatsapp: str | None = Field(
        default=None,
        alias="contact.whatsapp",
        strict=True,
        pattern=INTERNATIONAL_PHONE_PATTERN,
        description="The number every WhatsApp button on the store opens (public), "
        "international form.",
    )
    contact_email: str | None = Field(
        default=None,
        alias="contact.email",
        strict=True,
        max_length=EMAIL_MAX_LENGTH,
        description="The store's email address (public); stored in lower case.",
    )
    contact_address: str | None = Field(
        default=None,
        alias="contact.address",
        strict=True,
        min_length=3,
        max_length=CONTACT_ADDRESS_MAX,
        description="The store's street address (public), one line.",
    )
    contact_hours: str | None = Field(
        default=None,
        alias="contact.hours",
        strict=True,
        min_length=3,
        max_length=CONTACT_HOURS_MAX,
        description="Opening hours as customers read them (public), one line.",
    )
    announcement_enabled: bool | None = Field(
        default=None,
        alias="announcement.enabled",
        strict=True,
        description="Show the announcement bar message instead of the free-delivery line. "
        "Needs both messages.",
    )
    announcement_text_en: str | None = Field(
        default=None,
        alias="announcement.text_en",
        strict=True,
        min_length=3,
        max_length=ANNOUNCEMENT_MAX,
        description="Announcement bar message in English (public while enabled).",
    )
    announcement_text_rw: str | None = Field(
        default=None,
        alias="announcement.text_rw",
        strict=True,
        min_length=3,
        max_length=ANNOUNCEMENT_MAX,
        description="Announcement bar message in Kinyarwanda (public while enabled).",
    )
    social_facebook: str | None = Field(
        default=None,
        alias="social.facebook",
        strict=True,
        max_length=SOCIAL_URL_MAX,
        description="The store's Facebook page link (public): a full https:// link on "
        "facebook.com. An empty string removes it from the store.",
    )
    social_instagram: str | None = Field(
        default=None,
        alias="social.instagram",
        strict=True,
        max_length=SOCIAL_URL_MAX,
        description="The store's Instagram profile link (public): a full https:// link on "
        "instagram.com. An empty string removes it from the store.",
    )
    social_x: str | None = Field(
        default=None,
        alias="social.x",
        strict=True,
        max_length=SOCIAL_URL_MAX,
        description="The store's X (Twitter) profile link (public): a full https:// link on "
        "x.com or twitter.com. An empty string removes it from the store.",
    )
    social_youtube: str | None = Field(
        default=None,
        alias="social.youtube",
        strict=True,
        max_length=SOCIAL_URL_MAX,
        description="The store's YouTube channel link (public): a full https:// link on "
        "youtube.com. An empty string removes it from the store.",
    )
    social_tiktok: str | None = Field(
        default=None,
        alias="social.tiktok",
        strict=True,
        max_length=SOCIAL_URL_MAX,
        description="The store's TikTok profile link (public): a full https:// link on "
        "tiktok.com. An empty string removes it from the store.",
    )
    social_linkedin: str | None = Field(
        default=None,
        alias="social.linkedin",
        strict=True,
        max_length=SOCIAL_URL_MAX,
        description="The store's LinkedIn page link (public): a full https:// link on "
        "linkedin.com. An empty string removes it from the store.",
    )

    @field_validator("contact_email")
    @classmethod
    def check_email(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value != value.strip():
            raise ValueError("Remove leading and trailing spaces.")
        return validate_email_format(value)

    @field_validator(
        "seller_legal_name",
        "seller_tin",
        "seller_address",
        "store_name",
        "contact_address",
        "contact_hours",
        "announcement_text_en",
        "announcement_text_rw",
    )
    @classmethod
    def check_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return value
        if value != value.strip():
            raise ValueError("Remove leading and trailing spaces.")
        if has_control_characters(value, allow_newlines=info.field_name == "seller_address"):
            raise ValueError("Control characters are not allowed.")
        return value

    @field_validator(*(f"social_{name}" for name in SOCIAL_NETWORKS))
    @classmethod
    def check_social(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return value
        name = (info.field_name or "").removeprefix("social_")
        problem = social_url_problem(value, SOCIAL_NETWORKS[name])
        if problem:
            raise ValueError(problem)
        return value

    @model_validator(mode="after")
    def check_fields(self) -> "SettingsUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("Provide at least one setting to change.")
        if any(getattr(self, f) is None for f in self.model_fields_set):
            raise ValueError("A setting cannot be set to null.")
        return self

    def changes(self) -> dict[str, Any]:
        """{setting key: new value} for the settings sent."""
        return {
            self.__class__.model_fields[f].alias or f: getattr(self, f)
            for f in self.model_fields_set
        }


class SettingResponse(BaseModel):
    key: str
    value: Any = Field(description="Null while the setting has never been set")
    updated_at: datetime | None
    updated_by_user_id: uuid.UUID | None = Field(description="Staff account that last set it")


class SettingsResponse(BaseModel):
    items: list[SettingResponse] = Field(description="Every setting this API manages, by key")


class LocalizedAnnouncement(BaseModel):
    en: str
    rw: str


class SocialLinks(BaseModel):
    """The store's social media links (owner, 2026-11-18); null while not set."""

    facebook: str | None
    instagram: str | None
    x: str | None
    youtube: str | None
    tiktok: str | None
    linkedin: str | None


class PublicSettingsResponse(BaseModel):
    """The store's public settings (module 19). A value never set is null; the storefront then
    leaves that line out."""

    store_name: str | None
    phone: str | None = Field(description="International form as written, e.g. +250 788 123 456")
    whatsapp: str | None = Field(description="International form; wa.me takes its digits")
    email: str | None
    address: str | None
    hours: str | None
    announcement: LocalizedAnnouncement | None = Field(
        description="The announcement bar message while it is switched on; null otherwise"
    )
    social: SocialLinks = Field(description="The store's social media links, each null while unset")
