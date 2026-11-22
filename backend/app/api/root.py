from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.root import RootLinks, RootResponse

router = APIRouter()

LINKS = RootLinks(
    health="/api/v1/health",
    docs="/docs",
    redoc="/redoc",
    openapi="/api/v1/openapi.json",
)


@router.get(
    "/",
    response_model=RootResponse,
    tags=["Health"],
    summary="Service identity and links",
)
def root() -> RootResponse:
    """Identifies the service and links to its health check and documentation. Checks no
    dependency: use the health link for that."""
    service_name = f"{get_settings().marketplace_name} API"
    return RootResponse(
        service=service_name,
        message=f"Welcome to the {service_name}.",
        links=LINKS,
    )
