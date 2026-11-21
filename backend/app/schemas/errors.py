from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str = Field(description="Stable machine-readable error code", examples=["not_found"])
    message: str = Field(description="Human-readable message, safe to display")
    details: Any = Field(
        default=None,
        description="Optional structured details; for validation errors a list of "
        "{type, loc, msg} entries (submitted values are never echoed)",
    )


class ErrorResponse(BaseModel):
    """Body of every error response."""

    error: ErrorBody
