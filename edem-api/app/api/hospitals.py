import uuid

from fastapi import APIRouter, status
from sqlalchemy.orm import Session

from app.api.deps import ApprovedHospital, DbSession, HospitalUser
from app.core.exceptions import NotFoundException
from app.core.responses import success_response
from app.models.blood_bank import BloodBank
from app.models.hospital import Hospital
from app.schemas.blood_request import BloodRequestCreate, BloodRequestResponse
from app.schemas.hospital import HospitalProfileInput, HospitalProfileResponse
from app.services import blood_requests as blood_request_service
from app.services import hospitals as hospital_service
from app.services.ownership import get_request_for_hospital

router = APIRouter(prefix="/hospitals", tags=["Hospitals"])

# PROFILE routes use the plain HospitalUser guard, NOT ApprovedHospital: a new hospital has
# to be able to create its profile to get approved, and a pending one has to see its status.
# ACTION routes (requests) use ApprovedHospital.


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


# ----------------------------------------------------------------- requests


@router.post("/requests", status_code=status.HTTP_201_CREATED)
def create_request(data: BloodRequestCreate, hospital: ApprovedHospital, db: DbSession):
    blood_request = blood_request_service.create_blood_request(db, hospital, data)
    return success_response(
        BloodRequestResponse.model_validate(blood_request).model_dump(mode="json"),
        "Blood request created",
    )


@router.get("/requests/{request_id}")
def get_request(request_id: uuid.UUID, hospital: ApprovedHospital, db: DbSession):
    blood_request = get_request_for_hospital(db, request_id, hospital)
    return success_response(
        BloodRequestResponse.model_validate(blood_request).model_dump(mode="json")
    )
