import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.models.enums import ApprovalStatus
from app.schemas.common import Latitude, Longitude, PhoneNumber

Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=255)
]
Address = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
City = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class BloodBankPublic(BaseModel):
    """What anyone may see about a blood bank. No phone, owner or approval status."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    address: str
    city: str
    latitude: float
    longitude: float
    distance_km: float | None = None  # only filled when the caller sends lat and lng


class BloodBankProfileInput(BaseModel):
    """Used to create and to update (PUT) a profile. Every field is required.

    Approval status, operating status and the owner are NOT here on purpose:
    unknown fields are rejected, so a client cannot set them.
    """

    model_config = ConfigDict(extra="forbid")

    name: Name
    address: Address
    city: City
    latitude: Latitude
    longitude: Longitude
    contact_phone: PhoneNumber


class BloodBankProfileResponse(BaseModel):
    """The owner's view of their own profile."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    address: str
    city: str
    latitude: float
    longitude: float
    contact_phone: str
    is_active: bool
    approval_status: ApprovalStatus
    created_at: datetime
    updated_at: datetime
