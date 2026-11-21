import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.responses import ERR
from app.core.errors import ServiceUnavailable
from app.db.session import database_is_reachable, get_db
from app.integrations.media import MediaStorage, get_media_storage
from app.schemas.health import CheckStatus, HealthChecks, HealthResponse
from app.services.dev_data_guard import catalogue_status

router = APIRouter()
logger = logging.getLogger("app.health")


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="API, database, storage and catalogue health",
    responses={503: {**ERR, "description": "The database is unreachable"}},
)
def health(
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[MediaStorage, Depends(get_media_storage)],
) -> HealthResponse:
    """Process liveness, a database round trip (SELECT 1, 2-second limit) and an image storage
    probe. An unreachable database is 503; degraded storage is reported with 200, because the
    catalogue still works (the storefront shows placeholders for images that fail to load).
    In production, development seed SKUs (DEV-) make the catalogue check degraded (200)."""
    if not database_is_reachable(db):
        raise ServiceUnavailable("The database is unreachable.", code="database_unavailable")
    checks = HealthChecks(storage=storage_status(storage), catalogue=catalogue_status(db))
    degraded = "degraded" in (checks.storage, checks.catalogue)
    return HealthResponse(status="degraded" if degraded else "ok", checks=checks)


def storage_status(storage: MediaStorage) -> CheckStatus:
    try:
        storage.free_bytes()
    except Exception as exc:  # noqa: BLE001 - any failure means storage is not usable
        logger.warning("Storage health check failed: %s", type(exc).__name__)
        return "degraded"
    return "ok"
