"""Shared pagination query parameters for every paginated list endpoint."""

from typing import Annotated

from fastapi import Query

from app.schemas.pagination import MAX_PAGE_SIZE

PageNumber = Annotated[int, Query(ge=1, description="Page number, starting at 1")]
PageSize = Annotated[
    int, Query(ge=1, le=MAX_PAGE_SIZE, description=f"Items per page (1-{MAX_PAGE_SIZE})")
]
