import uuid

import pytest
from sqlalchemy import func, select

from app.models.blood_bank import BloodBank
from app.models.enums import ApprovalStatus, UserRole
from tests.factories import auth_headers, make_blood_bank, make_user

URL = "/v1/blood-banks/profile"
PUBLIC_LIST = "/v1/blood-banks"

REQUIRED_FIELDS = ["name", "address", "city", "latitude", "longitude", "contact_phone"]


def payload(drop=(), **overrides) -> dict:
    data = {
        "name": "Ethiopian Red Cross Blood Bank",
        "address": "Churchill Avenue",
        "city": "Addis Ababa",
        "latitude": 9.03,
        "longitude": 38.74,
        "contact_phone": "+251111234567",
    }
    data.update(overrides)
    for key in drop:
        data.pop(key, None)
    return data


def bank_user(db):
    return make_user(db, UserRole.BLOOD_BANK)


def create(client, user, **overrides):
    return client.post(URL, json=payload(**overrides), headers=auth_headers(user))


def error_fields(response) -> list[str]:
    return [item["field"] for item in response.json()["error"]["details"]]


def error_code(response) -> str:
    return response.json()["error"]["code"]


def stored(db, user) -> BloodBank | None:
    return db.scalar(select(BloodBank).where(BloodBank.user_id == user.id))


def bank_count(db) -> int:
    return db.scalar(select(func.count()).select_from(BloodBank))


# ------------------------------------------------------------------- create


def test_blood_bank_creates_its_profile(client, db):
    response = create(client, bank_user(db))
    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["id"]
    assert data["name"] == "Ethiopian Red Cross Blood Bank"
    assert data["city"] == "Addis Ababa"
    assert data["contact_phone"] == "+251111234567"
    assert data["approval_status"] == "pending"
    assert data["is_active"] is True


def test_new_profile_is_pending_and_linked_to_the_user(client, db):
    user = bank_user(db)
    create(client, user)
    bank = stored(db, user)
    assert bank is not None
    assert bank.approval_status == ApprovalStatus.PENDING
    assert bank.is_active is True
    assert bank.name == "Ethiopian Red Cross Blood Bank"


def test_response_does_not_expose_the_owner_account(client, db):
    data = create(client, bank_user(db)).json()["data"]
    assert "user_id" not in data


@pytest.mark.parametrize("field", ["approval_status", "is_active", "user_id", "id"])
def test_fields_the_client_must_not_set_are_rejected(client, db, field):
    values = {
        "approval_status": "approved",
        "is_active": False,
        "user_id": str(uuid.uuid4()),
        "id": str(uuid.uuid4()),
    }
    user = bank_user(db)
    response = create(client, user, **{field: values[field]})
    assert response.status_code == 422
    assert field in error_fields(response)
    assert stored(db, user) is None


def test_a_new_profile_is_not_in_the_public_list(client, db):
    create(client, bank_user(db))
    assert client.get(PUBLIC_LIST).json()["data"]["items"] == []


def test_a_second_profile_is_refused(client, db):
    user = bank_user(db)
    assert create(client, user).status_code == 201
    response = create(client, user, name="Another Name")
    assert response.status_code == 409
    assert error_code(response) == "PROFILE_ALREADY_EXISTS"
    assert bank_count(db) == 1
    assert stored(db, user).name == "Ethiopian Red Cross Blood Bank"


@pytest.mark.parametrize("role", [UserRole.DONOR, UserRole.HOSPITAL, UserRole.ADMIN])
def test_other_roles_cannot_create_a_blood_bank_profile(client, db, role):
    response = create(client, make_user(db, role))
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"
    assert bank_count(db) == 0


def test_creating_a_profile_requires_a_token(client, db):
    response = client.post(URL, json=payload())
    assert response.status_code == 401
    assert error_code(response) == "UNAUTHORIZED"


def test_a_deactivated_user_cannot_create_a_profile(client, db):
    user = make_user(db, UserRole.BLOOD_BANK, is_active=False)
    response = create(client, user)
    assert response.status_code == 403
    assert "deactivated" in response.json()["error"]["message"]
    assert bank_count(db) == 0


def test_text_fields_are_trimmed(client, db):
    data = create(
        client,
        bank_user(db),
        name="  Red Cross  ",
        address="  Bole  ",
        city=" Addis Ababa ",
    ).json()["data"]
    assert data["name"] == "Red Cross"
    assert data["address"] == "Bole"
    assert data["city"] == "Addis Ababa"


def test_the_phone_number_is_cleaned(client, db):
    data = create(client, bank_user(db), contact_phone="+251 111-234-567").json()[
        "data"
    ]
    assert data["contact_phone"] == "+251111234567"


@pytest.mark.parametrize("missing", REQUIRED_FIELDS)
def test_missing_required_fields_are_rejected(client, db, missing):
    response = client.post(
        URL, json=payload(drop=(missing,)), headers=auth_headers(bank_user(db))
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
    ],
)
def test_invalid_values_are_rejected(client, db, field, value):
    response = create(client, bank_user(db), **{field: value})
    assert response.status_code == 422
    assert field in error_fields(response)
    assert bank_count(db) == 0


@pytest.mark.parametrize("latitude,longitude", [(90, 180), (-90, -180), (0, 0)])
def test_boundary_coordinates_are_accepted(client, db, latitude, longitude):
    response = create(client, bank_user(db), latitude=latitude, longitude=longitude)
    assert response.status_code == 201


# --------------------------------------------------------------------- read


def test_blood_bank_reads_its_own_profile(client, db):
    user = bank_user(db)
    make_blood_bank(
        db, user=user, name="My Bank", approval_status=ApprovalStatus.PENDING
    )
    response = client.get(URL, headers=auth_headers(user))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["name"] == "My Bank"
    assert data["contact_phone"] == "+251111234567"
    assert data["approval_status"] == "pending"
    assert data["is_active"] is True


def test_reading_before_creating_a_profile_gives_404(client, db):
    response = client.get(URL, headers=auth_headers(bank_user(db)))
    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_each_bank_sees_only_its_own_profile(client, db):
    first, second = bank_user(db), bank_user(db)
    make_blood_bank(db, user=first, name="First Bank")
    make_blood_bank(db, user=second, name="Second Bank")
    assert (
        client.get(URL, headers=auth_headers(first)).json()["data"]["name"]
        == "First Bank"
    )
    assert (
        client.get(URL, headers=auth_headers(second)).json()["data"]["name"]
        == "Second Bank"
    )


@pytest.mark.parametrize("approval", [ApprovalStatus.PENDING, ApprovalStatus.SUSPENDED])
def test_pending_and_suspended_banks_can_still_read_their_profile(client, db, approval):
    user = bank_user(db)
    make_blood_bank(db, user=user, approval_status=approval)
    response = client.get(URL, headers=auth_headers(user))
    assert response.status_code == 200
    assert response.json()["data"]["approval_status"] == approval.value


@pytest.mark.parametrize("role", [UserRole.DONOR, UserRole.HOSPITAL, UserRole.ADMIN])
def test_other_roles_cannot_read_a_blood_bank_profile(client, db, role):
    response = client.get(URL, headers=auth_headers(make_user(db, role)))
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_reading_a_profile_requires_a_token(client, db):
    assert client.get(URL).status_code == 401


# ------------------------------------------------------------------- update


def test_blood_bank_updates_its_profile(client, db):
    user = bank_user(db)
    bank = make_blood_bank(db, user=user, name="Old Name")
    new_values = payload(
        name="Renamed Bank",
        address="New Street",
        city="Adama",
        latitude=8.54,
        longitude=39.27,
        contact_phone="+251222222222",
    )
    response = client.put(URL, json=new_values, headers=auth_headers(user))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["name"] == "Renamed Bank"
    assert data["city"] == "Adama"
    assert data["latitude"] == 8.54
    assert data["contact_phone"] == "+251222222222"
    db.refresh(bank)
    assert bank.name == "Renamed Bank"
    assert bank.address == "New Street"


def test_an_update_never_changes_approval_or_operating_status(client, db):
    user = bank_user(db)
    bank = make_blood_bank(
        db, user=user, approval_status=ApprovalStatus.APPROVED, is_active=False
    )
    response = client.put(
        URL, json=payload(name="Renamed Bank"), headers=auth_headers(user)
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["approval_status"] == "approved"
    assert data["is_active"] is False
    db.refresh(bank)
    assert bank.approval_status == ApprovalStatus.APPROVED
    assert bank.is_active is False


def test_a_pending_bank_can_update_its_profile_and_stays_pending(client, db):
    user = bank_user(db)
    make_blood_bank(db, user=user, approval_status=ApprovalStatus.PENDING)
    response = client.put(
        URL, json=payload(name="Renamed Bank"), headers=auth_headers(user)
    )
    assert response.status_code == 200
    assert response.json()["data"]["approval_status"] == "pending"


def test_updating_before_creating_a_profile_gives_404(client, db):
    response = client.put(URL, json=payload(), headers=auth_headers(bank_user(db)))
    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_an_update_only_changes_the_callers_own_profile(client, db):
    first, second = bank_user(db), bank_user(db)
    make_blood_bank(db, user=first, name="First Bank")
    other = make_blood_bank(db, user=second, name="Second Bank")
    client.put(URL, json=payload(name="First Renamed"), headers=auth_headers(first))
    db.refresh(other)
    assert other.name == "Second Bank"


@pytest.mark.parametrize("field", ["approval_status", "is_active", "user_id"])
def test_update_rejects_fields_the_client_must_not_set(client, db, field):
    values = {
        "approval_status": "approved",
        "is_active": False,
        "user_id": str(uuid.uuid4()),
    }
    user = bank_user(db)
    make_blood_bank(db, user=user, approval_status=ApprovalStatus.PENDING)
    response = client.put(
        URL, json=payload(**{field: values[field]}), headers=auth_headers(user)
    )
    assert response.status_code == 422
    assert field in error_fields(response)
    assert stored(db, user).approval_status == ApprovalStatus.PENDING


def test_update_needs_every_field(client, db):
    user = bank_user(db)
    make_blood_bank(db, user=user)
    response = client.put(URL, json=payload(drop=("city",)), headers=auth_headers(user))
    assert response.status_code == 422
    assert "city" in error_fields(response)


def test_update_validates_values_like_create(client, db):
    user = bank_user(db)
    make_blood_bank(db, user=user)
    response = client.put(URL, json=payload(latitude=91), headers=auth_headers(user))
    assert response.status_code == 422
    assert "latitude" in error_fields(response)


def test_updating_requires_a_token(client, db):
    assert client.put(URL, json=payload()).status_code == 401


@pytest.mark.parametrize("role", [UserRole.DONOR, UserRole.HOSPITAL, UserRole.ADMIN])
def test_other_roles_cannot_update_a_blood_bank_profile(client, db, role):
    response = client.put(
        URL, json=payload(), headers=auth_headers(make_user(db, role))
    )
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_an_approved_banks_new_name_shows_in_the_public_list(client, db):
    user = bank_user(db)
    make_blood_bank(db, user=user, name="Old Name")
    client.put(URL, json=payload(name="Renamed Bank"), headers=auth_headers(user))
    names = [item["name"] for item in client.get(PUBLIC_LIST).json()["data"]["items"]]
    assert names == ["Renamed Bank"]
