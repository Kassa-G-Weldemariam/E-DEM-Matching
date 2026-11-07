from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import BloodBankUser, DbSession
from app.api.pagination import PageDep, paginated
from app.core.exceptions import BadRequestException, NotFoundException
from app.core.responses import success_response
from app.models.blood_bank import BloodBank
from app.schemas.blood_bank import (
    BloodBankProfileInput,
    BloodBankProfileResponse,
    BloodBankPublic,
)
from app.services import blood_banks as blood_bank_service

router = APIRouter(prefix="/blood-banks", tags=["Blood Banks"])


def _profile_response(blood_bank: BloodBank) -> dict:
    return BloodBankProfileResponse.model_validate(blood_bank).model_dump(mode="json")


# ---------------------------------------------------------------- public list


@router.get("")
def list_blood_banks(
    db: DbSession,
    page: PageDep,
    city: Annotated[
        str | None, Query(max_length=100, description="Only banks in this city")
    ] = None,
    lat: Annotated[
        float | None, Query(ge=-90, le=90, description="Your latitude (with lng)")
    ] = None,
    lng: Annotated[
        float | None, Query(ge=-180, le=180, description="Your longitude (with lat)")
    ] = None,
):
    """Public. Lists approved, active blood banks so donors and hospitals can pick one at signup."""
    if (lat is None) != (lng is None):
        raise BadRequestException("Send both lat and lng, or neither")

    ranked = blood_bank_service.list_public_blood_banks(
        db, city=city, latitude=lat, longitude=lng
    )
    window = ranked[page.offset : page.offset + page.page_size]
    items = [
        BloodBankPublic.model_validate(bank)
        .model_copy(update={"distance_km": distance})
        .model_dump(mode="json")
        for bank, distance in window
    ]
    return success_response(paginated(items, len(ranked), page))


# ------------------------------------------------------- own profile
# These use the plain BloodBankUser guard, NOT ApprovedBloodBank: a new bank has to be
# able to create its profile to get approved, and a pending bank has to see its status.
# Keep these routes above any route that has an {id} in its path.

@router.post("/profile", status_code=status.HTTP_201_CREATED)
def create_profile(data: BloodBankProfileInput, user: BloodBankUser, db: DbSession):
    blood_bank = blood_bank_service.create_blood_bank_profile(db, user, data)
    return success_response(
        _profile_response(blood_bank),
        "Profile created. It is waiting for Admin approval",
    )


@router.get("/profile")
def get_profile(user: BloodBankUser, db: DbSession):
    blood_bank = blood_bank_service.get_blood_bank_by_user(db, user.id)
    if blood_bank is None:
        raise NotFoundException("You have not created your blood bank profile yet")
    return success_response(_profile_response(blood_bank))


@router.put("/profile")
def update_profile(data: BloodBankProfileInput, user: BloodBankUser, db: DbSession):
    blood_bank = blood_bank_service.get_blood_bank_by_user(db, user.id)
    if blood_bank is None:
        raise NotFoundException("You have not created your blood bank profile yet")
    blood_bank = blood_bank_service.update_blood_bank_profile(db, blood_bank, data)
    return success_response(_profile_response(blood_bank), "Profile updated")
