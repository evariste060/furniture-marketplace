import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.identity import User


class UserRepository:
    @staticmethod
    def get_by_id(db: Session, user_id: uuid.UUID) -> User | None:
        return db.scalar(select(User).where(User.id == user_id))

    @staticmethod
    def lock_by_id(db: Session, user_id: uuid.UUID) -> None:
        """Take a row lock on the user (PostgreSQL SELECT ... FOR UPDATE).

        Serialises concurrent writes to that user's dependent rows (e.g. default address).
        """
        db.execute(select(User.id).where(User.id == user_id).with_for_update())

    @staticmethod
    def get_by_email(db: Session, email: str) -> User | None:
        """Case-insensitive match; uses the upstream unique index on lower(email)."""
        return db.scalar(select(User).where(func.lower(User.email) == email.lower()))

    @staticmethod
    def get_by_phone(db: Session, phone: str) -> User | None:
        """Expects a canonical +2507XXXXXXXX number from app.core.identifiers."""
        return db.scalar(select(User).where(User.phone == phone))

    @staticmethod
    def get_by_identifier(db: Session, normalized_identifier: str) -> User | None:
        """Look up by a normalised login identifier (email or canonical phone)."""
        if "@" in normalized_identifier:
            return UserRepository.get_by_email(db, normalized_identifier)
        return UserRepository.get_by_phone(db, normalized_identifier)

    @staticmethod
    def create_customer(
        db: Session,
        full_name: str,
        password_hash: str | None,
        email: str | None = None,
        phone: str | None = None,
        email_verified_at: datetime | None = None,
    ) -> User:
        """Stage a new customer (never staff) in the caller's transaction (no commit).

        `password_hash` is None for a customer created by Continue with Google: password login
        then fails like a wrong password until they set one with a reset code."""
        user = User(
            full_name=full_name.strip(),
            password_hash=password_hash,
            email=email,
            phone=phone,
            is_active=True,
            is_staff=False,
            email_verified_at=email_verified_at,
        )
        db.add(user)
        db.flush()
        return user

    @staticmethod
    def update(
        db: Session,
        user: User,
        full_name: str | None = None,
        phone: str | None = None,
    ) -> User:
        """Stage profile changes in the caller's transaction (no commit)."""
        if full_name is not None:
            user.full_name = full_name.strip()
        if phone is not None:
            user.phone = phone
        db.flush()
        return user
