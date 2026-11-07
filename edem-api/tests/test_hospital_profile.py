import uuid

import pytest
from sqlalchemy import func, select

from app.models.enums import ApprovalStatus, UserRole
from app.models.hospital import Hospital
from tests.factories import auth_headers, make_blood_bank, make_hospital, make_user

URL = "/v1/hospitals/profile"

REQUIRED_FIELDS = [
    "blood_bank_id",
    "name",
    "address",
    "city",
    "latitude",
    "longitude",
    "contact_phone",
]


@pytest.fixture()
def bank(db):
    """An approved, active blood bank that hospitals may choose."""
    return make_blood_bank(db, name="Central Blood Bank")


def payload(bank, drop=(), **overrides) -> dict:
    data = {
        "blood_bank_id": str(bank.id),
        "name": "Tikur Anbessa Hospital",
        "address": "Churchill Avenue",
        "city": "Addis Ababa",
        "latitude": 9.03,
        "longitude": 38.74,
        "contact_phone": "+251111234568",
    }
    data.update(overrides)
    for key in drop:
        data.pop(key, None)
    return data


def hospital_user(db):
    return make_user(db, UserRole.HOSPITAL)


def create(client, user, bank, **overrides):
    return client.post(URL, json=payload(bank, **overrides), headers=auth_headers(user))


def error_fields(response) -> list[str]:
    return [item["field"] for item in response.json()["error"]["details"]]


def error_code(response) -> str:
    return response.json()["error"]["code"]


def stored(db, user) -> Hospital | None:
    return db.scalar(select(Hospital).where(Hospital.user_id == user.id))


def hospital_count(db) -> int:
    return db.scalar(select(func.count()).select_from(Hospital))


# ------------------------------------------------------------------- create


def test_hospital_creates_its_profile(client, db, bank):
    response = create(client, hospital_user(db), bank)
    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["id"]
    assert data["name"] == "Tikur Anbessa Hospital"
    assert data["blood_bank_id"] == str(bank.id)
    assert data["blood_bank_name"] == "Central Blood Bank"
    assert data["contact_phone"] == "+251111234568"
    assert data["approval_status"] == "pending"


def test_new_profile_is_pending_and_linked_to_the_user(client, db, bank):
    user = hospital_user(db)
    create(client, user, bank)
    hospital = stored(db, user)
    assert hospital is not None
    assert hospital.approval_status == ApprovalStatus.PENDING
    assert hospital.blood_bank_id == bank.id
    assert hospital.name == "Tikur Anbessa Hospital"


def test_response_does_not_expose_the_owner_account(client, db, bank):
    data = create(client, hospital_user(db), bank).json()["data"]
    assert "user_id" not in data


@pytest.mark.parametrize("field", ["approval_status", "is_active", "user_id", "id"])
def test_fields_the_client_must_not_set_are_rejected(client, db, bank, field):
    values = {
        "approval_status": "approved",
        "is_active": True,
        "user_id": str(uuid.uuid4()),
        "id": str(uuid.uuid4()),
    }
    user = hospital_user(db)
    response = create(client, user, bank, **{field: values[field]})
    assert response.status_code == 422
    assert field in error_fields(response)
    assert stored(db, user) is None


def test_a_second_profile_is_refused(client, db, bank):
    user = hospital_user(db)
    assert create(client, user, bank).status_code == 201
    response = create(client, user, bank, name="Another Name")
    assert response.status_code == 409
    assert error_code(response) == "PROFILE_ALREADY_EXISTS"
    assert hospital_count(db) == 1
    assert stored(db, user).name == "Tikur Anbessa Hospital"


@pytest.mark.parametrize("role", [UserRole.DONOR, UserRole.BLOOD_BANK, UserRole.ADMIN])
def test_other_roles_cannot_create_a_hospital_profile(client, db, bank, role):
    response = create(client, make_user(db, role), bank)
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"
    assert hospital_count(db) == 0


def test_creating_a_profile_requires_a_token(client, db, bank):
    response = client.post(URL, json=payload(bank))
    assert response.status_code == 401
    assert error_code(response) == "UNAUTHORIZED"


def test_a_deactivated_user_cannot_create_a_profile(client, db, bank):
    user = make_user(db, UserRole.HOSPITAL, is_active=False)
    response = create(client, user, bank)
    assert response.status_code == 403
    assert "deactivated" in response.json()["error"]["message"]
    assert hospital_count(db) == 0


def test_text_fields_are_trimmed(client, db, bank):
    data = create(
        client,
        hospital_user(db),
        bank,
        name="  St. Paul  ",
        address="  Bole  ",
        city=" Addis Ababa ",
    ).json()["data"]
    assert data["name"] == "St. Paul"
    assert data["address"] == "Bole"
    assert data["city"] == "Addis Ababa"


def test_the_phone_number_is_cleaned(client, db, bank):
    data = create(
        client, hospital_user(db), bank, contact_phone="+251 111-234-568"
    ).json()["data"]
    assert data["contact_phone"] == "+251111234568"


@pytest.mark.parametrize("missing", REQUIRED_FIELDS)
def test_missing_required_fields_are_rejected(client, db, bank, missing):
    response = client.post(
        URL,
        json=payload(bank, drop=(missing,)),
        headers=auth_headers(hospital_user(db)),
    )
    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"
    assert missing in error_fields(response)


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", ""),
        ("name", "   "),
        ("name", "x" * 256),
        ("address", ""),
        ("city", ""),
        ("latitude", 91),
        ("latitude", -91),
        ("longitude", 181),
        ("longitude", -181),
        ("contact_phone", "abc"),
        ("contact_phone", "123"),
        ("blood_bank_id", "not-a-uuid"),
    ],
)
def test_invalid_values_are_rejected(client, db, bank, field, value):
    response = create(client, hospital_user(db), bank, **{field: value})
    assert response.status_code == 422
    assert field in error_fields(response)
    assert hospital_count(db) == 0


@pytest.mark.parametrize("latitude,longitude", [(90, 180), (-90, -180), (0, 0)])
def test_boundary_coordinates_are_accepted(client, db, bank, latitude, longitude):
    assert (
        create(
            client, hospital_user(db), bank, latitude=latitude, longitude=longitude
        ).status_code
        == 201
    )


def test_an_unknown_blood_bank_is_refused(client, db, bank):
    response = create(client, hospital_user(db), bank, blood_bank_id=str(uuid.uuid4()))
    assert response.status_code == 400
    assert error_code(response) == "BAD_REQUEST"
    assert "not available" in response.json()["error"]["message"]
    assert hospital_count(db) == 0


@pytest.mark.parametrize(
    "bank_options",
    [
        {"approval_status": ApprovalStatus.PENDING},
        {"approval_status": ApprovalStatus.SUSPENDED},
        {"is_active": False},
    ],
    ids=["pending", "suspended", "paused"],
)
def test_a_blood_bank_that_is_not_available_is_refused(client, db, bank, bank_options):
    unavailable = make_blood_bank(db, **bank_options)
    response = create(
        client, hospital_user(db), bank, blood_bank_id=str(unavailable.id)
    )
    assert response.status_code == 400
    assert error_code(response) == "BAD_REQUEST"
    assert hospital_count(db) == 0


# --------------------------------------------------------------------- read


def test_hospital_reads_its_own_profile(client, db, bank):
    user = hospital_user(db)
    make_hospital(
        db,
        user=user,
        blood_bank=bank,
        name="My Hospital",
        approval_status=ApprovalStatus.PENDING,
    )
    response = client.get(URL, headers=auth_headers(user))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["name"] == "My Hospital"
    assert data["blood_bank_id"] == str(bank.id)
    assert data["blood_bank_name"] == "Central Blood Bank"
    assert data["approval_status"] == "pending"


def test_reading_before_creating_a_profile_gives_404(client, db):
    response = client.get(URL, headers=auth_headers(hospital_user(db)))
    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_each_hospital_sees_only_its_own_profile(client, db, bank):
    first, second = hospital_user(db), hospital_user(db)
    make_hospital(db, user=first, blood_bank=bank, name="First Hospital")
    make_hospital(db, user=second, blood_bank=bank, name="Second Hospital")
    assert (
        client.get(URL, headers=auth_headers(first)).json()["data"]["name"]
        == "First Hospital"
    )
    assert (
        client.get(URL, headers=auth_headers(second)).json()["data"]["name"]
        == "Second Hospital"
    )


@pytest.mark.parametrize("approval", [ApprovalStatus.PENDING, ApprovalStatus.SUSPENDED])
def test_pending_and_suspended_hospitals_can_still_read_their_profile(
    client, db, bank, approval
):
    user = hospital_user(db)
    make_hospital(db, user=user, blood_bank=bank, approval_status=approval)
    response = client.get(URL, headers=auth_headers(user))
    assert response.status_code == 200
    assert response.json()["data"]["approval_status"] == approval.value


@pytest.mark.parametrize("role", [UserRole.DONOR, UserRole.BLOOD_BANK, UserRole.ADMIN])
def test_other_roles_cannot_read_a_hospital_profile(client, db, role):
    response = client.get(URL, headers=auth_headers(make_user(db, role)))
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_reading_a_profile_requires_a_token(client, db):
    assert client.get(URL).status_code == 401


# ------------------------------------------------------------------- update


def test_hospital_updates_its_profile(client, db, bank):
    user = hospital_user(db)
    hospital = make_hospital(db, user=user, blood_bank=bank, name="Old Name")
    new_values = payload(
        bank,
        name="Renamed Hospital",
        address="New Street",
        city="Adama",
        latitude=8.54,
        longitude=39.27,
        contact_phone="+251222222222",
    )
    response = client.put(URL, json=new_values, headers=auth_headers(user))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["name"] == "Renamed Hospital"
    assert data["city"] == "Adama"
    assert data["latitude"] == 8.54
    assert data["contact_phone"] == "+251222222222"
    db.refresh(hospital)
    assert hospital.name == "Renamed Hospital"
    assert hospital.address == "New Street"


def test_an_update_never_changes_the_approval_status(client, db, bank):
    user = hospital_user(db)
    hospital = make_hospital(
        db, user=user, blood_bank=bank, approval_status=ApprovalStatus.APPROVED
    )
    response = client.put(
        URL, json=payload(bank, name="Renamed Hospital"), headers=auth_headers(user)
    )
    assert response.status_code == 200
    assert response.json()["data"]["approval_status"] == "approved"
    db.refresh(hospital)
    assert hospital.approval_status == ApprovalStatus.APPROVED


def test_a_pending_hospital_can_update_and_stays_pending(client, db, bank):
    user = hospital_user(db)
    make_hospital(
        db, user=user, blood_bank=bank, approval_status=ApprovalStatus.PENDING
    )
    response = client.put(
        URL, json=payload(bank, name="Renamed Hospital"), headers=auth_headers(user)
    )
    assert response.status_code == 200
    assert response.json()["data"]["approval_status"] == "pending"


def test_updating_before_creating_a_profile_gives_404(client, db, bank):
    response = client.put(
        URL, json=payload(bank), headers=auth_headers(hospital_user(db))
    )
    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_an_update_only_changes_the_callers_own_profile(client, db, bank):
    first, second = hospital_user(db), hospital_user(db)
    make_hospital(db, user=first, blood_bank=bank, name="First Hospital")
    other = make_hospital(db, user=second, blood_bank=bank, name="Second Hospital")
    client.put(
        URL, json=payload(bank, name="First Renamed"), headers=auth_headers(first)
    )
    db.refresh(other)
    assert other.name == "Second Hospital"


@pytest.mark.parametrize("field", ["approval_status", "is_active", "user_id"])
def test_update_rejects_fields_the_client_must_not_set(client, db, bank, field):
    values = {
        "approval_status": "approved",
        "is_active": True,
        "user_id": str(uuid.uuid4()),
    }
    user = hospital_user(db)
    make_hospital(
        db, user=user, blood_bank=bank, approval_status=ApprovalStatus.PENDING
    )
    response = client.put(
        URL, json=payload(bank, **{field: values[field]}), headers=auth_headers(user)
    )
    assert response.status_code == 422
    assert field in error_fields(response)
    assert stored(db, user).approval_status == ApprovalStatus.PENDING


def test_update_needs_every_field(client, db, bank):
    user = hospital_user(db)
    make_hospital(db, user=user, blood_bank=bank)
    response = client.put(
        URL, json=payload(bank, drop=("city",)), headers=auth_headers(user)
    )
    assert response.status_code == 422
    assert "city" in error_fields(response)


def test_update_validates_values_like_create(client, db, bank):
    user = hospital_user(db)
    make_hospital(db, user=user, blood_bank=bank)
    response = client.put(
        URL, json=payload(bank, latitude=91), headers=auth_headers(user)
    )
    assert response.status_code == 422
    assert "latitude" in error_fields(response)


def test_updating_requires_a_token(client, db, bank):
    assert client.put(URL, json=payload(bank)).status_code == 401


@pytest.mark.parametrize("role", [UserRole.DONOR, UserRole.BLOOD_BANK, UserRole.ADMIN])
def test_other_roles_cannot_update_a_hospital_profile(client, db, bank, role):
    response = client.put(
        URL, json=payload(bank), headers=auth_headers(make_user(db, role))
    )
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_a_hospital_can_switch_to_another_available_blood_bank(client, db, bank):
    user = hospital_user(db)
    make_hospital(db, user=user, blood_bank=bank)
    second_bank = make_blood_bank(db, name="Second Blood Bank")
    response = client.put(URL, json=payload(second_bank), headers=auth_headers(user))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["blood_bank_id"] == str(second_bank.id)
    assert data["blood_bank_name"] == "Second Blood Bank"


def test_switching_to_an_unavailable_blood_bank_is_refused(client, db, bank):
    user = hospital_user(db)
    hospital = make_hospital(db, user=user, blood_bank=bank)
    pending_bank = make_blood_bank(db, approval_status=ApprovalStatus.PENDING)
    response = client.put(URL, json=payload(pending_bank), headers=auth_headers(user))
    assert response.status_code == 400
    assert error_code(response) == "BAD_REQUEST"
    db.refresh(hospital)
    assert hospital.blood_bank_id == bank.id


def test_an_unchanged_blood_bank_that_became_unavailable_does_not_block_updates(
    client, db, bank
):
    user = hospital_user(db)
    make_hospital(db, user=user, blood_bank=bank)
    bank.approval_status = (
        ApprovalStatus.SUSPENDED
    )  # suspended after the hospital chose it
    db.commit()
    response = client.put(
        URL, json=payload(bank, name="Renamed Hospital"), headers=auth_headers(user)
    )
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Renamed Hospital"
