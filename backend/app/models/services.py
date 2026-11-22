"""Technical services (ADR-013, SC-02, approved 2026-11-17).

Services are not products: no price, stock or cart. Each service category has bullet-point items
and a "Request a service" form whose submissions are leads for staff (service_requests). They are
kept apart from the catalogue's categories table.

Text staff write is stored in English (required) and Kinyarwanda (optional; the storefront falls
back to English), as banners do.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.slugs import SLUG_PATTERN
from app.models.common import Entity
from app.models.media import MediaObject

SERVICE_SLUG_MAX_LENGTH = 80
SERVICE_NAME_MAX_LENGTH = 120
SERVICE_SHORT_MAX_LENGTH = 240
SERVICE_INTRO_MAX_LENGTH = 3000
SERVICE_ITEM_MAX_LENGTH = 200
SERVICE_ITEMS_MAX = 30
# The icons staff choose from (lucide icons in the frontend).
SERVICE_ICONS = (
    "cctv",
    "gate",
    "fingerprint",
    "network",
    "wrench",
    "graduation-cap",
    "shield",
    "cpu",
    # ADR-014 phase 6: furniture services (migration f2a4c6e8b0d1).
    "hammer",
    "truck",
    "ruler",
    "sofa",
    "paintbrush",
)

REQUEST_NAME_MAX_LENGTH = 120
REQUEST_EMAIL_MAX_LENGTH = 254
REQUEST_LOCATION_MAX_LENGTH = 120
REQUEST_MESSAGE_MAX_LENGTH = 2000
REQUEST_NOTES_MAX_LENGTH = 4000
CLIENT_TYPES = ("home", "business", "institution")
REQUEST_STATUSES = ("new", "contacted", "scheduled", "completed", "cancelled")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class ServiceCategory(Entity):
    """One technical service (CCTV, gate automation, repair, ...) with its storefront texts and
    one image (public source and private original, in the media registry, as category images)."""

    __tablename__ = "service_categories"
    __table_args__ = (
        CheckConstraint(f"slug ~ '{SLUG_PATTERN}'", name="slug_format"),
        CheckConstraint(_in("icon", SERVICE_ICONS), name="icon_valid"),
        CheckConstraint(
            f"char_length(intro_en) <= {SERVICE_INTRO_MAX_LENGTH} AND "
            f"(intro_rw IS NULL OR char_length(intro_rw) <= {SERVICE_INTRO_MAX_LENGTH})",
            name="intro_length",
        ),
        CheckConstraint(
            "(image_media_id IS NULL) = (image_original_media_id IS NULL)",
            name="image_media_together",
        ),
        Index("ix_service_categories_active_sort", "is_active", "sort_order"),
    )

    slug: Mapped[str] = mapped_column(String(SERVICE_SLUG_MAX_LENGTH), nullable=False, unique=True)
    name_en: Mapped[str] = mapped_column(String(SERVICE_NAME_MAX_LENGTH), nullable=False)
    name_rw: Mapped[str | None] = mapped_column(String(SERVICE_NAME_MAX_LENGTH))
    short_description_en: Mapped[str] = mapped_column(
        String(SERVICE_SHORT_MAX_LENGTH), nullable=False
    )
    short_description_rw: Mapped[str | None] = mapped_column(String(SERVICE_SHORT_MAX_LENGTH))
    intro_en: Mapped[str] = mapped_column(Text, nullable=False)
    intro_rw: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str] = mapped_column(String(32), nullable=False)
    image_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_objects.id", ondelete="RESTRICT"), unique=True
    )
    image_original_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_objects.id", ondelete="RESTRICT"), unique=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")

    image_media: Mapped[MediaObject | None] = relationship(
        foreign_keys=[image_media_id], lazy="selectin"
    )
    items: Mapped[list[ServiceItem]] = relationship(
        back_populates="service",
        order_by="(ServiceItem.sort_order, ServiceItem.created_at)",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )


class ServiceItem(Entity):
    """One bullet point of a service ("DVR and NVR installation and configuration")."""

    __tablename__ = "service_items"
    __table_args__ = (Index("ix_service_items_service_sort", "service_category_id", "sort_order"),)

    service_category_id: Mapped[UUID] = mapped_column(
        ForeignKey("service_categories.id", ondelete="CASCADE"), nullable=False
    )
    title_en: Mapped[str] = mapped_column(String(SERVICE_ITEM_MAX_LENGTH), nullable=False)
    title_rw: Mapped[str | None] = mapped_column(String(SERVICE_ITEM_MAX_LENGTH))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    service: Mapped[ServiceCategory] = relationship(back_populates="items")


class ServiceRequest(Entity):
    """A visitor's request for a service (a lead). Staff follow it up by phone or WhatsApp, move
    it through new, contacted, scheduled, completed or cancelled, assign it and keep notes. A
    service with requests cannot be deleted (RESTRICT); staff hide it instead."""

    __tablename__ = "service_requests"
    __table_args__ = (
        CheckConstraint(_in("status", REQUEST_STATUSES), name="status_valid"),
        CheckConstraint(_in("client_type", CLIENT_TYPES), name="client_type_valid"),
        CheckConstraint(r"phone ~ '^\+2507[0-9]{8}$'", name="phone_canonical"),
        CheckConstraint("locale IN ('en', 'rw')", name="locale_valid"),
        CheckConstraint(
            "(status = 'new') = (status_changed_at IS NULL)", name="changed_when_not_new"
        ),
        CheckConstraint(
            f"internal_notes IS NULL OR char_length(internal_notes) <= {REQUEST_NOTES_MAX_LENGTH}",
            name="notes_length",
        ),
        Index("ix_service_requests_status_created", "status", "created_at"),
        Index("ix_service_requests_service_created", "service_category_id", "created_at"),
        Index("ix_service_requests_assigned", "assigned_to_user_id"),
    )

    reference: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    service_category_id: Mapped[UUID] = mapped_column(
        ForeignKey("service_categories.id", ondelete="RESTRICT"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(REQUEST_NAME_MAX_LENGTH), nullable=False)
    phone: Mapped[str] = mapped_column(String(13), nullable=False)
    email: Mapped[str | None] = mapped_column(String(REQUEST_EMAIL_MAX_LENGTH))
    location: Mapped[str | None] = mapped_column(String(REQUEST_LOCATION_MAX_LENGTH))
    client_type: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str | None] = mapped_column(String(REQUEST_MESSAGE_MAX_LENGTH))
    preferred_date: Mapped[date | None] = mapped_column(Date)
    locale: Mapped[str] = mapped_column(String(2), nullable=False, default="en")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="new", server_default="new"
    )
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_to_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    internal_notes: Mapped[str | None] = mapped_column(Text)

    service: Mapped[ServiceCategory] = relationship(lazy="selectin")
