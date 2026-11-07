import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, ProfileAlreadyExistsException
from app.models.enums import ApprovalStatus
from app.models.hospital import Hospital
from app.models.user import User
from app.schemas.hospital import HospitalProfileInput
from app.services.blood_banks import get_available_blood_bank


def get_hospital_by_user(db: Session, user_id: uuid.UUID) -> Hospital | None:
    return db.scalar(select(Hospital).where(Hospital.user_id == user_id))


def _require_available_blood_bank(db: Session, blood_bank_id: uuid.UUID) -> None:
    if get_available_blood_bank(db, blood_bank_id) is None:
        raise BadRequestException("The selected blood bank is not available")


def create_hospital_profile(
    db: Session, user: User, data: HospitalProfileInput
) -> Hospital:
    """Create the user's hospital profile. It always starts as pending Admin approval."""
    if get_hospital_by_user(db, user.id):
        raise ProfileAlreadyExistsException(
            "You have already created a hospital profile"
        )
    _require_available_blood_bank(db, data.blood_bank_id)

    hospital = Hospital(
        user_id=user.id,
        approval_status=ApprovalStatus.PENDING,
        **data.model_dump(),
    )
    db.add(hospital)
    try:
        db.commit()
    except IntegrityError:
        # Two requests at the same moment: the database unique rule on user_id wins.
        db.rollback()
        raise ProfileAlreadyExistsException(
            "You have already created a hospital profile"
        ) from None
    db.refresh(hospital)
    return hospital


def update_hospital_profile(
    db: Session, hospital: Hospital, data: HospitalProfileInput
) -> Hospital:
    """Replace the editable fields. Approval status is never touched here."""
    # Only a NEW choice has to be available. A hospital whose bank was suspended
    # later can still edit its own details.
    if data.blood_bank_id != hospital.blood_bank_id:
        _require_available_blood_bank(db, data.blood_bank_id)

    for field, value in data.model_dump().items():
        setattr(hospital, field, value)
    db.commit()
    db.refresh(hospital)
    return hospital
