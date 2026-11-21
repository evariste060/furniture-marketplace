"""Application errors, rendered by the handlers in app.main as the standard error body:

    {"error": {"code": "<stable machine code>", "message": "<safe text>", "details": ...}}

Services and routers raise these instead of fastapi.HTTPException. `code` is stable for clients
to branch on; `message` is human-readable and never contains secrets or submitted values.
"""

from typing import Any


class AppError(Exception):
    status_code = 500
    code = "internal_error"
    message = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or type(self).message
        self.code = code or type(self).code
        self.details = details
        self.headers = headers
        super().__init__(self.message)


class BadRequest(AppError):
    status_code = 400
    code = "bad_request"
    message = "The request could not be processed."


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"
    message = "Authentication is required."


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"
    message = "Access forbidden."


class NotFound(AppError):
    status_code = 404
    code = "not_found"
    message = "Resource not found."


class Conflict(AppError):
    status_code = 409
    code = "conflict"
    message = "The request conflicts with the current state."


class PayloadTooLarge(AppError):
    status_code = 413
    code = "file_too_large"
    message = "The upload is larger than allowed."


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_error"
    message = "Request validation failed."


class TooManyRequests(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests."


class InsufficientStorage(AppError):
    status_code = 507
    code = "insufficient_storage"
    message = "There is not enough storage space for this upload right now."


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "The service is temporarily unavailable."


def field_error(location: tuple[str, ...], message: str) -> ValidationFailed:
    """A 422 for a rule FastAPI cannot express, shaped like a schema validation error."""
    details = [{"type": "value_error", "loc": list(location), "msg": message}]
    return ValidationFailed(details=details)
