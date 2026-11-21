import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.session import PasswordResetCode


class PasswordResetRepository:
    @staticmethod
    def supersede_open_codes(db: Session, user_id: uuid.UUID, now: datetime) -> None:
        """Mark every unused code of the user consumed, so only the next code works (no commit)."""
        db.execute(
            update(PasswordResetCode)
            .where(PasswordResetCode.user_id == user_id, PasswordResetCode.consumed_at.is_(None))
            .values(consumed_at=now)
            .execution_options(synchronize_session=False)
        )

    @staticmethod
    def create(
        db: Session, user_id: uuid.UUID, code_hash: str, channel: str, expires_at: datetime
    ) -> PasswordResetCode:
        """Stage a new code in the caller's transaction (no commit)."""
        row = PasswordResetCode(
            user_id=user_id, code_hash=code_hash, channel=channel, expires_at=expires_at
        )
        db.add(row)
        db.flush()
        return row

    @staticmethod
    def latest_open(
        db: Session, user_id: uuid.UUID, *, for_update: bool = False
    ) -> PasswordResetCode | None:
        """The newest unused code of the user, optionally row-locked against concurrent use."""
        query = (
            select(PasswordResetCode)
            .where(PasswordResetCode.user_id == user_id, PasswordResetCode.consumed_at.is_(None))
            .order_by(PasswordResetCode.created_at.desc(), PasswordResetCode.id.desc())
            .limit(1)
        )
        if for_update:
            query = query.with_for_update()
        return db.scalar(query)
