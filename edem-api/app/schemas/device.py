import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.models.enums import DevicePlatform

# 512 is the size of the database column. Tokens must not contain spaces.
DeviceToken = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=20, max_length=512, pattern=r"^\S+$"
    ),
]


class DeviceRegisterRequest(BaseModel):
    """Unknown fields (for example user_id) are rejected, so nobody can register for someone else."""

    model_config = ConfigDict(extra="forbid")

    token: DeviceToken
    platform: DevicePlatform | None = None


class DeviceResponse(BaseModel):
    """Deliberately has no token field: tokens are never sent back."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    platform: DevicePlatform | None
    created_at: datetime
    updated_at: datetime
