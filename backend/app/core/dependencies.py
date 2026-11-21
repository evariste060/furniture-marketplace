from collections.abc import Callable
from dataclasses import dataclass
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
from app.models.marketplace import Store
from app.models.session import UserSession
from app.repositories.session_repository import SessionRepository
from app.repositories.store_repository import StoreRepository
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


@dataclass(frozen=True)
class SellerContext:
    """The signed-in seller and their own approved store (ADR-014)."""

    user: User
    store: Store


SELLER_NOT_APPROVED = "Seller access requires an approved store."


def require_approved_seller(
    request: Request,
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SellerContext:
    """The single authorization mechanism for seller features (ADR-014 decision 4).

    The caller's store is read from the database on every request, never from the request or the
    session, so a suspension applies to the very next call made with an existing session. No
    store, or a store that is pending, rejected or suspended, is 403 seller_not_approved
    (audited as auth.access_denied). Staff never own stores. Seller routes take no store id: what
    a seller may touch is always their own store.
    """
    store = None if current_user.is_staff else StoreRepository.get_by_owner(db, current_user.id)
    if store is None or store.status != "approved":
        _deny(
            db,
            ctx,
            request,
            current_user,
            {"required": "approved_seller", "store_status": store.status if store else None},
        )
        raise Forbidden(SELLER_NOT_APPROVED, code="seller_not_approved")
    return SellerContext(user=current_user, store=store)


# Read by tests that enumerate every seller-scoped route.
require_approved_seller.seller_scoped = True  # type: ignore[attr-defined]
