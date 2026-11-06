"""Helpers for creating test data."""

import itertools

from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.models.blood_bank import BloodBank
from app.models.enums import ApprovalStatus, UserRole
from app.models.hospital import Hospital
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
) -> BloodBank:
    """A blood bank profile. Approved by default, to keep other tests short."""
    owner = user or make_user(db, UserRole.BLOOD_BANK)
    blood_bank = BloodBank(
        user_id=owner.id,
        name=name or f"Test Blood Bank {next(_counter)}",
        address="Churchill Avenue",
        city="Addis Ababa",
        latitude=LATITUDE,
        longitude=LONGITUDE,
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
