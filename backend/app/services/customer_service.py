from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict
from app.core.request_context import RequestContext
from app.db.transaction import atomic
from app.models.identity import User
from app.repositories.user_repository import UserRepository
from app.schemas.customer import CustomerUpdateRequest
from app.services.audit_service import AuditService

PHONE_IN_USE = "This phone number is already associated with another account."


class CustomerService:
    @staticmethod
    def get_profile(user: User) -> User:
        return user

    @staticmethod
    def update_profile(
        db: Session, user: User, req: CustomerUpdateRequest, ctx: RequestContext
    ) -> User:
        if req.phone and req.phone != user.phone:
            existing = UserRepository.get_by_phone(db, req.phone)
            if existing and existing.id != user.id:
                raise Conflict(PHONE_IN_USE, code="phone_taken")

        try:
            with atomic(db):
                UserRepository.update(
                    db=db,
                    user=user,
                    full_name=req.full_name,
                    phone=req.phone,
                )
                AuditService.log_event(
                    db=db,
                    action="user.profile.update",
                    status="success",
                    actor=user,
                    entity_type="user",
                    entity_id=user.id,
                    context=ctx,
                    details={"updated_fields": sorted(req.model_dump(exclude_none=True).keys())},
                )
        except IntegrityError:
            # Concurrent update claimed the same phone number first.
            raise Conflict(PHONE_IN_USE, code="phone_taken") from None
        return user
