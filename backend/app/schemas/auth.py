import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.identifiers import (
    EMAIL_MAX_LENGTH,
    PHONE_INPUT_MAX_LENGTH,
    normalize_login_identifier,
    validate_email_format,
    validate_rwanda_phone,
)
from app.core.roles import effective_roles
from app.core.security import PASSWORD_MAX_LENGTH, validate_password_strength
from app.models.identity import User

__all__ = [
    "AuthResponse",
    "ChangePasswordRequest",
    "ForgotPasswordRequest",
    "LoginRequest",
    "MessageResponse",
    "RegisterRequest",
    "ResetPasswordRequest",
    "UserResponse",
    "validate_email_format",
    "validate_rwanda_phone",
]


class RegisterRequest(BaseModel):
    email: str | None = Field(
        default=None, max_length=EMAIL_MAX_LENGTH, description="Customer email address"
    )
    phone: str | None = Field(
        default=None,
        max_length=PHONE_INPUT_MAX_LENGTH,
        description="Rwandan mobile number: +2507XXXXXXXX, 2507XXXXXXXX or 07XXXXXXXX",
    )
    full_name: str = Field(..., min_length=2, max_length=255, description="Customer full name")
    password: str = Field(
        ...,
        max_length=PASSWORD_MAX_LENGTH,
        description="8-256 characters with upper and lower case and a digit or symbol",
    )

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str | None) -> str | None:
        if v is not None:
            return validate_email_format(v)
        return v

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        if v is not None:
            return validate_rwanda_phone(v)
        return v

    @model_validator(mode="after")
    def validate_registration(self) -> "RegisterRequest":
        if not self.email and not self.phone:
            raise ValueError("Either email or phone number must be provided.")
        is_valid, msg = validate_password_strength(self.password)
        if not is_valid:
            raise ValueError(msg)
        return self


class LoginRequest(BaseModel):
    identifier: str = Field(
        ...,
        min_length=1,
        max_length=EMAIL_MAX_LENGTH,
        description="Email address, or Rwandan mobile number in any approved format "
        "(+2507XXXXXXXX, 2507XXXXXXXX, 07XXXXXXXX)",
    )
    password: str = Field(
        ..., min_length=1, max_length=PASSWORD_MAX_LENGTH, description="Account password"
    )

    @field_validator("identifier")
    @classmethod
    def normalize_identifier(cls, v: str) -> str:
        return normalize_login_identifier(v)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str | None = None
    phone: str | None = None
    full_name: str | None = None
    is_active: bool
    is_staff: bool
    roles: list[str] = Field(
        description="Effective roles: staff roles from staff_role_assignments, else ['customer']"
    )
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> "UserResponse":
        return cls.model_validate(user_fields(user))


def user_fields(user: User) -> dict:
    """ORM user -> response fields, adding computed effective roles."""
    return {
        "id": user.id,
        "email": user.email,
        "phone": user.phone,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "is_staff": user.is_staff,
        "roles": sorted(effective_roles(user)),
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


class MeResponse(UserResponse):
    """GET /auth/me: the identity plus how the account can sign in (ADR-006 amendment
    2026-11-11), so the profile shows the true state. Never the provider subject or any hash."""

    google_linked: bool = Field(description="A Google account is linked to this account.")
    has_password: bool = Field(
        description=(
            "The account has a password. False for a customer created by Continue with Google "
            "until they set one with a reset code."
        )
    )


class AuthResponse(BaseModel):
    user: UserResponse
    session_token: str
    token_type: str = "bearer"
    expires_at: datetime


class MessageResponse(BaseModel):
    message: str


class RegisterResponse(BaseModel):
    """POST /auth/register (ADR-006 amendment 2026-11-12). With an email address the account
    waits for verification: `verification_required` is true and there is no session (the three
    session fields are null) until the link in the email is used and the customer signs in.
    Phone-only registration returns the session as before."""

    user: UserResponse
    session_token: str | None = Field(
        default=None, description="Null while the email address waits for verification."
    )
    token_type: str | None = Field(default=None, description='"bearer" when a session is given.')
    expires_at: datetime | None = None
    verification_required: bool = Field(
        description="True: a verification link was sent; sign in after using it."
    )


class VerifyEmailRequest(BaseModel):
    """The token from the verification link (the `#token=` part of the storefront URL)."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=256)


class ResendVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=320, description="The address used to register")

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return validate_email_format(v)


IDENTIFIER_DESCRIPTION = (
    "Email address, or Rwandan mobile number in any approved format "
    "(+2507XXXXXXXX, 2507XXXXXXXX, 07XXXXXXXX)"
)


class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(
        ..., min_length=1, max_length=EMAIL_MAX_LENGTH, description=IDENTIFIER_DESCRIPTION
    )

    @field_validator("identifier")
    @classmethod
    def normalize_identifier(cls, v: str) -> str:
        return normalize_login_identifier(v)


class ResetPasswordRequest(BaseModel):
    identifier: str = Field(
        ..., min_length=1, max_length=EMAIL_MAX_LENGTH, description=IDENTIFIER_DESCRIPTION
    )
    code: str = Field(..., pattern=r"^\d{6}$", description="The 6-digit code that was sent")
    new_password: str = Field(
        ...,
        min_length=1,
        max_length=PASSWORD_MAX_LENGTH,
        description="At least 8 characters with upper- and lower-case letters and a digit or "
        "symbol",
    )

    @field_validator("identifier")
    @classmethod
    def normalize_identifier(cls, v: str) -> str:
        return normalize_login_identifier(v)

    @field_validator("new_password")
    @classmethod
    def strong_password(cls, v: str) -> str:
        is_valid, msg = validate_password_strength(v)
        if not is_valid:
            raise ValueError(msg)
        return v


class ChangePasswordRequest(BaseModel):
    """A signed-in customer changes their password (approved by the project owner 2026-10-28)."""

    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(..., min_length=1, max_length=PASSWORD_MAX_LENGTH)
    new_password: str = Field(
        ...,
        min_length=1,
        max_length=PASSWORD_MAX_LENGTH,
        description="At least 8 characters with upper- and lower-case letters and a digit or "
        "symbol",
    )

    @field_validator("new_password")
    @classmethod
    def strong_password(cls, v: str) -> str:
        is_valid, msg = validate_password_strength(v)
        if not is_valid:
            raise ValueError(msg)
        return v


# ---- Continue with Google (ADR-006 amendment 2026-11-11) ----------------------------------------
OAUTH_VALUE_MAX_LENGTH = 512
OAUTH_CODE_MAX_LENGTH = 2048


class GoogleStartResponse(BaseModel):
    authorization_url: str = Field(
        description="Send the browser here (Google's consent screen). Single use."
    )
    flow_token: str = Field(
        description=(
            "Binds this sign-in to the browser that started it. Keep it in a short-lived "
            "httpOnly cookie and send it back with the callback; never expose it to page scripts."
        )
    )
    expires_at: datetime = Field(description="The callback must arrive before this time.")


class GoogleCallbackRequest(BaseModel):
    """Google's answer at the redirect URI, forwarded with the browser's flow token. Google sends
    either `code` (the user agreed) or `error` (e.g. access_denied when the user cancelled)."""

    model_config = ConfigDict(extra="forbid")

    state: str = Field(min_length=1, max_length=OAUTH_VALUE_MAX_LENGTH)
    flow_token: str = Field(min_length=1, max_length=OAUTH_VALUE_MAX_LENGTH)
    code: str | None = Field(default=None, min_length=1, max_length=OAUTH_CODE_MAX_LENGTH)
    error: str | None = Field(default=None, min_length=1, max_length=OAUTH_VALUE_MAX_LENGTH)

    @model_validator(mode="after")
    def _code_or_error(self) -> "GoogleCallbackRequest":
        if (self.code is None) == (self.error is None):
            raise ValueError("Send exactly one of code or error.")
        return self


class GoogleAuthResponse(AuthResponse):
    account_created: bool = Field(
        description="True when this sign-in created a new customer account."
    )


class GoogleLinkResponse(BaseModel):
    provider: str = "google"
    email: str | None = Field(description="The Google account's verified email address.")
    linked_at: datetime
