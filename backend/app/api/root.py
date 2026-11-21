from fastapi import APIRouter

from app.schemas.root import RootLinks, RootResponse

router = APIRouter()

SERVICE_NAME = "3 Sixty Technologies API"
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
    return RootResponse(
        service=SERVICE_NAME,
        message=f"Welcome to the {SERVICE_NAME}.",
        links=LINKS,
    )
