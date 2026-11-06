import re
import uuid
from datetime import datetime
from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ValidationInfo,
    field_validator,
)

from app.models.enums import UserRole

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128

_PHONE_PATTERN = re.compile(r"^\+?[0-9]{9,15}$")


class RegistrableRole(str, Enum):
    """Roles that can sign up on their own. 'admin' is deliberately missing."""

    DONOR = "donor"
    HOSPITAL = "hospital"
    BLOOD_BANK = "blood_bank"


class RegisterRequest(BaseModel):
    # Unknown fields (for example "is_admin") are rejected, not ignored.
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH
    )
    role: RegistrableRole
    phone: str | None = Field(default=None, validate_default=True)

    @field_validator("email", mode="before")
    @classmethod
    def clean_email(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def password_is_not_blank(cls, value: str) -> str:
        # Spaces inside or around a password are kept as typed, but it cannot be all spaces.
        if not value.strip():
            raise ValueError("Password cannot be blank")
        return value

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, value: str | None, info: ValidationInfo) -> str | None:
        cleaned = re.sub(r"[\s\-()]", "", value) if value else None
        if cleaned and not _PHONE_PATTERN.match(cleaned):
            raise ValueError("Enter a valid phone number, for example +251911234567")
        # "role" is declared before "phone", so it has already been validated here.
        if info.data.get("role") == RegistrableRole.DONOR and not cleaned:
            raise ValueError("Phone number is required for donors")
        return cleaned


class UserResponse(BaseModel):
    """What the API returns about a user. Never includes the password or its hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    phone: str | None
    role: UserRole
    is_active: bool
    created_at: datetime
