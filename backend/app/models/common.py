from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# ADR-007: money is whole RWF in BIGINT columns, capped per stored amount.
MAX_MONEY_RWF = 999_999_999_999


def utc_now() -> datetime:
    return datetime.now(UTC)


class UUIDPrimaryKey:
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Entity(UUIDPrimaryKey, Timestamped, Base):
    __abstract__ = True
