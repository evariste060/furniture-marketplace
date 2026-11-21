from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.common import Entity

if TYPE_CHECKING:
    from app.models.commerce import Cart, Order


class User(Entity):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("email IS NOT NULL OR phone IS NOT NULL", name="login_identifier_required"),
        Index(
            "uq_users_email_lower",
            text("lower(email)"),
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
        UniqueConstraint("phone", name="user_phone"),
        # Auth (ADR-006): phones are stored only in canonical +2507XXXXXXXX form.
        CheckConstraint(
            r"phone IS NULL OR phone ~ '^\+2507[0-9]{8}$'", name="phone_canonical"
        ).ddl_if(dialect="postgresql"),
    )

    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(32))
    # Auth (ADR-006): display name collected at registration; nullable for pre-existing rows.
    full_name: Mapped[str | None] = mapped_column(String(255))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    is_staff: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    # Email verification (ADR-006 amendment 2026-11-12): when the address was proven. NULL with an
    # email means a customer who registered with a password and has not verified yet: they get
    # no session until they do. Accounts that existed before the feature, and customers created
    # by Continue with Google (verified email claim), have it set.
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    addresses: Mapped[list[Address]] = relationship(
        back_populates="user", cascade="save-update, merge"
    )
    carts: Mapped[list[Cart]] = relationship(back_populates="user")
    orders: Mapped[list[Order]] = relationship(back_populates="user", foreign_keys="Order.user_id")
    staff_roles: Mapped[list[StaffRoleAssignment]] = relationship(back_populates="user")


class OAuthIdentity(Entity):
    """A sign-in identity at an external provider linked to a user (ADR-006 amendment
    2026-11-11). Matched by the provider's stable subject (`sub`), never by email: one provider
    account belongs to at most one user, and a user has at most one account per provider."""

    __tablename__ = "oauth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_oauth_identities_provider_subject"),
        UniqueConstraint("user_id", "provider", name="uq_oauth_identities_user_id_provider"),
        CheckConstraint("provider IN ('google')", name="valid_provider"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    # The provider's verified email when the identity was linked or last used (informational;
    # sign-in matches the subject only).
    email: Mapped[str | None] = mapped_column(String(320))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class StaffRoleAssignment(Entity):
    __tablename__ = "staff_role_assignments"
    __table_args__ = (
        # One role per staff user (ADR-006, approved 2026-10-22).
        UniqueConstraint("user_id"),
        # The Marketplace Administrator is the only staff role (SC-05, 2026-11-21).
        CheckConstraint("role IN ('administrator')", name="valid_role"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)

    user: Mapped[User] = relationship(back_populates="staff_roles")


class Address(Entity):
    __tablename__ = "addresses"
    __table_args__ = (
        Index("ix_addresses_user", "user_id"),
        Index(
            "uq_addresses_one_default",
            "user_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
        CheckConstraint(r"phone ~ '^\+2507[0-9]{8}$'", name="phone_canonical").ddl_if(
            dialect="postgresql"
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(80))
    recipient_name: Mapped[str] = mapped_column(String(180), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    country_code: Mapped[str] = mapped_column(
        String(2), nullable=False, default="RW", server_default="RW"
    )
    province: Mapped[str | None] = mapped_column(String(120))
    district: Mapped[str | None] = mapped_column(String(120))
    sector: Mapped[str | None] = mapped_column(String(120))
    cell: Mapped[str | None] = mapped_column(String(120))
    village: Mapped[str | None] = mapped_column(String(120))
    street_address: Mapped[str | None] = mapped_column(String(240))
    delivery_instructions: Mapped[str | None] = mapped_column(String(500))
    is_default: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")

    user: Mapped[User] = relationship(back_populates="addresses")
