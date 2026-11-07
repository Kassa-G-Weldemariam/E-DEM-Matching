import uuid
from datetime import date, datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationInfo,
    field_validator,
)

from app.core.config import get_settings
from app.core.dates import age_in_years
from app.models.enums import BloodType, Gender, VerificationStatus
from app.schemas.blood_bank import Name
from app.schemas.common import Latitude, Longitude

# Weight is only checked for plausibility here. The real minimum weight for donating is
# applied by the matching engine, because a donor's weight can change.
MIN_PLAUSIBLE_WEIGHT_KG = 20
MAX_PLAUSIBLE_WEIGHT_KG = 300
MAX_PLAUSIBLE_AGE_YEARS = 120


class DonorProfileUpdate(BaseModel):
    """Used to update (PUT) a profile. Every field is required except last_donation_date.

    Verification status, availability, the blood bank and the owner are NOT here on
    purpose: unknown fields are rejected, so a client cannot set them.
    """

    model_config = ConfigDict(extra="forbid")

    full_name: Name
    blood_type: BloodType
    gender: Gender
    date_of_birth: date
    weight_kg: float = Field(ge=MIN_PLAUSIBLE_WEIGHT_KG, le=MAX_PLAUSIBLE_WEIGHT_KG)
    latitude: Latitude
    longitude: Longitude
    # Optional. Leaving it out (or sending null) keeps the date already recorded.
    last_donation_date: date | None = None

    @field_validator("date_of_birth")
    @classmethod
    def check_date_of_birth(cls, value: date) -> date:
        today = date.today()
        if value > today:
            raise ValueError("Date of birth cannot be in the future")
        age = age_in_years(value, today)
        minimum = get_settings().MIN_AGE_YEARS
        if age < minimum:
            raise ValueError(f"You must be at least {minimum} years old to donate")
        if age > MAX_PLAUSIBLE_AGE_YEARS:
            raise ValueError("Enter a valid date of birth")
        return value

    @field_validator("last_donation_date")
    @classmethod
    def check_last_donation_date(
        cls, value: date | None, info: ValidationInfo
    ) -> date | None:
        if value is None:
            return None
        if value > date.today():
            raise ValueError("Last donation date cannot be in the future")
        born = info.data.get(
            "date_of_birth"
        )  # missing when the date of birth itself was invalid
        if born is not None and value < born:
            raise ValueError("Last donation date cannot be before the date of birth")
        return value


class DonorProfileCreate(DonorProfileUpdate):
    """Creating a profile also chooses the blood bank the donor registers under."""

    blood_bank_id: uuid.UUID  # chosen from GET /v1/blood-banks


class AvailabilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_available: StrictBool  # only JSON true or false


class DonorProfileResponse(BaseModel):
    """The donor's view of their own profile."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    blood_bank_id: uuid.UUID
    blood_bank_name: str | None = None
    full_name: str
    blood_type: BloodType
    gender: Gender
    date_of_birth: date
    weight_kg: float
    latitude: float
    longitude: float
    last_donation_date: date | None
    is_available: bool
    verification_status: VerificationStatus
    suspended_at: datetime | None
    suspension_reason: str | None
    created_at: datetime
    updated_at: datetime
