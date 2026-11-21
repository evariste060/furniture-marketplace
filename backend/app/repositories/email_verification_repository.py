import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.session import EmailVerificationToken


class EmailVerificationRepository:
    """Email verification tokens (ADR-006 amendment 2026-11-12). Every method works in the
    caller's transaction (no commit)."""

    @staticmethod
    def create(
        db: Session, user_id: uuid.UUID, email: str, token_hash: str, expires_at: datetime
    ) -> EmailVerificationToken:
        row = EmailVerificationToken(
            user_id=user_id, email=email, token_hash=token_hash, expires_at=expires_at
        )
        db.add(row)
        db.flush()
        return row

    @staticmethod
    def revoke_open(
        db: Session, user_id: uuid.UUID, now: datetime, *, keep: uuid.UUID | None = None
    ) -> int:
        """Mark every unused, unrevoked token of the user revoked (all but `keep`)."""
        query = update(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user_id,
            EmailVerificationToken.consumed_at.is_(None),
            EmailVerificationToken.revoked_at.is_(None),
        )
        if keep is not None:
            query = query.where(EmailVerificationToken.id != keep)
        result = db.execute(
            query.values(revoked_at=now, updated_at=now).execution_options(
                synchronize_session=False
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)

    @staticmethod
    def lock_by_hash(db: Session, token_hash: str) -> EmailVerificationToken | None:
        """The token with this digest, row-locked: a concurrent use of the same token waits here
        until this transaction ends, then sees it consumed."""
        return db.scalar(
            select(EmailVerificationToken)
            .where(EmailVerificationToken.token_hash == token_hash)
            .with_for_update()
        )

    @staticmethod
    def latest_issued_at(db: Session, user_id: uuid.UUID) -> datetime | None:
        """When the user's newest token was issued (the resend cooldown)."""
        return db.scalar(
            select(func.max(EmailVerificationToken.created_at)).where(
                EmailVerificationToken.user_id == user_id
            )
        )
