import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models.enums import BloodType, RequestStatus, Urgency

MAX_UNITS_PER_REQUEST = 20

Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


class BloodRequestCreate(BaseModel):
    """What a hospital sends. Status, deadlines, counters and the blood bank are set by the server."""

    model_config = ConfigDict(extra="forbid")

    blood_type: BloodType
    units_needed: int = Field(ge=1, le=MAX_UNITS_PER_REQUEST, strict=True)
    urgency: Urgency
    notes: Notes | None = None

    @field_validator("notes")
    @classmethod
    def blank_notes_become_none(cls, value: str | None) -> str | None:
        return value or None


class BloodRequestResponse(BaseModel):
    """The hospital's view of its own request."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hospital_id: uuid.UUID
    blood_bank_id: uuid.UUID
    blood_type: BloodType
    units_needed: int
    units_from_inventory: int
    units_confirmed: int
    urgency: Urgency
    status: RequestStatus
    response_deadline: datetime | None
    current_batch: int
    donor_deadline: datetime | None
    notes: str | None
    fulfilled_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime
