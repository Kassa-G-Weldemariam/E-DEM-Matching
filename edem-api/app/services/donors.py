import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, ProfileAlreadyExistsException
from app.models.donor import Donor
from app.models.enums import VerificationStatus
from app.models.user import User
from app.schemas.donor import DonorProfileCreate, DonorProfileUpdate
from app.services.blood_banks import require_available_blood_bank


def get_donor_by_user(db: Session, user_id: uuid.UUID) -> Donor | None:
    return db.scalar(select(Donor).where(Donor.user_id == user_id))


def create_donor_profile(db: Session, user: User, data: DonorProfileCreate) -> Donor:
    """Create the user's donor profile. It always starts unverified and available."""
    if get_donor_by_user(db, user.id):
        raise ProfileAlreadyExistsException("You have already created a donor profile")
    require_available_blood_bank(db, data.blood_bank_id)

    donor = Donor(
        user_id=user.id,
        verification_status=VerificationStatus.UNVERIFIED,
        is_available=True,
        **data.model_dump(),
    )
    db.add(donor)
    try:
        db.commit()
    except IntegrityError:
        # Two requests at the same moment: the database unique rule on user_id wins.
        db.rollback()
        raise ProfileAlreadyExistsException(
            "You have already created a donor profile"
        ) from None
    db.refresh(donor)
    return donor


def update_donor_profile(db: Session, donor: Donor, data: DonorProfileUpdate) -> Donor:
    """Update the details a donor may change. Verification, availability and blood bank are untouched."""
    new_date = data.last_donation_date
    if (
        new_date is not None
        and donor.last_donation_date is not None
        and new_date < donor.last_donation_date
    ):
        # Otherwise a donor could skip the waiting period by editing the date a hospital recorded.
        raise BadRequestException(
            "The last donation date cannot be earlier than the one already recorded. "
            "Ask your blood bank to correct it"
        )

    donor.full_name = data.full_name
    donor.blood_type = data.blood_type
    donor.gender = data.gender
    donor.date_of_birth = data.date_of_birth
    donor.weight_kg = data.weight_kg
    donor.latitude = data.latitude
    donor.longitude = data.longitude
    if new_date is not None:
        donor.last_donation_date = new_date
    db.commit()
    db.refresh(donor)
    return donor


def set_availability(db: Session, donor: Donor, is_available: bool) -> Donor:
    donor.is_available = is_available
    db.commit()
    db.refresh(donor)
    return donor
