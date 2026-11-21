"""Staff promotions (module 13; RE-026 B3, B6; TC-06). Rules are in
app.services.promotion_service. Customers apply codes through POST /cart/apply-code.

GET routes need 'promotions:read' (administrator); POST and PATCH need
'promotions:manage' (administrator only).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import ERR, FORBIDDEN_403, UNAUTHORIZED_401, VALIDATION_422, ResponseMap
from app.core.dependencies import require_permission
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Permission
from app.db.session import get_db
from app.models.identity import User
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page
from app.schemas.promotions import (
    PromotionCreateRequest,
    PromotionResponse,
    PromotionStatus,
    PromotionUpdateRequest,
)
from app.services.promotion_service import PromotionService

router = APIRouter(prefix="/staff/promotions", tags=["Staff Promotions"])

Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]
Reader = Annotated[User, Depends(require_permission(Permission.PROMOTIONS_READ))]
Manager = Annotated[User, Depends(require_permission(Permission.PROMOTIONS_MANAGE))]

GUARDED: ResponseMap = {**UNAUTHORIZED_401, **FORBIDDEN_403}
NOT_FOUND: ResponseMap = {404: {**ERR, "description": "promotion_not_found"}}
SAVE_409: ResponseMap = {
    409: {
        **ERR,
        "description": "promotion_code_taken: another promotion has this code (ignoring case); "
        "invalid_status_transition: an activated or disabled promotion cannot return to draft",
    }
}
TIME_NOTE = (
    "Start and end date-times without an offset are Africa/Kigali local time; responses show "
    "them in Kigali time (+02:00). A code works from starts_at (inclusive) until ends_at "
    "(exclusive)."
)


@router.get(
    "",
    response_model=Page[PromotionResponse],
    summary="List promotions",
    description="Requires 'promotions:read' (administrator). Newest first.",
    responses={**GUARDED, **VALIDATION_422},
)
def list_promotions(
    _: Reader,
    db: Db,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
    status_filter: Annotated[
        PromotionStatus | None, Query(alias="status", description="draft, active or disabled")
    ] = None,
) -> Page[PromotionResponse]:
    return PromotionService.list_page(db, status=status_filter, page=page, size=size)


@router.get(
    "/{promotion_id}",
    response_model=PromotionResponse,
    summary="View a promotion",
    description="Requires 'promotions:read' (administrator).",
    responses={**GUARDED, **NOT_FOUND, **VALIDATION_422},
)
def get_promotion(promotion_id: uuid.UUID, _: Reader, db: Db) -> PromotionResponse:
    return PromotionService.get(db, promotion_id)


@router.post(
    "",
    response_model=PromotionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a promotion",
    description=(
        "Requires 'promotions:manage' (administrator). A 'percent' promotion takes percent_off "
        "(1-100), a 'fixed' one amount_off (whole RWF). applies_to 'targets' needs targets "
        f"(categories, which include their subcategories, brands or products). {TIME_NOTE} "
        "Audited as 'promotion.create'."
    ),
    responses={**GUARDED, **SAVE_409, **VALIDATION_422},
)
def create_promotion(
    req: PromotionCreateRequest, current_user: Manager, db: Db, ctx: Ctx
) -> PromotionResponse:
    return PromotionService.create(db, current_user, req, ctx)


@router.patch(
    "/{promotion_id}",
    response_model=PromotionResponse,
    summary="Update, activate or disable a promotion",
    description=(
        "Requires 'promotions:manage' (administrator). Partial update; `targets` replaces "
        f"every target. {TIME_NOTE} Audited as 'promotion.update' with the old and new "
        "values; a request that changes nothing is not audited."
    ),
    responses={**GUARDED, **NOT_FOUND, **SAVE_409, **VALIDATION_422},
)
def update_promotion(
    promotion_id: uuid.UUID,
    req: PromotionUpdateRequest,
    current_user: Manager,
    db: Db,
    ctx: Ctx,
) -> PromotionResponse:
    return PromotionService.update(db, current_user, promotion_id, req, ctx)
