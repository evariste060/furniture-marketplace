import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.identifiers import (
    EMAIL_MAX_LENGTH,
    PHONE_INPUT_MAX_LENGTH,
    validate_email_format,
    validate_rwanda_phone,
)
from app.core.roles import StaffRoleName, effective_permissions, staff_role
from app.core.security import PASSWORD_MAX_LENGTH, validate_password_strength
from app.models.identity import User


class StaffResponse(BaseModel):
    """A staff account. Never includes password hashes, session tokens or other secrets."""

    id: uuid.UUID
    email: str | None = None
    phone: str | None = None
    full_name: str | None = None
    role: StaffRoleName
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_user(cls, user: User) -> "StaffResponse":
        return cls.model_validate(_staff_fields(user))


class StaffMeResponse(StaffResponse):
    permissions: list[str] = Field(
        description="Effective permissions from the server-side role mapping"
    )

    @classmethod
    def from_user(cls, user: User) -> "StaffMeResponse":
        return cls.model_validate(
            {**_staff_fields(user), "permissions": effective_permissions(user)}
        )


class StaffPermissionsResponse(BaseModel):
    role: StaffRoleName
    permissions: list[str] = Field(
        description="Effective permissions from the server-side role mapping"
    )


def _staff_fields(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "phone": user.phone,
        "full_name": user.full_name,
        "role": staff_role(user),
        "is_active": user.is_active,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


class StaffCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str | None = Field(default=None, max_length=EMAIL_MAX_LENGTH, description="Work email")
    phone: str | None = Field(
        default=None,
        max_length=PHONE_INPUT_MAX_LENGTH,
        description="Rwandan mobile number: +2507XXXXXXXX, 2507XXXXXXXX or 07XXXXXXXX",
    )
    full_name: str = Field(..., min_length=2, max_length=255)
    password: str = Field(
        ...,
        max_length=PASSWORD_MAX_LENGTH,
        description="Initial password: 8-256 characters with upper and lower case and a digit "
        "or symbol. Never returned or logged.",
    )
    # The Marketplace Administrator is the only staff role (SC-05); any other value is 422.
    role: StaffRoleName = "administrator"

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str | None) -> str | None:
        return validate_email_format(v) if v is not None else v

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        return validate_rwanda_phone(v) if v is not None else v

    @model_validator(mode="after")
    def check_identity(self) -> "StaffCreateRequest":
        if not self.email and not self.phone:
            raise ValueError("Either email or phone number must be provided.")
        ok, msg = validate_password_strength(self.password)
        if not ok:
            raise ValueError(msg)
        return self


class StaffUpdateRequest(BaseModel):
    """Editable staff details. Role, status, email, password and flags are rejected (422)."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    phone: str | None = Field(
        default=None,
        max_length=PHONE_INPUT_MAX_LENGTH,
        description="Rwandan mobile number (stored as +2507XXXXXXXX)",
    )

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        return validate_rwanda_phone(v) if v is not None else v

    @model_validator(mode="after")
    def check_not_empty(self) -> "StaffUpdateRequest":
        if self.full_name is None and self.phone is None:
            raise ValueError("Provide at least one of: full_name, phone.")
        return self


class StaffStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool = Field(description="false disables the account and revokes its sessions")
