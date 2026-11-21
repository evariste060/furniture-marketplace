from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.common import Entity

if TYPE_CHECKING:
    from app.models.identity import User


class UserSession(Entity):
    """Opaque bearer session (ADR-006). Only the SHA-256 of the token is stored."""

    __tablename__ = "user_sessions"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class PasswordResetCode(Entity):
    """One-time password-reset code (module 2). Only a keyed HMAC of the code is stored.

    A code is usable while consumed_at is NULL, expires_at is in the future and attempts is below
    the limit. Issuing a new code marks older open codes consumed, so only the newest one works.
    """

    __tablename__ = "password_reset_codes"
    __table_args__ = (
        CheckConstraint("channel IN ('email', 'sms')", name="valid_channel"),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        Index("ix_password_reset_codes_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(8), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailVerificationToken(Entity):
    """One email verification link (ADR-006 amendment 2026-11-12). Only the SHA-256 of the token
    is stored. A token is usable while consumed_at and revoked_at are NULL and expires_at is in
    the future, and only for the address it was issued for. Issuing a new token revokes the
    older open ones; verifying revokes every other open token of the account."""

    __tablename__ = "email_verification_tokens"
    __table_args__ = (
        CheckConstraint(
            "consumed_at IS NULL OR revoked_at IS NULL", name="consumed_or_revoked_not_both"
        ),
        Index("ix_email_verification_tokens_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthLoginFlow(Entity):
    """One external sign-in attempt between its start and Google's answer (ADR-006 amendment
    2026-11-11). Only SHA-256 digests of the `state`, the browser-binding flow token and the
    `nonce` are stored. The PKCE code verifier is kept until the flow is used, then erased.

    A flow is usable once: consuming it sets consumed_at in a single UPDATE that also checks the
    flow token and the expiry, so a replayed or forged callback finds no row. `purpose` 'link'
    flows belong to a signed-in user (user_id) and can only link, never sign in.
    """

    __tablename__ = "oauth_login_flows"
    __table_args__ = (
        CheckConstraint("provider IN ('google')", name="valid_provider"),
        CheckConstraint("purpose IN ('login', 'link')", name="valid_purpose"),
        CheckConstraint("(purpose = 'link') = (user_id IS NOT NULL)", name="link_flow_has_user"),
        Index("ix_oauth_login_flows_expires_at", "expires_at"),
    )

    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    purpose: Mapped[str] = mapped_column(String(8), nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    flow_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    nonce_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_verifier: Mapped[str | None] = mapped_column(String(128))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
