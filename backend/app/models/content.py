"""Storefront content: homepage banners (approved 2026-10-26, checkpoint 1b topic 9); policy pages
and business quote requests (module 19, approved 2026-10-29)."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.common import Entity

if TYPE_CHECKING:
    from app.models.media import MediaObject

TITLE_MAX_LENGTH = 80
OVERLINE_MAX_LENGTH = 40  # small line above the title (2026-10-27)
SUBTITLE_MAX_LENGTH = 160
CTA_LABEL_MAX_LENGTH = 30
CTA_URL_MAX_LENGTH = 200

# Policy pages (module 19). The storefront links exactly these slugs (footer and help menu).
PAGE_SLUGS = (
    "about-us",
    "delivery-information",
    "returns-and-refunds",
    "warranty",
    "privacy-policy",
    "terms-and-conditions",
)
PAGE_LOCALES = ("en", "rw")
PAGE_SLUG_MAX_LENGTH = 60
PAGE_TITLE_MAX_LENGTH = 120
PAGE_BODY_MAX_LENGTH = 50_000

# Business quote requests (module 19; Contact page, PR-01).
QUOTE_REFERENCE_PREFIX = "Q"
QUOTE_STATUSES = ("new", "contacted", "closed")
QUOTE_COMPANY_MAX_LENGTH = 150
QUOTE_CONTACT_MAX_LENGTH = 120
QUOTE_EMAIL_MAX_LENGTH = 254
QUOTE_LOCATION_MAX_LENGTH = 120
QUOTE_MESSAGE_MAX_LENGTH = 2000
QUOTE_LINES_MAX = 20
QUOTE_PRODUCT_MAX_LENGTH = 200
QUOTE_QUANTITY_MAX = 100_000


class Banner(Entity):
    """A homepage hero banner. English and Kinyarwanda text in _en/_rw columns (the backend has
    no other translated-field pattern). Shown while active and within its window."""

    __tablename__ = "banners"
    __table_args__ = (
        CheckConstraint("position >= 0", name="position_nonnegative"),
        CheckConstraint(
            "starts_at IS NULL OR ends_at IS NULL OR ends_at > starts_at", name="window_valid"
        ),
        CheckConstraint(
            "cta_url IS NULL OR (cta_label_en IS NOT NULL AND cta_label_rw IS NOT NULL)",
            name="cta_label_with_url",
        ),
        CheckConstraint(
            "(image_media_id IS NULL) = (image_original_media_id IS NULL)",
            name="image_media_together",
        ),
        CheckConstraint("NOT is_active OR image_media_id IS NOT NULL", name="active_has_image"),
        Index("ix_banners_active_position", "is_active", "position"),
    )

    title_en: Mapped[str] = mapped_column(String(TITLE_MAX_LENGTH), nullable=False)
    title_rw: Mapped[str] = mapped_column(String(TITLE_MAX_LENGTH), nullable=False)
    overline_en: Mapped[str | None] = mapped_column(String(OVERLINE_MAX_LENGTH))
    overline_rw: Mapped[str | None] = mapped_column(String(OVERLINE_MAX_LENGTH))
    subtitle_en: Mapped[str | None] = mapped_column(String(SUBTITLE_MAX_LENGTH))
    subtitle_rw: Mapped[str | None] = mapped_column(String(SUBTITLE_MAX_LENGTH))
    cta_label_en: Mapped[str | None] = mapped_column(String(CTA_LABEL_MAX_LENGTH))
    cta_label_rw: Mapped[str | None] = mapped_column(String(CTA_LABEL_MAX_LENGTH))
    cta_url: Mapped[str | None] = mapped_column(String(CTA_URL_MAX_LENGTH))
    image_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_objects.id", ondelete="RESTRICT"), unique=True
    )
    image_original_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_objects.id", ondelete="RESTRICT"), unique=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    image_media: Mapped[MediaObject | None] = relationship(
        foreign_keys=[image_media_id], lazy="selectin"
    )


class Page(Entity):
    """One language version of a policy page (About us, Delivery, Returns, Warranty, Privacy,
    Terms). Body is Markdown, rendered by the storefront without raw HTML. Only published rows
    are public; a missing or unpublished translation is not found (no other language is served
    in its place by the API)."""

    __tablename__ = "pages"
    __table_args__ = (
        UniqueConstraint("slug", "locale", name="slug_locale"),
        CheckConstraint("locale IN ('en', 'rw')", name="locale_valid"),
        CheckConstraint(r"slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="slug_format"),
        CheckConstraint("char_length(title) > 0", name="title_present"),
        CheckConstraint(f"char_length(body) <= {PAGE_BODY_MAX_LENGTH}", name="body_length"),
    )

    slug: Mapped[str] = mapped_column(String(PAGE_SLUG_MAX_LENGTH), nullable=False)
    locale: Mapped[str] = mapped_column(String(2), nullable=False)
    title: Mapped[str] = mapped_column(String(PAGE_TITLE_MAX_LENGTH), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_published: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false"
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class QuoteRequest(Entity):
    """A business buyer's quote request from the Contact page. Staff follow it up by phone,
    WhatsApp or email and track it as new, contacted or closed. No prices are stored: the reply
    happens outside the store."""

    __tablename__ = "quote_requests"
    __table_args__ = (
        CheckConstraint("status IN ('new', 'contacted', 'closed')", name="status_valid"),
        CheckConstraint(r"phone ~ '^\+2507[0-9]{8}$'", name="phone_canonical"),
        CheckConstraint("locale IN ('en', 'rw')", name="locale_valid"),
        CheckConstraint(
            "jsonb_typeof(lines) = 'array' AND jsonb_array_length(lines) BETWEEN 1 AND "
            f"{QUOTE_LINES_MAX}",
            name="lines_shape",
        ),
        CheckConstraint("(status = 'new') = (handled_at IS NULL)", name="handled_when_not_new"),
        Index("ix_quote_requests_status_created", "status", "created_at"),
        Index("ix_quote_requests_created", "created_at"),
    )

    reference: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    company: Mapped[str] = mapped_column(String(QUOTE_COMPANY_MAX_LENGTH), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(QUOTE_CONTACT_MAX_LENGTH), nullable=False)
    phone: Mapped[str] = mapped_column(String(13), nullable=False)
    email: Mapped[str | None] = mapped_column(String(QUOTE_EMAIL_MAX_LENGTH))
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    delivery_location: Mapped[str | None] = mapped_column(String(QUOTE_LOCATION_MAX_LENGTH))
    needed_by: Mapped[date | None] = mapped_column(Date)
    message: Mapped[str | None] = mapped_column(String(QUOTE_MESSAGE_MAX_LENGTH))
    locale: Mapped[str] = mapped_column(String(2), nullable=False, default="en")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="new", server_default="new"
    )
    handled_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
