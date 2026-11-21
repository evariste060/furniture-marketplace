"""Background jobs (approved 2026-10-26, checkpoint 1b topic 4): read a job's progress and retry
its failed items. The worker process (python -m app.worker) does the work. The only job type is
bulk_image_upload, a catalogue change, so the routes need 'catalog:manage'."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.responses import (
    ERR,
    FORBIDDEN_403,
    UNAUTHORIZED_401,
    VALIDATION_422,
    ResponseMap,
)
from app.core.dependencies import require_permission
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Permission
from app.db.session import get_db
from app.models.identity import User
from app.schemas.jobs import JobResponse
from app.services import jobs

router = APIRouter(prefix="/staff/jobs", tags=["Staff Jobs"])

GUARDED: ResponseMap = {**UNAUTHORIZED_401, **FORBIDDEN_403}
JOB_404: ResponseMap = {404: {**ERR, "description": "job_not_found: no job with this ID"}}
RETRY_409: ResponseMap = {
    409: {
        **ERR,
        "description": "nothing_to_retry: no failed item can be retried (files rejected before "
        "they were queued must be uploaded again)",
    }
}
CatalogManager = Annotated[User, Depends(require_permission(Permission.CATALOG_MANAGE))]
Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    summary="A job's progress and every item's outcome",
    description=(
        "Requires 'catalog:manage' (administrator). Poll it after starting a job: "
        "`state` is finished when no item is queued or processing."
    ),
    responses={**GUARDED, **JOB_404, **VALIDATION_422},
)
def get_job(job_id: uuid.UUID, current_user: CatalogManager, db: Db) -> JobResponse:
    return JobResponse.from_job(jobs.get_job(db, job_id))


@router.post(
    "/{job_id}/retry-failed",
    response_model=JobResponse,
    summary="Requeue a job's failed items",
    description=(
        "Requires 'catalog:manage' (administrator). Failed items go back to the queue "
        "with their attempts reset; done items are never redone. Audited as "
        "'job.retry_failed'."
    ),
    responses={**GUARDED, **JOB_404, **RETRY_409, **VALIDATION_422},
)
def retry_failed(job_id: uuid.UUID, current_user: CatalogManager, db: Db, ctx: Ctx) -> JobResponse:
    return JobResponse.from_job(jobs.retry_failed(db, current_user, job_id, ctx))
