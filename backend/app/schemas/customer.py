import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.identifiers import PHONE_INPUT_MAX_LENGTH, validate_rwanda_phone
from app.models.identity import User
from app.schemas.auth import user_fields


class CustomerProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str | None = None
    phone: str | None = None
    full_name: str | None = None
    is_active: bool
    is_staff: bool
    roles: list[str]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_user(cls, user: User) -> "CustomerProfileResponse":
        return cls.model_validate(user_fields(user))


class CustomerUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(
        default=None, min_length=2, max_length=255, description="Updated full name"
    )
    phone: str | None = Field(
        default=None,
        max_length=PHONE_INPUT_MAX_LENGTH,
        description="Updated Rwandan mobile number (stored as +2507XXXXXXXX)",
    )

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        if v is not None:
            return validate_rwanda_phone(v)
        return v
