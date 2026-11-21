"""Staff identity, provisioning and administration (ADR-006, approved 2026-10-22).

Rules:
- Only callers with 'staff:manage' (administrators) change staff accounts. Their authority is
  re-checked inside the transaction, after the staff-change lock, so a concurrently demoted or
  disabled administrator cannot complete a change.
- Every change commits atomically with its audit record (app.db.transaction.atomic).
- At least one active administrator must always remain.
- A role change or deactivation revokes all of the user's sessions.
- Customers are never converted to staff here: non-staff IDs are reported as not found.
"""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.core.request_context import RequestContext
from app.core.roles import Permission, Role, has_permission, staff_role
from app.core.security import hash_password
from app.db.transaction import atomic
from app.models.identity import User
from app.repositories.session_repository import SessionRepository
from app.repositories.staff_repository import StaffRepository
from app.repositories.user_repository import UserRepository
from app.schemas.staff import StaffCreateRequest, StaffUpdateRequest
from app.services.audit_service import AuditService
from app.services.auth_service import duplicate_field_from_integrity_error

STAFF_NOT_FOUND = "Staff account not found."
EMAIL_IN_USE = "An account with this email already exists."
PHONE_IN_USE = "An account with this phone number already exists."
LAST_ADMIN = "This change would leave no active administrator."
NOT_AUTHORIZED = f"Access forbidden: requires '{Permission.STAFF_MANAGE.value}' permission."


class StaffBootstrapError(Exception):
    """The first-administrator bootstrap was refused; the message is safe to show."""


def _conflict(field: str) -> AppError:
    return Conflict(
        EMAIL_IN_USE if field == "email" else PHONE_IN_USE,
        code="email_taken" if field == "email" else "phone_taken",
    )


def _duplicate_field(db: Session, email: str | None, phone: str | None) -> str | None:
    if email and UserRepository.get_by_email(db, email):
        return "email"
    if phone and UserRepository.get_by_phone(db, phone):
        return "phone"
    return None


class StaffService:
    # ---- reads ---------------------------------------------------------------------------
    @staticmethod
    def get(db: Session, staff_id: uuid.UUID) -> User:
        user = StaffRepository.get(db, staff_id)
        if user is None:
            raise NotFound(STAFF_NOT_FOUND, code="staff_not_found")
        return user

    @staticmethod
    def list(
        db: Session, role: str | None, is_active: bool | None, limit: int, offset: int
    ) -> tuple[list[User], int]:
        return StaffRepository.list_staff(db, role, is_active, limit, offset)

    # ---- helpers -------------------------------------------------------------------------
    @staticmethod
    def _begin_change(db: Session, actor: User, staff_id: uuid.UUID | None) -> User | None:
        """Inside a transaction: lock, re-verify the actor, and load the target staff user."""
        StaffRepository.lock_staff_changes(db)
        db.refresh(actor)
        db.refresh(actor, ["staff_roles"])
        if not (actor.is_active and has_permission(actor, Permission.STAFF_MANAGE)):
            raise Forbidden(NOT_AUTHORIZED, code="permission_denied")
        if staff_id is None:
            return None
        target = StaffRepository.get(db, staff_id)
        if target is None:
            raise NotFound(STAFF_NOT_FOUND, code="staff_not_found")
        db.refresh(target)
        db.refresh(target, ["staff_roles"])
        return target

    @staticmethod
    def _ensure_other_active_admin(db: Session, target: User) -> None:
        if StaffRepository.count_active_administrators(db, exclude_user_id=target.id) == 0:
            raise Conflict(LAST_ADMIN, code="last_administrator")

    # ---- provisioning --------------------------------------------------------------------
    @staticmethod
    def create(db: Session, actor: User, req: StaffCreateRequest, ctx: RequestContext) -> User:
        # Fast-path checks give a clear 409; the unique indexes remain the source of truth.
        field = _duplicate_field(db, req.email, req.phone)
        if field:
            raise _conflict(field)
        password_hash = hash_password(req.password)
        try:
            with atomic(db):
                StaffService._begin_change(db, actor, None)
                user = StaffRepository.create(
                    db,
                    full_name=req.full_name,
                    password_hash=password_hash,
                    role=req.role,
                    email=req.email,
                    phone=req.phone,
                )
                AuditService.log_event(
                    db=db,
                    action="staff.create",
                    status="success",
                    actor=actor,
                    entity_type="user",
                    entity_id=user.id,
                    context=ctx,
                    details={"role": req.role},
                )
        except IntegrityError as exc:
            # A concurrent request claimed the same identifier between check and insert.
            field = duplicate_field_from_integrity_error(exc)
            if field is None:
                raise
            raise _conflict(field) from None
        return user

    @staticmethod
    def bootstrap_administrator(
        db: Session, req: StaffCreateRequest, os_user: str | None = None
    ) -> User:
        """Create the first administrator. Refused while any active administrator exists.

        Operator-only path (scripts/bootstrap_admin.py); there is no HTTP route for it. The audit
        record says whether this was the first setup or a recovery (administrators exist but are
        all disabled), and which database and OS accounts ran it.
        """
        if req.role != Role.ADMINISTRATOR.value:
            raise StaffBootstrapError("The bootstrap account must have the administrator role.")
        password_hash = hash_password(req.password)
        try:
            with atomic(db):
                StaffRepository.lock_staff_changes(db)
                if StaffRepository.count_active_administrators(db) > 0:
                    raise StaffBootstrapError(
                        "An active administrator already exists; create staff through the API."
                    )
                field = _duplicate_field(db, req.email, req.phone)
                if field:
                    raise StaffBootstrapError(f"An account with this {field} already exists.")
                mode = "recovery" if StaffRepository.count_administrators(db) else "first"
                user = StaffRepository.create(
                    db,
                    full_name=req.full_name,
                    password_hash=password_hash,
                    role=Role.ADMINISTRATOR.value,
                    email=req.email,
                    phone=req.phone,
                )
                AuditService.log_event(
                    db=db,
                    action="staff.bootstrap_administrator",
                    status="success",
                    entity_type="user",
                    entity_id=user.id,
                    details={
                        "role": Role.ADMINISTRATOR.value,
                        "channel": "cli",
                        "mode": mode,
                        "db_role": StaffRepository.current_database_role(db),
                        "os_user": os_user,
                    },
                )
        except IntegrityError as exc:
            field = duplicate_field_from_integrity_error(exc) or "identifier"
            raise StaffBootstrapError(f"An account with this {field} already exists.") from None
        return user

    # ---- administration ------------------------------------------------------------------
    @staticmethod
    def update(
        db: Session,
        actor: User,
        staff_id: uuid.UUID,
        req: StaffUpdateRequest,
        ctx: RequestContext,
    ) -> User:
        try:
            with atomic(db):
                target = StaffService._begin_change(db, actor, staff_id)
                assert target is not None
                if req.phone and req.phone != target.phone:
                    existing = UserRepository.get_by_phone(db, req.phone)
                    if existing and existing.id != target.id:
                        raise _conflict("phone")
                UserRepository.update(db, target, full_name=req.full_name, phone=req.phone)
                AuditService.log_event(
                    db=db,
                    action="staff.update",
                    status="success",
                    actor=actor,
                    entity_type="user",
                    entity_id=target.id,
                    context=ctx,
                    details={"updated_fields": sorted(req.model_dump(exclude_none=True))},
                )
        except IntegrityError:
            raise _conflict("phone") from None
        return target

    @staticmethod
    def change_role(
        db: Session, actor: User, staff_id: uuid.UUID, role: str, ctx: RequestContext
    ) -> User:
        with atomic(db):
            target = StaffService._begin_change(db, actor, staff_id)
            assert target is not None
            old_role = staff_role(target)
            if old_role == role:
                return target  # no change: nothing to audit, sessions kept
            if old_role == Role.ADMINISTRATOR.value and target.is_active:
                StaffService._ensure_other_active_admin(db, target)
            StaffRepository.set_role(db, target, role)
            revoked = SessionRepository.revoke_all_user_sessions(db, target.id)
            AuditService.log_event(
                db=db,
                action="staff.role_change",
                status="success",
                actor=actor,
                entity_type="user",
                entity_id=target.id,
                context=ctx,
                details={"old_role": old_role, "new_role": role, "sessions_revoked": revoked},
            )
        return target

    @staticmethod
    def change_status(
        db: Session, actor: User, staff_id: uuid.UUID, is_active: bool, ctx: RequestContext
    ) -> User:
        with atomic(db):
            target = StaffService._begin_change(db, actor, staff_id)
            assert target is not None
            if target.is_active == is_active:
                return target  # no change
            revoked = 0
            if not is_active:
                if staff_role(target) == Role.ADMINISTRATOR.value:
                    StaffService._ensure_other_active_admin(db, target)
                revoked = SessionRepository.revoke_all_user_sessions(db, target.id)
            StaffRepository.set_active(db, target, is_active)
            AuditService.log_event(
                db=db,
                action="staff.status_change",
                status="success",
                actor=actor,
                entity_type="user",
                entity_id=target.id,
                context=ctx,
                details={
                    "old_is_active": not is_active,
                    "new_is_active": is_active,
                    "sessions_revoked": revoked,
                },
            )
        return target
