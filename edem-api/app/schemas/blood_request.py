import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models.enums import BloodType, MatchStatus, RequestStatus, Urgency

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
    units_remaining: int
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


class HistoryItem(BaseModel):
    """One status change. The actor is a role or "system", never a user id."""

    from_status: RequestStatus | None
    to_status: RequestStatus
    actor: str
    note: str | None
    created_at: datetime


class MatchedDonor(BaseModel):
    """What a hospital may know about a donor it is dealing with in person."""

    full_name: str
    blood_type: BloodType
    phone: str | None


class RequestMatchItem(BaseModel):
    match_id: uuid.UUID
    batch_number: int
    status: MatchStatus
    distance_km: float
    notified_at: datetime
    responded_at: datetime | None
    arrived_at: datetime | None
    donated_at: datetime | None
    donor: MatchedDonor | None  # only for donors the hospital deals with in person


class DonorRequestSummary(BaseModel):
    """The request as a donor sees it. No notes: they may describe a patient."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    blood_type: BloodType
    units_needed: int
    units_confirmed: int
    units_remaining: int
    urgency: Urgency
    status: RequestStatus
    created_at: datetime


class HospitalContact(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    address: str
    city: str
    latitude: float
    longitude: float
    contact_phone: str


class DonorRequestItem(BaseModel):
    match_id: uuid.UUID
    match_status: MatchStatus
    distance_km: float
    notified_at: datetime
    responded_at: datetime | None
    can_respond: bool
    request: DonorRequestSummary
    hospital: HospitalContact
