from fastapi import APIRouter, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentDonor, DbSession, DonorUser
from app.core.exceptions import NotFoundException
from app.core.responses import success_response
from app.models.blood_bank import BloodBank
from app.models.donor import Donor
from app.schemas.donor import (
    AvailabilityRequest,
    DonorProfileCreate,
    DonorProfileResponse,
    DonorProfileUpdate,
)
from app.services import donors as donor_service

router = APIRouter(prefix="/donors", tags=["Donors"])

# These use the plain DonorUser guard: a new donor must be able to create a profile, and an
# unverified or suspended donor must be able to see their status.
# Keep these routes above any route that has an {id} in its path.


def _profile_response(db: Session, donor: Donor) -> dict:
    blood_bank = db.get(BloodBank, donor.blood_bank_id)
    response = DonorProfileResponse.model_validate(donor).model_copy(
        update={"blood_bank_name": blood_bank.name if blood_bank else None}
    )
    return response.model_dump(mode="json")


@router.post("/profile", status_code=status.HTTP_201_CREATED)
def create_profile(data: DonorProfileCreate, user: DonorUser, db: DbSession):
    donor = donor_service.create_donor_profile(db, user, data)
    return success_response(_profile_response(db, donor), "Profile created")


@router.get("/profile")
def get_profile(user: DonorUser, db: DbSession):
    donor = donor_service.get_donor_by_user(db, user.id)
    if donor is None:
        raise NotFoundException("You have not created your donor profile yet")
    return success_response(_profile_response(db, donor))


@router.put("/profile")
def update_profile(data: DonorProfileUpdate, donor: CurrentDonor, db: DbSession):
    donor = donor_service.update_donor_profile(db, donor, data)
    return success_response(_profile_response(db, donor), "Profile updated")


@router.patch("/availability")
def update_availability(data: AvailabilityRequest, donor: CurrentDonor, db: DbSession):
    donor = donor_service.set_availability(db, donor, data.is_available)
    return success_response(_profile_response(db, donor), "Availability updated")
