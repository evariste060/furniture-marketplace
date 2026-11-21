"""Security audit events written to the shared audit_records table (commerce schema, PR #2).

Column mapping (ADR-006):
- actor_user_id / actor_identifier_snapshot: the authenticated actor (email, else phone)
- action: e.g. "auth.login", "address.update"
- entity_type / entity_id: affected record; failed logins use ("login_identifier", HMAC ref)
- change_summary (JSONB): {"status", "ip_address", "user_agent", **bounded details}
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import field_error
from app.core.request_context import RequestContext, sanitize_ip_address, sanitize_user_agent
from app.core.security import pseudonymize_identifier
from app.models.identity import User
from app.models.operations import AuditRecord
from app.models.session import UserSession
from app.repositories.audit_repository import AuditRepository

# Sensitive keys that must NEVER be written to audit logs
FORBIDDEN_AUDIT_KEYS = {
    "password",
    "password_hash",
    "token",
    "session_token",
    "secret",
    "authorization",
    "cookie",
    "credit_card",
    "card_number",
    "cvv",
    "otp",
}
# Raw personal identifiers must be pseudonymised by the caller (see identifier_ref).
PERSONAL_IDENTIFIER_KEYS = {"identifier", "email", "phone", "phone_number"}
# Keys the service itself sets; callers cannot override them through details.
RESERVED_KEYS = {"status", "ip_address", "user_agent"}

MAX_DETAIL_KEYS = 20
MAX_DETAIL_DEPTH = 3
MAX_DETAIL_STRING = 256
MAX_DETAIL_LIST = 20
ENTITY_FIELD_MAX = 80  # audit_records.entity_type / entity_id / action
ACTOR_SNAPSHOT_MAX = 180

SESSION_INVALID_ACTION = "auth.session_invalid"
SESSION_INVALID_AUDIT_WINDOW_SECONDS = 900  # one record per stale session per 15 minutes


def _bound_value(val: Any, depth: int) -> Any:
    if isinstance(val, dict):
        return _sanitize(val, depth + 1) if depth < MAX_DETAIL_DEPTH else "[TRUNCATED]"
    if isinstance(val, (list, tuple)):
        return [_bound_value(v, depth + 1) for v in list(val)[:MAX_DETAIL_LIST]]
    if isinstance(val, str):
        return val[:MAX_DETAIL_STRING]
    if isinstance(val, (int, float, bool)) or val is None:
        return val
    return str(val)[:MAX_DETAIL_STRING]


def _sanitize(details: dict[str, Any], depth: int) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, val in list(details.items())[:MAX_DETAIL_KEYS]:
        key = str(key)[:64]
        if key.lower() in FORBIDDEN_AUDIT_KEYS:
            sanitized[key] = "[REDACTED]"
        elif key.lower() in PERSONAL_IDENTIFIER_KEYS:
            sanitized[key] = "[PSEUDONYMISE]"
        else:
            sanitized[key] = _bound_value(val, depth)
    return sanitized


def sanitize_audit_details(details: dict[str, Any] | None) -> dict[str, Any] | None:
    """Redact secrets/raw identifiers and bound the size and depth of audit metadata."""
    if not details:
        return None
    return _sanitize(details, 1)


def identifier_ref(normalized_identifier: str) -> str:
    """Keyed pseudonym for a normalised email/phone, safe to store in audit records."""
    key = get_settings().audit_hmac_key.get_secret_value()
    return pseudonymize_identifier(normalized_identifier, key)


def actor_snapshot(user: User | None) -> str | None:
    if user is None:
        return None
    value = user.email or user.phone
    return value[:ACTOR_SNAPSHOT_MAX] if value else None


class AuditService:
    @staticmethod
    def log_event(
        db: Session,
        action: str,
        status: str,
        entity_type: str,
        entity_id: str | uuid.UUID,
        actor: User | None = None,
        context: RequestContext | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> AuditRecord:
        """Stage an audit record inside the caller's transaction.

        Commit it together with the business change (app.db.transaction.atomic), so that if the
        audit insert fails the change rolls back too.
        """
        summary: dict[str, Any] = {
            k: v
            for k, v in (sanitize_audit_details(details) or {}).items()
            if k not in RESERVED_KEYS
        }
        summary["status"] = status[:32]
        if context is not None:
            summary["ip_address"] = sanitize_ip_address(context.ip_address)
            summary["user_agent"] = sanitize_user_agent(context.user_agent)
        return AuditRepository.create(
            db=db,
            action=action[:ENTITY_FIELD_MAX],
            entity_type=entity_type[:ENTITY_FIELD_MAX],
            entity_id=str(entity_id)[:ENTITY_FIELD_MAX],
            change_summary=summary,
            actor_user_id=actor.id if actor is not None else None,
            actor_identifier_snapshot=actor_snapshot(actor),
            request_id=request_id[:160] if request_id else None,
        )

    @staticmethod
    def record_standalone(db: Session, **kwargs: Any) -> AuditRecord:
        """Persist a security event that has no accompanying change (e.g. failed login).

        Must only be called when the session has no other pending changes.
        """
        try:
            record = AuditService.log_event(db, **kwargs)
            db.commit()
            return record
        except BaseException:
            db.rollback()
            raise

    @staticmethod
    def record_session_invalid(
        db: Session, session: UserSession, context: RequestContext
    ) -> AuditRecord | None:
        """Audit use of an expired or revoked session, at most once per session per window.

        Unknown tokens are never audited (QA D-11): rows are bounded by the number of real
        sessions. The per-session advisory lock makes the once-per-window rule hold under
        concurrent requests. Returns None when the event was already recorded in the window.
        """
        entity_id = str(session.id)
        try:
            AuditRepository.lock_entity_events(db, "session", entity_id)
            if AuditRepository.has_recent(
                db,
                action=SESSION_INVALID_ACTION,
                entity_type="session",
                entity_id=entity_id,
                window_seconds=SESSION_INVALID_AUDIT_WINDOW_SECONDS,
            ):
                db.rollback()  # releases the advisory lock
                return None
            revoked = session.revoked_at is not None or not session.is_active
            record = AuditService.log_event(
                db,
                action=SESSION_INVALID_ACTION,
                status="failure",
                entity_type="session",
                entity_id=entity_id,
                context=context,
                details={"reason": "session_revoked" if revoked else "session_expired"},
            )
            db.commit()
            return record
        except BaseException:
            db.rollback()
            raise

    @staticmethod
    def list_events(
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
        """Newest first. The date range is inclusive at both ends; `from` must not be after `to`."""
        if created_from is not None and created_to is not None and created_from > created_to:
            raise field_error(("query", "from"), "from must be earlier than or equal to to")
        return AuditRepository.list_records(
            db=db,
            action=action,
            status=status,
            actor_user_id=actor_user_id,
            entity_type=entity_type,
            created_from=created_from,
            created_to=created_to,
            limit=limit,
            offset=offset,
        )
