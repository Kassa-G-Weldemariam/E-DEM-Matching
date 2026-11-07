import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import ApprovalStatus
from app.schemas.blood_bank import Address, City, Name
from app.schemas.common import Latitude, Longitude, PhoneNumber


class HospitalProfileInput(BaseModel):
    """Used to create and to update (PUT) a profile. Every field is required.

    Approval status and the owner are NOT here on purpose: unknown fields are
    rejected, so a client cannot set them.
    """

    model_config = ConfigDict(extra="forbid")

    blood_bank_id: uuid.UUID  # the primary blood bank, chosen from GET /v1/blood-banks
    name: Name
    address: Address
    city: City
    latitude: Latitude
    longitude: Longitude
    contact_phone: PhoneNumber


class HospitalProfileResponse(BaseModel):
    """The owner's view of their own profile."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    blood_bank_id: uuid.UUID
    blood_bank_name: str | None = None
    name: str
    address: str
    city: str
    latitude: float
    longitude: float
    contact_phone: str
    approval_status: ApprovalStatus
    created_at: datetime
    updated_at: datetime
