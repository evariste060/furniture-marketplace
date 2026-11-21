"""Staff identity and staff account administration (ADR-006, approved 2026-10-22).

Authorization uses require_permission with the code-defined matrix in app.core.roles:
- staff:self_read (every staff role): /staff/me, /staff/me/permissions
- staff:read (administrator): list and view staff accounts
- staff:manage (administrator): create staff, edit details, change role or status

The first administrator is created with scripts/bootstrap_admin.py, never over HTTP.

Staff-account IDs use the {staff_id:uuid} path converter, so other /staff/<name> routes
(categories, brands, orders, ...) are never captured here; a non-UUID ID is 404, not 422.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import (
    ERR,
    FORBIDDEN_403,
    UNAUTHORIZED_401,
    VALIDATION_422,
    ResponseMap,
)
from app.core.dependencies import require_permission
from app.core.errors import Forbidden
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Permission, effective_permissions, staff_role
from app.db.session import get_db
from app.models.identity import User
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page, page_offset
from app.schemas.staff import (
    StaffCreateRequest,
    StaffMeResponse,
    StaffPermissionsResponse,
    StaffResponse,
    StaffRoleName,
    StaffRoleUpdateRequest,
    StaffStatusUpdateRequest,
    StaffUpdateRequest,
)
from app.services.staff_service import StaffService

router = APIRouter(prefix="/staff", tags=["Staff Accounts & Authorization"])

GUARDED: ResponseMap = {**UNAUTHORIZED_401, **FORBIDDEN_403}
STAFF_404: ResponseMap = {
    404: {**ERR, "description": "No staff account with this ID (customers included)"}
}
IDENTIFIER_409: ResponseMap = {
    409: {**ERR, "description": "Email or phone already used by another account"}
}
LAST_ADMIN_409: ResponseMap = {
    409: {**ERR, "description": "Change would leave no active administrator"}
}

SelfReader = Annotated[User, Depends(require_permission(Permission.STAFF_SELF_READ))]
StaffReader = Annotated[User, Depends(require_permission(Permission.STAFF_READ))]
StaffManager = Annotated[User, Depends(require_permission(Permission.STAFF_MANAGE))]
Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]


# ---- own identity (declared before /{staff_id}) ---------------------------------------------
@router.get(
    "/me",
    response_model=StaffMeResponse,
    summary="Current staff identity",
    description=(
        "Returns the authenticated staff member's account, role and effective permissions. "
        "Requires 'staff:self_read' (every staff role). Customers receive 403."
    ),
    responses=GUARDED,
)
def get_me(current_user: SelfReader) -> StaffMeResponse:
    return StaffMeResponse.from_user(current_user)


@router.get(
    "/me/permissions",
    response_model=StaffPermissionsResponse,
    summary="Current staff permissions",
    description=(
        "Returns the caller's role and effective permissions, computed from the server-side "
        "role mapping (never from client input). Requires 'staff:self_read'."
    ),
    responses=GUARDED,
)
def get_my_permissions(current_user: SelfReader) -> StaffPermissionsResponse:
    role = staff_role(current_user)
    if role is None:
        # A user without an effective staff role cannot satisfy STAFF_SELF_READ.
        raise Forbidden(
            "Access forbidden: no effective staff role is assigned.", code="no_staff_role"
        )
    return StaffPermissionsResponse(role=role, permissions=effective_permissions(current_user))


# ---- administration -----------------------------------------------------------------------
@router.get(
    "",
    response_model=Page[StaffResponse],
    summary="List staff accounts",
    description=(
        "Lists staff accounts, oldest first, with optional role and status filters. "
        "Requires 'staff:read' (administrator)."
    ),
    responses={**GUARDED, **VALIDATION_422},
)
def list_staff(
    current_user: StaffReader,
    db: Db,
    role: Annotated[StaffRoleName | None, Query(description="Filter by role")] = None,
    is_active: Annotated[bool | None, Query(description="Filter by account status")] = None,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
) -> Page[StaffResponse]:
    items, total = StaffService.list(db, role, is_active, size, page_offset(page, size))
    return Page[StaffResponse](
        items=[StaffResponse.from_user(u) for u in items], total=total, page=page, size=size
    )


@router.post(
    "",
    response_model=StaffResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a staff account",
    description=(
        "Creates an active staff account with exactly one role and an initial password. "
        "Requires 'staff:manage' (administrator). The password is never returned or logged. "
        "Recorded in the audit trail as 'staff.create'."
    ),
    responses={**GUARDED, **IDENTIFIER_409, **VALIDATION_422},
)
def create_staff(
    req: StaffCreateRequest, current_user: StaffManager, db: Db, ctx: Ctx
) -> StaffResponse:
    return StaffResponse.from_user(StaffService.create(db, current_user, req, ctx))


@router.get(
    "/{staff_id:uuid}",
    response_model=StaffResponse,
    summary="Get a staff account",
    description="Returns one staff account. Requires 'staff:read' (administrator).",
    responses={**GUARDED, **STAFF_404, **VALIDATION_422},
)
def get_staff(staff_id: uuid.UUID, current_user: StaffReader, db: Db) -> StaffResponse:
    return StaffResponse.from_user(StaffService.get(db, staff_id))


@router.patch(
    "/{staff_id:uuid}",
    response_model=StaffResponse,
    summary="Update staff details",
    description=(
        "Updates full_name and/or phone. Role, status, email, password and any other field are "
        "rejected with 422. Requires 'staff:manage' (administrator). Audited as 'staff.update'."
    ),
    responses={**GUARDED, **STAFF_404, **IDENTIFIER_409, **VALIDATION_422},
)
def update_staff(
    staff_id: uuid.UUID, req: StaffUpdateRequest, current_user: StaffManager, db: Db, ctx: Ctx
) -> StaffResponse:
    return StaffResponse.from_user(StaffService.update(db, current_user, staff_id, req, ctx))


@router.patch(
    "/{staff_id:uuid}/role",
    response_model=StaffResponse,
    summary="Change a staff member's role",
    description=(
        "Replaces the staff member's single role. Requires 'staff:manage' (administrator). "
        "A change revokes all of the member's sessions and is audited as 'staff.role_change' "
        "with the old and new role. Setting the current role is a no-op. Demoting the last "
        "active administrator returns 409."
    ),
    responses={**GUARDED, **STAFF_404, **LAST_ADMIN_409, **VALIDATION_422},
)
def change_staff_role(
    staff_id: uuid.UUID,
    req: StaffRoleUpdateRequest,
    current_user: StaffManager,
    db: Db,
    ctx: Ctx,
) -> StaffResponse:
    return StaffResponse.from_user(
        StaffService.change_role(db, current_user, staff_id, req.role, ctx)
    )


@router.patch(
    "/{staff_id:uuid}/status",
    response_model=StaffResponse,
    summary="Enable or disable a staff account",
    description=(
        "Sets is_active. Disabling revokes all of the member's sessions and blocks login. "
        "Requires 'staff:manage' (administrator). Audited as 'staff.status_change'. Setting the "
        "current status is a no-op. Disabling the last active administrator returns 409."
    ),
    responses={**GUARDED, **STAFF_404, **LAST_ADMIN_409, **VALIDATION_422},
)
def change_staff_status(
    staff_id: uuid.UUID,
    req: StaffStatusUpdateRequest,
    current_user: StaffManager,
    db: Db,
    ctx: Ctx,
) -> StaffResponse:
    return StaffResponse.from_user(
        StaffService.change_status(db, current_user, staff_id, req.is_active, ctx)
    )
