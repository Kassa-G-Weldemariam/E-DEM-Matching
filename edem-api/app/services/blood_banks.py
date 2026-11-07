import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ProfileAlreadyExistsException
from app.core.geo import haversine_km
from app.models.blood_bank import BloodBank
from app.models.enums import ApprovalStatus
from app.models.user import User
from app.schemas.blood_bank import BloodBankProfileInput


def list_public_blood_banks(
    db: Session,
    *,
    city: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> list[tuple[BloodBank, float | None]]:
    """Approved, active blood banks. Sorted by name, or nearest first when coordinates are given.

    Distances are computed in Python. That is fine for the number of blood banks in a
    country (tens to hundreds). Revisit it if the list ever grows into the thousands.
    """
    query = select(BloodBank).where(
        BloodBank.approval_status == ApprovalStatus.APPROVED,
        BloodBank.is_active.is_(True),
    )
    if city and city.strip():
        query = query.where(func.lower(BloodBank.city) == city.strip().lower())
    banks = list(db.scalars(query.order_by(BloodBank.name, BloodBank.id)))

    if latitude is None or longitude is None:
        return [(bank, None) for bank in banks]

    ranked = sorted(
        (
            (
                bank,
                round(
                    haversine_km(latitude, longitude, bank.latitude, bank.longitude), 1
                ),
            )
            for bank in banks
        ),
        key=lambda pair: (pair[1], pair[0].name),
    )
    return [(bank, distance) for bank, distance in ranked]


def get_blood_bank_by_user(db: Session, user_id: uuid.UUID) -> BloodBank | None:
    return db.scalar(select(BloodBank).where(BloodBank.user_id == user_id))


def create_blood_bank_profile(
    db: Session, user: User, data: BloodBankProfileInput
) -> BloodBank:
    """Create the user's blood bank profile. It always starts as pending Admin approval."""
    if get_blood_bank_by_user(db, user.id):
        raise ProfileAlreadyExistsException(
            "You have already created a blood bank profile"
        )

    blood_bank = BloodBank(
        user_id=user.id,
        approval_status=ApprovalStatus.PENDING,
        is_active=True,
        **data.model_dump(),
    )
    db.add(blood_bank)
    try:
        db.commit()
    except IntegrityError:
        # Two requests at the same moment: the database unique rule on user_id wins.
        db.rollback()
        raise ProfileAlreadyExistsException(
            "You have already created a blood bank profile"
        ) from None
    db.refresh(blood_bank)
    return blood_bank


def update_blood_bank_profile(
    db: Session, blood_bank: BloodBank, data: BloodBankProfileInput
) -> BloodBank:
    """Replace the editable fields. Approval and operating status are never touched here."""
    for field, value in data.model_dump().items():
        setattr(blood_bank, field, value)
    db.commit()
    db.refresh(blood_bank)
    return blood_bank


def get_available_blood_bank(db: Session, blood_bank_id: uuid.UUID) -> BloodBank | None:
    """A blood bank that can be chosen as a primary bank: approved and operating.

    These are the same rules as the public list.
    """
    return db.scalar(
        select(BloodBank).where(
            BloodBank.id == blood_bank_id,
            BloodBank.approval_status == ApprovalStatus.APPROVED,
            BloodBank.is_active.is_(True),
        )
    )
