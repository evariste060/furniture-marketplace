"""Saved delivery addresses.

Approved default-address rule (2026-10-21): a customer who has addresses always has exactly one
default.
- The first address always becomes the default.
- Creating or updating with is_default=true, or POST .../default, moves the default.
- is_default=false on the current default is rejected (422); set another address instead.
- Deleting the default promotes the most recently created remaining address.
PostgreSQL enforces "at most one" with a partial unique index; every write takes a row lock on
the customer, so concurrent requests are serialised and "exactly one" holds.
"""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound, ValidationFailed
from app.core.request_context import RequestContext
from app.db.transaction import atomic
from app.models.identity import Address, User
from app.repositories.address_repository import AddressRepository
from app.repositories.user_repository import UserRepository
from app.schemas.address import AddressCreateRequest, AddressUpdateRequest
from app.services.audit_service import AuditService

ADDRESS_NOT_FOUND = "Delivery address not found."
CANNOT_UNSET_DEFAULT = (
    "A default delivery address is required. Set another address as default instead."
)
CONCURRENT_CHANGE = "The address list changed concurrently. Please retry."


def _not_found() -> AppError:
    return NotFound(ADDRESS_NOT_FOUND, code="address_not_found")


def _conflict() -> AppError:
    return Conflict(CONCURRENT_CHANGE, code="concurrent_change")


class AddressService:
    @staticmethod
    def _owned(db: Session, address_id: uuid.UUID, user: User) -> Address:
        address = AddressRepository.get_by_id_and_user(db, address_id, user.id)
        if not address:
            raise _not_found()
        return address

    @staticmethod
    def create_address(
        db: Session, user: User, req: AddressCreateRequest, ctx: RequestContext
    ) -> Address:
        try:
            with atomic(db):
                UserRepository.lock_by_id(db, user.id)
                make_default = req.is_default or AddressRepository.count_by_user(db, user.id) == 0
                if make_default:
                    AddressRepository.unset_all_defaults(db, user.id)
                address = AddressRepository.create(
                    db=db,
                    user_id=user.id,
                    fields=req.model_dump(exclude={"is_default"}),
                    is_default=make_default,
                )
                AuditService.log_event(
                    db=db,
                    action="address.create",
                    status="success",
                    actor=user,
                    entity_type="address",
                    entity_id=address.id,
                    context=ctx,
                    details={"is_default": address.is_default},
                )
        except IntegrityError:
            raise _conflict() from None
        return address

    @staticmethod
    def list_addresses(db: Session, user: User) -> list[Address]:
        return AddressRepository.list_by_user(db, user.id)

    @staticmethod
    def get_address(db: Session, address_id: uuid.UUID, user: User) -> Address:
        return AddressService._owned(db, address_id, user)

    @staticmethod
    def update_address(
        db: Session,
        address_id: uuid.UUID,
        user: User,
        req: AddressUpdateRequest,
        ctx: RequestContext,
    ) -> Address:
        try:
            with atomic(db):
                UserRepository.lock_by_id(db, user.id)
                address = AddressService._owned(db, address_id, user)
                db.refresh(address)  # re-read under the lock
                if req.is_default is False and address.is_default:
                    raise ValidationFailed(CANNOT_UNSET_DEFAULT, code="cannot_unset_default")
                # null means "no change"; an empty string clears an optional field.
                changes = req.model_dump(exclude_unset=True, exclude_none=True)
                changes.pop("is_default", None)
                AddressRepository.update_fields(db=db, address=address, changes=changes)
                if req.is_default is True and not address.is_default:
                    AddressRepository.mark_default(db, address)
                AuditService.log_event(
                    db=db,
                    action="address.update",
                    status="success",
                    actor=user,
                    entity_type="address",
                    entity_id=address.id,
                    context=ctx,
                    details={
                        "updated_fields": sorted(req.model_dump(exclude_unset=True).keys()),
                    },
                )
        except IntegrityError:
            raise _conflict() from None
        return address

    @staticmethod
    def delete_address(db: Session, address_id: uuid.UUID, user: User, ctx: RequestContext) -> None:
        try:
            with atomic(db):
                UserRepository.lock_by_id(db, user.id)
                address = AddressService._owned(db, address_id, user)
                db.refresh(address)
                was_default = address.is_default
                AddressRepository.delete(db, address)  # flushed before promotion
                promoted = None
                if was_default:
                    promoted = AddressRepository.newest_other(db, user.id, address_id)
                    if promoted:
                        AddressRepository.mark_default(db, promoted)
                AuditService.log_event(
                    db=db,
                    action="address.delete",
                    status="success",
                    actor=user,
                    entity_type="address",
                    entity_id=address_id,
                    context=ctx,
                    details={"promoted_default": str(promoted.id) if promoted else None},
                )
        except IntegrityError:
            raise _conflict() from None

    @staticmethod
    def set_default_address(
        db: Session, address_id: uuid.UUID, user: User, ctx: RequestContext
    ) -> Address:
        try:
            with atomic(db):
                UserRepository.lock_by_id(db, user.id)
                address = AddressService._owned(db, address_id, user)
                AddressRepository.mark_default(db, address)
                AuditService.log_event(
                    db=db,
                    action="address.set_default",
                    status="success",
                    actor=user,
                    entity_type="address",
                    entity_id=address.id,
                    context=ctx,
                )
        except IntegrityError:
            raise _conflict() from None
        return address
