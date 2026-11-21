import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import exists, func, select, text
from sqlalchemy.orm import Session

from app.models.operations import AuditRecord

# pg_advisory_xact_lock(namespace, hashtext(entity_type:entity_id)); 7302 is the order lock.
AUDIT_ENTITY_LOCK_NAMESPACE = 7303


class AuditRepository:
    @staticmethod
    def lock_entity_events(db: Session, entity_type: str, entity_id: str) -> None:
        """Serialise audit writes for one entity until the transaction ends."""
        db.execute(
            text("SELECT pg_advisory_xact_lock(CAST(:ns AS integer), hashtext(:key))"),
            {"ns": AUDIT_ENTITY_LOCK_NAMESPACE, "key": f"{entity_type}:{entity_id}"},
        )

    @staticmethod
    def has_recent(
        db: Session, action: str, entity_type: str, entity_id: str, window_seconds: int
    ) -> bool:
        """Whether this action was recorded for the entity within the window (database time)."""
        return bool(
            db.scalar(
                select(
                    exists().where(
                        AuditRecord.entity_type == entity_type,
                        AuditRecord.entity_id == entity_id,
                        AuditRecord.action == action,
                        AuditRecord.created_at > func.now() - timedelta(seconds=window_seconds),
                    )
                )
            )
        )

    @staticmethod
    def create(
        db: Session,
        action: str,
        entity_type: str,
        entity_id: str,
        change_summary: dict[str, Any],
        actor_user_id: uuid.UUID | None = None,
        actor_identifier_snapshot: str | None = None,
        request_id: str | None = None,
    ) -> AuditRecord:
        """Stage an audit row in the caller's transaction (no commit)."""
        record = AuditRecord(
            actor_user_id=actor_user_id,
            actor_identifier_snapshot=actor_identifier_snapshot,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            request_id=request_id,
            change_summary=change_summary,
        )
        db.add(record)
        db.flush()
        return record

    @staticmethod
    def list_records(
        db: Session,
        action: str | None = None,
        status: str | None = None,
        actor_user_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditRecord], int]:
        filters = []
        if action:
            filters.append(AuditRecord.action == action)
        if status:
            filters.append(AuditRecord.change_summary["status"].astext == status)
        if actor_user_id:
            filters.append(AuditRecord.actor_user_id == actor_user_id)
        if entity_type:
            filters.append(AuditRecord.entity_type == entity_type)
        if created_from is not None:
            filters.append(AuditRecord.created_at >= created_from)
        if created_to is not None:
            filters.append(AuditRecord.created_at <= created_to)
        total = db.scalar(select(func.count(AuditRecord.id)).where(*filters)) or 0
        query = (
            select(AuditRecord)
            .where(*filters)
            .order_by(AuditRecord.created_at.desc(), AuditRecord.id)
            .limit(min(limit, 100))
            .offset(offset)
        )
        return list(db.scalars(query).all()), total
