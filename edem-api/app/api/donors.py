import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentDonor, DbSession, DonorUser
from app.api.pagination import PageDep, paginated
from app.api.request_views import donor_request_item
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
from app.services import request_queries
from app.services.ownership import get_match_for_donor

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


@router.get("/requests")
def list_requests(
    donor: CurrentDonor,
    db: DbSession,
    page: PageDep,
    open_only: Annotated[
        bool, Query(description="Only requests still in progress for this donor")
    ] = False,
):
    """The requests sent to this donor. This is also the fallback screen when a push never arrives."""
    entries, total = request_queries.list_donor_requests(
        db, donor, open_only=open_only, limit=page.page_size, offset=page.offset
    )
    items = [donor_request_item(entry).model_dump(mode="json") for entry in entries]
    return success_response(paginated(items, total, page))


@router.get("/requests/{match_id}")
def get_request(match_id: uuid.UUID, donor: CurrentDonor, db: DbSession):
    match = get_match_for_donor(db, match_id, donor)
    entry = request_queries.get_donor_request(db, match, donor)
    return success_response(donor_request_item(entry).model_dump(mode="json"))
