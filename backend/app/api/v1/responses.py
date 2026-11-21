"""Shared OpenAPI error response declarations, so documented codes match real behaviour."""

from typing import Any

from app.schemas.errors import ErrorResponse

ResponseMap = dict[int | str, dict[str, Any]]

ERR: dict[str, Any] = {"model": ErrorResponse}

VALIDATION_422: ResponseMap = {
    422: {**ERR, "description": "Request body, path or query failed validation"}
}
UNAUTHORIZED_401: ResponseMap = {
    401: {**ERR, "description": "Token missing, invalid, expired or revoked"}
}
INACTIVE_403: ResponseMap = {403: {**ERR, "description": "Account is inactive or disabled"}}
FORBIDDEN_403: ResponseMap = {
    403: {**ERR, "description": "Account inactive, or role lacks the required permission"}
}
NOT_FOUND_404: ResponseMap = {
    404: {**ERR, "description": "Address not found or not owned by the caller"}
}
AUTHENTICATED: ResponseMap = {**UNAUTHORIZED_401, **INACTIVE_403}
