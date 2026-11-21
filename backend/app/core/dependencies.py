from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, Unauthorized
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import effective_roles, has_permission
from app.core.security import hash_session_token
from app.db.session import get_db
from app.models.identity import User
from app.models.session import UserSession
from app.repositories.session_repository import SessionRepository
from app.services.audit_service import AuditService

security_scheme = HTTPBearer(
    scheme_name="BearerAuth",
    description="Paste the session_token returned by /api/v1/auth/login or /register.",
    auto_error=False,
)


def get_current_session(
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> UserSession:
    if not credentials or not credentials.credentials:
        raise Unauthorized(
            "Authentication token is missing.",
            code="token_missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_hash = hash_session_token(credentials.credentials)
    session = SessionRepository.get_active_session_by_token_hash(db, token_hash)

    if not session:
        # Only tokens of real (expired or revoked) sessions are audited, throttled per session;
        # unknown tokens are not, so anonymous callers cannot flood audit_records (QA D-11).
        stale = SessionRepository.get_by_token_hash(db, token_hash)
        if stale is not None:
            AuditService.record_session_invalid(db, stale, ctx)
        raise Unauthorized(
            "Session is invalid, expired, or revoked. Please log in again.",
            code="session_invalid",
            headers={"WWW-Authenticate": "Bearer"},
        )

    SessionRepository.touch(db, session)
    return session


def get_current_user(
    session: Annotated[UserSession, Depends(get_current_session)],
) -> User:
    user = session.user
    if not user or not user.is_active:
        raise Forbidden("User account is inactive or disabled.", code="account_inactive")
    return user


def _deny(db: Session, ctx: RequestContext, request: Request, user: User, details: dict) -> None:
    AuditService.record_standalone(
        db,
        action="auth.access_denied",
        status="denied",
        actor=user,
        entity_type="endpoint",
        entity_id=request.url.path,
        context=ctx,
        details={"user_roles": sorted(effective_roles(user)), **details},
    )


def require_permission(required_permission: str) -> Callable:
    """Dependency factory ensuring current user's role has the specified permission.

    This is the single authorization mechanism for protected staff features; permissions come
    only from the code-defined mapping in app.core.roles, re-read from the database on every
    request, so role and status changes apply immediately.
    """

    def permission_checker(
        request: Request,
        ctx: Annotated[RequestContext, Depends(get_request_context)],
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
    ) -> User:
        if not has_permission(current_user, required_permission):
            _deny(db, ctx, request, current_user, {"required_permission": required_permission})
            raise Forbidden(
                f"Access forbidden: requires '{required_permission}' permission.",
                code="permission_denied",
            )
        return current_user

    # Read by tests that enumerate every permission-protected route.
    permission_checker.required_permission = required_permission  # type: ignore[attr-defined]
    return permission_checker
