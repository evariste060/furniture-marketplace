import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.identity import Address

# All methods stage changes in the caller's transaction; AddressService commits.

ADDRESS_FIELDS = (
    "label",
    "recipient_name",
    "phone",
    "province",
    "district",
    "sector",
    "cell",
    "village",
    "street_address",
    "delivery_instructions",
)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


class AddressRepository:
    @staticmethod
    def get_by_id_and_user(
        db: Session, address_id: uuid.UUID, user_id: uuid.UUID
    ) -> Address | None:
        return db.scalar(
            select(Address).where(
                Address.id == address_id,
                Address.user_id == user_id,
            )
        )

    @staticmethod
    def list_by_user(db: Session, user_id: uuid.UUID) -> list[Address]:
        return list(
            db.scalars(
                select(Address)
                .where(Address.user_id == user_id)
                .order_by(Address.is_default.desc(), Address.created_at.desc())
            ).all()
        )

    @staticmethod
    def newest_other(db: Session, user_id: uuid.UUID, exclude_id: uuid.UUID) -> Address | None:
        return db.scalar(
            select(Address)
            .where(Address.user_id == user_id, Address.id != exclude_id)
            .order_by(Address.created_at.desc(), Address.id.desc())
            .limit(1)
        )

    @staticmethod
    def count_by_user(db: Session, user_id: uuid.UUID) -> int:
        return db.scalar(select(func.count(Address.id)).where(Address.user_id == user_id)) or 0

    @staticmethod
    def unset_all_defaults(db: Session, user_id: uuid.UUID) -> None:
        # Runs as SQL immediately, so the partial unique index sees the old default cleared
        # before a new default is written.
        db.execute(
            update(Address)
            .where(Address.user_id == user_id, Address.is_default.is_(True))
            .values(is_default=False)
            .execution_options(synchronize_session="fetch")
        )

    @staticmethod
    def create(
        db: Session, user_id: uuid.UUID, fields: dict[str, str | None], is_default: bool
    ) -> Address:
        """fields: validated address columns (see ADDRESS_FIELDS); blanks stored as NULL."""
        address = Address(
            user_id=user_id,
            country_code="RW",  # single-country MVP (international shipping is out of scope)
            is_default=is_default,
            **{k: _clean(v) for k, v in fields.items() if k in ADDRESS_FIELDS},
        )
        db.add(address)
        db.flush()
        return address

    @staticmethod
    def update_fields(db: Session, address: Address, changes: dict[str, str | None]) -> Address:
        """Apply only the provided columns; an empty string clears an optional column."""
        for key, value in changes.items():
            if key in ADDRESS_FIELDS:
                setattr(address, key, _clean(value))
        db.flush()
        return address

    @staticmethod
    def mark_default(db: Session, address: Address) -> Address:
        AddressRepository.unset_all_defaults(db, address.user_id)
        address.is_default = True
        db.flush()
        return address

    @staticmethod
    def delete(db: Session, address: Address) -> None:
        db.delete(address)
        db.flush()
