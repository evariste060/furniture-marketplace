"""Customer support messages (approved 2026-11-11): questions sent from the Contact page, by
guests or signed-in customers, and the conversation with staff that follows.

A thread is one question and its replies. Its status is 'open' while it waits for staff,
'answered' after a staff reply, and 'closed' when staff close it; a customer reply reopens it.
Messages are plain text and never edited or deleted.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.common import Entity

SUPPORT_STATUSES = ("open", "answered", "closed")
# What the question is about, chosen in the Contact page wizard's first step.
SUPPORT_TOPICS = ("order", "product", "payment", "warranty", "returns", "other")
SUPPORT_NAME_MAX_LENGTH = 120
SUPPORT_EMAIL_MAX_LENGTH = 254
SUPPORT_SUBJECT_MAX_LENGTH = 120
SUPPORT_ORDER_NUMBER_MAX_LENGTH = 32
SUPPORT_BODY_MAX_LENGTH = 2000


class SupportThread(Entity):
    __tablename__ = "support_threads"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'answered', 'closed')", name="status_valid"),
        CheckConstraint(r"phone IS NULL OR phone ~ '^\+2507[0-9]{8}$'", name="phone_canonical"),
        CheckConstraint("phone IS NOT NULL OR email IS NOT NULL", name="has_contact"),
        CheckConstraint("locale IN ('en', 'rw')", name="locale_valid"),
        CheckConstraint(
            "topic IN ('order', 'product', 'payment', 'warranty', 'returns', 'other')",
            name="topic_valid",
        ),
        Index("ix_support_threads_status_last", "status", "last_message_at"),
        Index("ix_support_threads_last", "last_message_at"),
        Index("ix_support_threads_customer_last", "customer_user_id", "last_message_at"),
    )

    reference: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    # The signed-in customer who started it; null for guests (they follow it by private link).
    customer_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(SUPPORT_NAME_MAX_LENGTH), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(13))
    email: Mapped[str | None] = mapped_column(String(SUPPORT_EMAIL_MAX_LENGTH))
    topic: Mapped[str] = mapped_column(String(16), nullable=False)
    subject: Mapped[str] = mapped_column(String(SUPPORT_SUBJECT_MAX_LENGTH), nullable=False)
    order_number: Mapped[str | None] = mapped_column(String(SUPPORT_ORDER_NUMBER_MAX_LENGTH))
    locale: Mapped[str] = mapped_column(String(2), nullable=False, default="en")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open"
    )
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    messages: Mapped[list[SupportMessage]] = relationship(
        back_populates="thread",
        order_by="(SupportMessage.created_at, SupportMessage.id)",
        cascade="all, delete-orphan",
    )


class SupportMessage(Entity):
    __tablename__ = "support_messages"
    __table_args__ = (
        CheckConstraint("author IN ('customer', 'staff')", name="author_valid"),
        CheckConstraint("char_length(body) BETWEEN 1 AND 2000", name="body_length"),
        Index("ix_support_messages_thread_created", "thread_id", "created_at"),
    )

    thread_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_threads.id", ondelete="CASCADE"), nullable=False
    )
    author: Mapped[str] = mapped_column(String(16), nullable=False)
    # The staff member who wrote a staff message (kept null if their account is deleted).
    staff_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(String(SUPPORT_BODY_MAX_LENGTH), nullable=False)

    thread: Mapped[SupportThread] = relationship(back_populates="messages")
