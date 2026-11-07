from fastapi import APIRouter, status
from sqlalchemy.orm import Session

from app.api.deps import DbSession, HospitalUser
from app.core.exceptions import NotFoundException
from app.core.responses import success_response
from app.models.blood_bank import BloodBank
from app.models.hospital import Hospital
from app.schemas.hospital import HospitalProfileInput, HospitalProfileResponse
from app.services import hospitals as hospital_service

router = APIRouter(prefix="/hospitals", tags=["Hospitals"])

# These use the plain HospitalUser guard, NOT ApprovedHospital: a new hospital has to be
# able to create its profile to get approved, and a pending one has to see its status.
# Keep these routes above any route that has an {id} in its path.


def _profile_response(db: Session, hospital: Hospital) -> dict:
    blood_bank = db.get(BloodBank, hospital.blood_bank_id)
    response = HospitalProfileResponse.model_validate(hospital).model_copy(
        update={"blood_bank_name": blood_bank.name if blood_bank else None}
    )
    return response.model_dump(mode="json")


@router.post("/profile", status_code=status.HTTP_201_CREATED)
def create_profile(data: HospitalProfileInput, user: HospitalUser, db: DbSession):
    hospital = hospital_service.create_hospital_profile(db, user, data)
    return success_response(
        _profile_response(db, hospital),
        "Profile created. It is waiting for Admin approval",
    )


@router.get("/profile")
def get_profile(user: HospitalUser, db: DbSession):
    hospital = hospital_service.get_hospital_by_user(db, user.id)
    if hospital is None:
        raise NotFoundException("You have not created your hospital profile yet")
    return success_response(_profile_response(db, hospital))


@router.put("/profile")
def update_profile(data: HospitalProfileInput, user: HospitalUser, db: DbSession):
    hospital = hospital_service.get_hospital_by_user(db, user.id)
    if hospital is None:
        raise NotFoundException("You have not created your hospital profile yet")
    hospital = hospital_service.update_hospital_profile(db, hospital, data)
    return success_response(_profile_response(db, hospital), "Profile updated")
