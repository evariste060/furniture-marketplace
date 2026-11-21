from pydantic import BaseModel, Field

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


class Page[T](BaseModel):
    """Every paginated list: one page of items plus the total number of matches."""

    items: list[T]
    total: int = Field(ge=0, description="Number of items matching the filters")
    page: int = Field(ge=1, description="Page number, starting at 1")
    size: int = Field(ge=1, le=MAX_PAGE_SIZE, description="Requested page size")


def page_offset(page: int, size: int) -> int:
    return (page - 1) * size
