"""Helpers for creating test data."""

import itertools
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.models.blood_bank import BloodBank
from app.models.blood_request import BloodRequest
from app.models.device_token import DeviceToken
from app.models.donor import Donor
from app.models.enums import (
    ApprovalStatus,
    BloodType,
    DevicePlatform,
    Gender,
    RequestStatus,
    Urgency,
    UserRole,
    VerificationStatus,
)
from app.models.hospital import Hospital
from app.models.match import Match
from app.models.user import User

_counter = itertools.count(1)

# Addis Ababa
LATITUDE = 9.03
LONGITUDE = 38.74


def make_user(
    db: Session,
    role: UserRole = UserRole.DONOR,
    *,
    email: str | None = None,
    is_active: bool = True,
) -> User:
    """Insert a user directly (admins cannot register through the API).

    The password hash is a placeholder: use the register and login endpoints
    in tests that need a real login.
    """
    user = User(
        email=email or f"{role.value}-{next(_counter)}@edem-demo.org",
        phone="+251911234567",
        password_hash="not-a-real-hash",
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def auth_headers(user: User) -> dict[str, str]:
    """Authorization header with a valid access token for this user."""
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def make_blood_bank(
    db: Session,
    *,
    user: User | None = None,
    approval_status: ApprovalStatus = ApprovalStatus.APPROVED,
    is_active: bool = True,
    name: str | None = None,
    city: str = "Addis Ababa",
    latitude: float = LATITUDE,
    longitude: float = LONGITUDE,
) -> BloodBank:
    """A blood bank profile. Approved by default, to keep other tests short."""
    owner = user or make_user(db, UserRole.BLOOD_BANK)
    blood_bank = BloodBank(
        user_id=owner.id,
        name=name or f"Test Blood Bank {next(_counter)}",
        address="Churchill Avenue",
        city=city,
        latitude=latitude,
        longitude=longitude,
        contact_phone="+251111234567",
        is_active=is_active,
        approval_status=approval_status,
    )
    db.add(blood_bank)
    db.commit()
    db.refresh(blood_bank)
    return blood_bank


def make_hospital(
    db: Session,
    *,
    user: User | None = None,
    blood_bank: BloodBank | None = None,
    approval_status: ApprovalStatus = ApprovalStatus.APPROVED,
    name: str | None = None,
) -> Hospital:
    """A hospital profile (creates its primary blood bank if none is given). Approved by default."""
    owner = user or make_user(db, UserRole.HOSPITAL)
    primary_bank = blood_bank or make_blood_bank(db)
    hospital = Hospital(
        user_id=owner.id,
        blood_bank_id=primary_bank.id,
        name=name or f"Test Hospital {next(_counter)}",
        address="Bole Road",
        city="Addis Ababa",
        latitude=LATITUDE,
        longitude=LONGITUDE,
        contact_phone="+251111234568",
        approval_status=approval_status,
    )
    db.add(hospital)
    db.commit()
    db.refresh(hospital)
    return hospital


def make_donor(
    db: Session,
    *,
    user: User | None = None,
    blood_bank: BloodBank | None = None,
    blood_type: BloodType = BloodType.O_POS,
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED,
    is_available: bool = True,
    last_donation_date: date | None = None,
    full_name: str | None = None,
) -> Donor:
    """A donor profile (creates the donor user and a blood bank if none are given)."""
    owner = user or make_user(db, UserRole.DONOR)
    bank = blood_bank or make_blood_bank(db)
    suspension: dict = {}
    if verification_status == VerificationStatus.SUSPENDED:
        # The database requires who, when and why for a suspended donor.
        suspension = {
            "suspended_by": make_user(db, UserRole.ADMIN).id,
            "suspended_at": datetime.now(UTC),
            "suspension_reason": "test reason",
        }
    donor = Donor(
        user_id=owner.id,
        blood_bank_id=bank.id,
        full_name=full_name or f"Test Donor {next(_counter)}",
        blood_type=blood_type,
        gender=Gender.FEMALE,
        date_of_birth=date(1995, 1, 1),
        weight_kg=65.0,
        latitude=LATITUDE,
        longitude=LONGITUDE,
        is_available=is_available,
        last_donation_date=last_donation_date,
        verification_status=verification_status,
        **suspension,
    )
    db.add(donor)
    db.commit()
    db.refresh(donor)
    return donor


def make_blood_request(
    db: Session,
    *,
    hospital: Hospital | None = None,
    blood_type: BloodType = BloodType.O_POS,
    units_needed: int = 2,
    status: RequestStatus = RequestStatus.PENDING_BLOOD_BANK,
    urgency: Urgency = Urgency.NORMAL,
    response_deadline: datetime | None = None,
    donor_deadline: datetime | None = None,
    units_from_inventory: int = 0,
    units_confirmed: int = 0,
) -> BloodRequest:
    """A blood request from the hospital, assigned to the hospital's primary blood bank."""
    owner = hospital or make_hospital(db)
    blood_request = BloodRequest(
        hospital_id=owner.id,
        blood_bank_id=owner.blood_bank_id,
        blood_type=blood_type,
        units_needed=units_needed,
        units_from_inventory=units_from_inventory,
        units_confirmed=units_confirmed,
        urgency=urgency,
        status=status,
        latitude=owner.latitude,
        longitude=owner.longitude,
        response_deadline=response_deadline,
        donor_deadline=donor_deadline,
    )
    db.add(blood_request)
    db.commit()
    db.refresh(blood_request)
    return blood_request


def make_match(
    db: Session,
    *,
    blood_request: BloodRequest | None = None,
    donor: Donor | None = None,
    batch_number: int = 1,
    distance_km: float = 3.5,
) -> Match:
    """A donor notified for a blood request."""
    request_for_match = blood_request or make_blood_request(db)
    donor_for_match = donor or make_donor(db)
    match = Match(
        request_id=request_for_match.id,
        donor_id=donor_for_match.id,
        batch_number=batch_number,
        distance_km=distance_km,
    )
    db.add(match)
    db.commit()
    db.refresh(match)
    return match


def make_device(
    db: Session,
    *,
    user: User | None = None,
    token: str | None = None,
    platform: DevicePlatform | None = None,
) -> DeviceToken:
    """A registered device token for a user (a donor is created if no user is given)."""
    owner = user or make_user(db, UserRole.DONOR)
    device = DeviceToken(
        user_id=owner.id,
        token=token or f"test-device-token-{next(_counter)}-" + "x" * 40,
        platform=platform,
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return device
