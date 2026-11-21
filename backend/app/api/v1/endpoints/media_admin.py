"""Media cleanup problems (ADR-009; checkpoint 1b topic 1, 2026-10-26): files the cleanup worker
could not delete yet, with their last error, so staff can see a storage problem."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import FORBIDDEN_403, UNAUTHORIZED_401, VALIDATION_422
from app.core.dependencies import require_permission
from app.core.roles import Permission
from app.db.session import get_db
from app.models.identity import User
from app.models.media import MediaObject
from app.schemas.media_admin import MediaCleanupProblem
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page, page_offset

router = APIRouter(prefix="/staff/media", tags=["Staff Catalogue"])


@router.get(
    "/cleanup-problems",
    response_model=Page[MediaCleanupProblem],
    summary="Stored files the cleanup worker could not delete",
    description=(
        "Requires 'catalog:manage' (administrator). Files retired by the API whose "
        "deletion failed at least once, most attempts first, with the last error. The worker "
        "retries them with backoff (at most hourly); an empty list means nothing is stuck."
    ),
    responses={**UNAUTHORIZED_401, **FORBIDDEN_403, **VALIDATION_422},
)
def list_cleanup_problems(
    current_user: Annotated[User, Depends(require_permission(Permission.CATALOG_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
) -> Page[MediaCleanupProblem]:
    stuck = (MediaObject.state == "deleting", MediaObject.attempts > 0)
    total = db.scalar(select(func.count(MediaObject.id)).where(*stuck)) or 0
    rows = db.scalars(
        select(MediaObject)
        .where(*stuck)
        .order_by(MediaObject.attempts.desc(), MediaObject.updated_at.desc(), MediaObject.id)
        .offset(page_offset(page, size))
        .limit(size)
    )
    items = [MediaCleanupProblem.model_validate(row) for row in rows]
    return Page[MediaCleanupProblem](items=items, total=total, page=page, size=size)
