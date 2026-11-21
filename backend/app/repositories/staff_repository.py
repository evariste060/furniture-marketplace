import uuid

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from app.core.roles import Role
from app.models.identity import StaffRoleAssignment, User

# Arbitrary fixed key for pg_advisory_xact_lock: serialises every staff role/status/creation
# change so the "at least one active administrator" check cannot race.
STAFF_CHANGE_LOCK_KEY = 7_302_116_001


class StaffRepository:
    @staticmethod
    def lock_staff_changes(db: Session) -> None:
        """Take the transaction-scoped staff-change lock (released at commit/rollback)."""
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": STAFF_CHANGE_LOCK_KEY})

    @staticmethod
    def get(db: Session, staff_id: uuid.UUID) -> User | None:
        """A staff account by ID; customers (is_staff=false) are never returned."""
        return db.scalar(
            select(User)
            .where(User.id == staff_id, User.is_staff.is_(True))
            .options(selectinload(User.staff_roles))
        )

    @staticmethod
    def list_staff(
        db: Session,
        role: str | None,
        is_active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[User], int]:
        filters = [User.is_staff.is_(True)]
        if is_active is not None:
            filters.append(User.is_active.is_(is_active))
        if role is not None:
            filters.append(
                User.id.in_(
                    select(StaffRoleAssignment.user_id).where(StaffRoleAssignment.role == role)
                )
            )
        total = db.scalar(select(func.count(User.id)).where(*filters)) or 0
        items = db.scalars(
            select(User)
            .where(*filters)
            .options(selectinload(User.staff_roles))
            .order_by(User.created_at, User.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return list(items), total

    @staticmethod
    def count_active_administrators(db: Session, exclude_user_id: uuid.UUID | None = None) -> int:
        stmt = (
            select(func.count(User.id))
            .join(StaffRoleAssignment, StaffRoleAssignment.user_id == User.id)
            .where(
                User.is_staff.is_(True),
                User.is_active.is_(True),
                StaffRoleAssignment.role == Role.ADMINISTRATOR.value,
            )
        )
        if exclude_user_id is not None:
            stmt = stmt.where(User.id != exclude_user_id)
        return db.scalar(stmt) or 0

    @staticmethod
    def count_administrators(db: Session) -> int:
        """All administrator accounts, active or disabled."""
        stmt = (
            select(func.count(User.id))
            .join(StaffRoleAssignment, StaffRoleAssignment.user_id == User.id)
            .where(User.is_staff.is_(True), StaffRoleAssignment.role == Role.ADMINISTRATOR.value)
        )
        return db.scalar(stmt) or 0

    @staticmethod
    def current_database_role(db: Session) -> str | None:
        return db.scalar(text("SELECT current_user"))

    @staticmethod
    def create(
        db: Session,
        full_name: str,
        password_hash: str,
        role: str,
        email: str | None,
        phone: str | None,
    ) -> User:
        """Stage a new active staff user and its single role (no commit)."""
        user = User(
            full_name=full_name.strip(),
            password_hash=password_hash,
            email=email,
            phone=phone,
            is_active=True,
            is_staff=True,
        )
        db.add(user)
        db.flush()
        db.add(StaffRoleAssignment(user_id=user.id, role=role))
        db.flush()
        db.refresh(user, ["staff_roles"])
        return user

    @staticmethod
    def set_role(db: Session, user: User, role: str) -> None:
        """Stage the user's single role (no commit)."""
        if user.staff_roles:
            user.staff_roles[0].role = role
        else:
            user.staff_roles.append(StaffRoleAssignment(user_id=user.id, role=role))
        db.flush()

    @staticmethod
    def set_active(db: Session, user: User, is_active: bool) -> None:
        user.is_active = is_active
        db.flush()
