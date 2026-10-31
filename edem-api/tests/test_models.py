from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.blood_bank import BloodBank
from app.models.blood_request import BloodRequest
from app.models.donor import Donor
from app.models.enums import BloodType, Gender, UserRole
from app.models.hospital import Hospital
from app.models.user import User


def create_user(db, email: str, role: UserRole = UserRole.DONOR) -> User:
    user = User(email=email, password_hash="hashed-password", role=role)
    db.add(user)
    db.flush()
    return user


def create_blood_bank(db, user_id) -> BloodBank:
    blood_bank = BloodBank(
        user_id=user_id,
        name="Central Blood Bank",
        address="1 Main Street",
        city="Addis Ababa",
        latitude=9.03,
        longitude=38.74,
        contact_phone="+251900000000",
    )
    db.add(blood_bank)
    db.flush()
    return blood_bank


def create_hospital(db, user_id, blood_bank_id) -> Hospital:
    hospital = Hospital(
        user_id=user_id,
        blood_bank_id=blood_bank_id,
        name="General Hospital",
        address="2 Main Street",
        city="Addis Ababa",
        latitude=9.04,
        longitude=38.75,
        contact_phone="+251911111111",
    )
    db.add(hospital)
    db.flush()
    return hospital


def test_user_crud_and_commit_isolation(db):
    user = create_user(db, "crud@example.com")
    db.commit()

    persisted = db.scalar(select(User).where(User.id == user.id))
    assert persisted is not None
    assert persisted.email == "crud@example.com"

    persisted.phone = "+251900000001"
    db.commit()
    assert db.scalar(select(User.phone).where(User.id == user.id)) == "+251900000001"

    db.delete(persisted)
    db.commit()
    assert db.scalar(select(User).where(User.id == user.id)) is None


def test_user_email_must_be_unique(db):
    create_user(db, "duplicate@example.com")
    db.commit()
    duplicate = User(
        email="duplicate@example.com",
        password_hash="another-hash",
        role=UserRole.HOSPITAL,
    )
    db.add(duplicate)

    with pytest.raises(IntegrityError):
        db.flush()


def test_donor_constraints_reject_non_positive_weight(db):
    donor_user = create_user(db, "donor@example.com")
    bank_user = create_user(db, "bank@example.com", UserRole.BLOOD_BANK)
    blood_bank = create_blood_bank(db, bank_user.id)
    donor = Donor(
        user_id=donor_user.id,
        blood_bank_id=blood_bank.id,
        full_name="Test Donor",
        blood_type=BloodType.O_POS,
        gender=Gender.MALE,
        date_of_birth=date(1990, 1, 1),
        weight_kg=0,
        latitude=9.03,
        longitude=38.74,
    )
    db.add(donor)

    with pytest.raises(IntegrityError):
        db.flush()


def test_blood_request_units_cannot_exceed_requested_total(db):
    hospital_user = create_user(db, "hospital@example.com", UserRole.HOSPITAL)
    bank_user = create_user(db, "request-bank@example.com", UserRole.BLOOD_BANK)
    blood_bank = create_blood_bank(db, bank_user.id)
    hospital = create_hospital(db, hospital_user.id, blood_bank.id)
    request = BloodRequest(
        hospital_id=hospital.id,
        blood_bank_id=blood_bank.id,
        blood_type=BloodType.A_POS,
        units_needed=2,
        units_from_inventory=2,
        units_confirmed=1,
        latitude=9.04,
        longitude=38.75,
    )
    db.add(request)

    with pytest.raises(IntegrityError):
        db.flush()
