from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.commerce import Order
from app.models.identity import StaffRoleAssignment, User


class OrderRepository:
    @staticmethod
    def get(db: Session, order_id: UUID, *, for_update: bool = False) -> Order | None:
        statement = select(Order).where(Order.id == order_id)
        if for_update:
            statement = statement.with_for_update()
        return db.scalar(statement)

    @staticmethod
    def get_owned(db: Session, order_id: UUID, user_id: UUID) -> Order | None:
        return db.scalar(select(Order).where(Order.id == order_id, Order.user_id == user_id))

    @staticmethod
    def get_owned_by_number(db: Session, order_number: str, user_id: UUID) -> Order | None:
        return db.scalar(
            select(Order).where(Order.order_number == order_number, Order.user_id == user_id)
        )

    @staticmethod
    def get_active_staff_for_update(db: Session, user_id: UUID) -> User | None:
        return db.scalar(
            select(User)
            .join(StaffRoleAssignment, StaffRoleAssignment.user_id == User.id)
            .where(User.id == user_id, User.is_staff.is_(True), User.is_active.is_(True))
            .with_for_update()
        )
