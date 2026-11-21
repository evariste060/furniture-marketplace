import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import FORBIDDEN_403, UNAUTHORIZED_401, VALIDATION_422
from app.core.dependencies import require_permission
from app.core.roles import Permission
from app.db.session import get_db
from app.models.identity import User
from app.schemas.audit import AuditRecordResponse
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page, page_offset
from app.services.audit_service import AuditService

router = APIRouter(prefix="/audit-logs", tags=["Security Audit Logs"])


@router.get(
    "",
    response_model=Page[AuditRecordResponse],
    status_code=status.HTTP_200_OK,
    summary="List security audit logs",
    description=(
        "Lists append-only audit records, newest first. Restricted to the 'audit:read' "
        "permission (administrator staff role). Failed-login records use "
        "entity_type='login_identifier' with a keyed HMAC pseudonym as entity_id, never the "
        "raw email/phone.\n\n"
        "**Date range:** `from` and `to` are inclusive ISO 8601 timestamps that must include a "
        "timezone offset, e.g. `2026-10-23T00:00:00+02:00` for midnight in Kigali. `from` "
        "later than `to` returns 422."
    ),
    responses={**UNAUTHORIZED_401, **FORBIDDEN_403, **VALIDATION_422},
)
def list_audit_logs(
    current_user: Annotated[User, Depends(require_permission(Permission.AUDIT_READ))],
    db: Annotated[Session, Depends(get_db)],
    action: Annotated[
        str | None, Query(max_length=80, description="Filter by action, e.g. auth.login")
    ] = None,
    status_filter: Annotated[
        str | None,
        Query(alias="status", max_length=32, description="Filter by change_summary.status"),
    ] = None,
    actor_user_id: Annotated[uuid.UUID | None, Query(description="Filter by actor UUID")] = None,
    entity_type: Annotated[
        str | None, Query(max_length=80, description="Filter by entity type, e.g. address")
    ] = None,
    created_from: Annotated[
        AwareDatetime | None,
        Query(alias="from", description="Only records created at or after this time"),
    ] = None,
    created_to: Annotated[
        AwareDatetime | None,
        Query(alias="to", description="Only records created at or before this time"),
    ] = None,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
) -> Page[AuditRecordResponse]:
    records, total = AuditService.list_events(
        db=db,
        action=action,
        status=status_filter,
        actor_user_id=actor_user_id,
        entity_type=entity_type,
        created_from=created_from,
        created_to=created_to,
        limit=size,
        offset=page_offset(page, size),
    )
    return Page[AuditRecordResponse](
        items=[AuditRecordResponse.model_validate(r) for r in records],
        total=total,
        page=page,
        size=size,
    )
