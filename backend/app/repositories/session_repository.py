import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.session import UserSession


class SessionRepository:
    @staticmethod
    def create(
        db: Session,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> UserSession:
        """Stage a new session in the caller's transaction (no commit)."""
        now = datetime.now(UTC)
        session = UserSession(
            user_id=user_id,
            token_hash=token_hash,
            ip_address=ip_address,
            user_agent=user_agent,
            is_active=True,
            created_at=now,
            last_active_at=now,
            expires_at=expires_at,
        )
        db.add(session)
        db.flush()
        return session

    @staticmethod
    def get_active_session_by_token_hash(db: Session, token_hash: str) -> UserSession | None:
        now = datetime.now(UTC)
        return db.scalar(
            select(UserSession).where(
                UserSession.token_hash == token_hash,
                UserSession.is_active.is_(True),
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
        )

    @staticmethod
    def get_by_token_hash(db: Session, token_hash: str) -> UserSession | None:
        """Any session with this token hash, whatever its state (to tell unknown from stale)."""
        return db.scalar(select(UserSession).where(UserSession.token_hash == token_hash))

    @staticmethod
    def touch(db: Session, session: UserSession) -> None:
        """Record activity. Committed on its own: it is bookkeeping, not a protected change."""
        session.last_active_at = datetime.now(UTC)
        db.commit()

    @staticmethod
    def revoke(db: Session, session: UserSession) -> None:
        """Stage revocation in the caller's transaction (no commit)."""
        session.is_active = False
        session.revoked_at = datetime.now(UTC)
        db.flush()

    @staticmethod
    def revoke_all_user_sessions(
        db: Session, user_id: uuid.UUID, *, keep: uuid.UUID | None = None
    ) -> int:
        """Stage revocation of every active session for a user, except `keep` (no commit)."""
        conditions = [UserSession.user_id == user_id, UserSession.is_active.is_(True)]
        if keep is not None:
            conditions.append(UserSession.id != keep)
        revoked_ids = db.scalars(
            update(UserSession)
            .where(*conditions)
            .values(is_active=False, revoked_at=datetime.now(UTC))
            .returning(UserSession.id)
        )
        return len(revoked_ids.all())
