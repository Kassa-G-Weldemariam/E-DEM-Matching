"""End-to-end onboarding: real registration, real login and real tokens, all over HTTP."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.api.deps import ApprovedBloodBank, ApprovedHospital
from app.models.blood_bank import BloodBank
from app.models.enums import ApprovalStatus
from app.models.hospital import Hospital
from app.models.user import User
from app.services.admin import create_admin

PASSWORD = "S3cure-password"
ADMIN_PASSWORD = "Admin-S3cure-pass"

BANK_NAME = "Central Blood Bank"
HOSPITAL_NAME = "Tikur Anbessa Hospital"

BANK_URL = "/v1/blood-banks/profile"
HOSPITAL_URL = "/v1/hospitals/profile"
DONOR_URL = "/v1/donors/profile"
LIST_URL = "/v1/blood-banks"
LOGIN_URL = "/v1/auth/login"

EMAILS = {
    "bank": "bank@edem-demo.org",
    "hospital": "hospital@edem-demo.org",
    "donor": "donor@edem-demo.org",
    "admin": "admin@edem-demo.org",
}
PROFILE_URLS = {"bank": BANK_URL, "hospital": HOSPITAL_URL, "donor": DONOR_URL}


# ------------------------------------------------------------------ helpers


def _approved_hospital(hospital: ApprovedHospital):
    return {"id": str(hospital.id), "name": hospital.name}


def _approved_blood_bank(blood_bank: ApprovedBloodBank):
    return {"id": str(blood_bank.id), "name": blood_bank.name}


@pytest.fixture()
def routes(app, client):
    """The test client, plus throw-away action routes that use the approval guards."""
    app.add_api_route("/_test/approved-hospital", _approved_hospital, methods=["GET"])
    app.add_api_route(
        "/_test/approved-blood-bank", _approved_blood_bank, methods=["GET"]
    )
    return client


def sign_up(client, role: str, email: str, phone: str | None = None) -> dict:
    """Register and log in through the real endpoints. Returns the Authorization header."""
    body = {"email": email, "password": PASSWORD, "role": role}
    if phone:
        body["phone"] = phone
    assert client.post("/v1/auth/register", json=body).status_code == 201
    login = client.post(LOGIN_URL, json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['data']['access_token']}"}


def bank_body() -> dict:
    return {
        "name": BANK_NAME,
        "address": "Churchill Avenue",
        "city": "Addis Ababa",
        "latitude": 9.03,
        "longitude": 38.74,
        "contact_phone": "+251111234567",
    }


def hospital_body(bank_id: str) -> dict:
    return {
        "blood_bank_id": bank_id,
        "name": HOSPITAL_NAME,
        "address": "Churchill Avenue",
        "city": "Addis Ababa",
        "latitude": 9.03,
        "longitude": 38.74,
        "contact_phone": "+251111234568",
    }


def donor_body(bank_id: str) -> dict:
    return {
        "blood_bank_id": bank_id,
        "full_name": "Abebe Kebede",
        "blood_type": "O+",
        "gender": "male",
        "date_of_birth": "1995-04-12",
        "weight_kg": 68.5,
        "latitude": 9.03,
        "longitude": 38.74,
    }


def set_approval(db, model, name: str, status: ApprovalStatus) -> None:
    """What an Admin endpoint will do in Phase 5."""
    row = db.scalar(select(model).where(model.name == name))
    row.approval_status = status
    db.commit()


def public_items(client) -> list[dict]:
    return client.get(LIST_URL).json()["data"]["items"]


def error_code(response) -> str:
    return response.json()["error"]["code"]


@pytest.fixture()
def world(routes, db):
    """One of each role, fully onboarded through the real endpoints."""
    client = routes
    bank = sign_up(client, "blood_bank", EMAILS["bank"])
    bank_id = client.post(BANK_URL, json=bank_body(), headers=bank).json()["data"]["id"]
    set_approval(db, BloodBank, BANK_NAME, ApprovalStatus.APPROVED)

    hospital = sign_up(client, "hospital", EMAILS["hospital"])
    assert (
        client.post(
            HOSPITAL_URL, json=hospital_body(bank_id), headers=hospital
        ).status_code
        == 201
    )
    set_approval(db, Hospital, HOSPITAL_NAME, ApprovalStatus.APPROVED)

    donor = sign_up(client, "donor", EMAILS["donor"], phone="+251911234567")
    assert (
        client.post(DONOR_URL, json=donor_body(bank_id), headers=donor).status_code
        == 201
    )

    create_admin(db, EMAILS["admin"], ADMIN_PASSWORD)
    admin_login = client.post(
        LOGIN_URL, json={"email": EMAILS["admin"], "password": ADMIN_PASSWORD}
    )
    assert admin_login.status_code == 200
    admin = {"Authorization": f"Bearer {admin_login.json()['data']['access_token']}"}

    return SimpleNamespace(
        client=client,
        bank=bank,
        hospital=hospital,
        donor=donor,
        admin=admin,
        bank_id=bank_id,
    )


# -------------------------------------------------------- the full journey


def test_full_onboarding_flow(routes, db):
    client = routes

    # 1. A blood bank signs up and creates its profile.
    bank = sign_up(client, "blood_bank", EMAILS["bank"])
    created = client.post(BANK_URL, json=bank_body(), headers=bank)
    assert created.status_code == 201
    bank_id = created.json()["data"]["id"]
    assert created.json()["data"]["approval_status"] == "pending"

    # 2. While it is pending it is hidden from the public list and cannot use action endpoints.
    assert public_items(client) == []
    blocked = client.get("/_test/approved-blood-bank", headers=bank)
    assert blocked.status_code == 403
    assert error_code(blocked) == "ACCOUNT_NOT_APPROVED"

    # 3. A hospital and a donor cannot choose a bank that has not been approved.
    hospital = sign_up(client, "hospital", EMAILS["hospital"])
    refused_hospital = client.post(
        HOSPITAL_URL, json=hospital_body(bank_id), headers=hospital
    )
    assert refused_hospital.status_code == 400
    assert error_code(refused_hospital) == "BAD_REQUEST"

    donor = sign_up(client, "donor", EMAILS["donor"], phone="+251911234567")
    refused_donor = client.post(DONOR_URL, json=donor_body(bank_id), headers=donor)
    assert refused_donor.status_code == 400
    assert error_code(refused_donor) == "BAD_REQUEST"

    # 4. An Admin approves the blood bank. Now it is listed and can act.
    set_approval(db, BloodBank, BANK_NAME, ApprovalStatus.APPROVED)
    assert [item["id"] for item in public_items(client)] == [bank_id]
    assert client.get("/_test/approved-blood-bank", headers=bank).json() == {
        "id": bank_id,
        "name": BANK_NAME,
    }

    # 5. The hospital and the donor can now sign up under it.
    hospital_profile = client.post(
        HOSPITAL_URL, json=hospital_body(bank_id), headers=hospital
    )
    assert hospital_profile.status_code == 201
    hospital_id = hospital_profile.json()["data"]["id"]
    assert hospital_profile.json()["data"]["approval_status"] == "pending"
    assert hospital_profile.json()["data"]["blood_bank_name"] == BANK_NAME

    donor_profile = client.post(DONOR_URL, json=donor_body(bank_id), headers=donor)
    assert donor_profile.status_code == 201
    assert donor_profile.json()["data"]["verification_status"] == "unverified"
    assert donor_profile.json()["data"]["is_available"] is True
    assert donor_profile.json()["data"]["blood_bank_name"] == BANK_NAME

    # 6. The hospital is blocked from action endpoints until an Admin approves it.
    still_blocked = client.get("/_test/approved-hospital", headers=hospital)
    assert still_blocked.status_code == 403
    assert error_code(still_blocked) == "ACCOUNT_NOT_APPROVED"
    set_approval(db, Hospital, HOSPITAL_NAME, ApprovalStatus.APPROVED)
    assert client.get("/_test/approved-hospital", headers=hospital).json() == {
        "id": hospital_id,
        "name": HOSPITAL_NAME,
    }

    # 7. The donor switches availability off and sees it on their profile.
    patched = client.patch(
        "/v1/donors/availability", json={"is_available": False}, headers=donor
    )
    assert patched.status_code == 200
    profile = client.get(DONOR_URL, headers=donor).json()["data"]
    assert profile["is_available"] is False
    assert profile["verification_status"] == "unverified"


# ------------------------------------------------------------ role boundaries


@pytest.mark.parametrize("role", ["bank", "hospital", "donor", "admin"])
@pytest.mark.parametrize("endpoint", list(PROFILE_URLS))
def test_each_role_can_only_use_its_own_profile_endpoint(world, role, endpoint):
    response = world.client.get(PROFILE_URLS[endpoint], headers=getattr(world, role))
    if role == endpoint:
        assert response.status_code == 200
    else:
        assert response.status_code == 403
        assert error_code(response) == "FORBIDDEN"


def test_the_admin_account_works_end_to_end(world):
    response = world.client.get("/v1/auth/me", headers=world.admin)
    assert response.status_code == 200
    assert response.json()["data"]["role"] == "admin"


def test_hospital_and_donor_point_at_the_same_blood_bank(world):
    hospital = world.client.get(HOSPITAL_URL, headers=world.hospital).json()["data"]
    donor = world.client.get(DONOR_URL, headers=world.donor).json()["data"]
    assert hospital["blood_bank_id"] == donor["blood_bank_id"] == world.bank_id
    assert hospital["blood_bank_name"] == donor["blood_bank_name"] == BANK_NAME


# ----------------------------------------------------------------- suspension


def test_a_suspended_blood_bank_leaves_the_public_list(world, db):
    assert [item["id"] for item in public_items(world.client)] == [world.bank_id]
    set_approval(db, BloodBank, BANK_NAME, ApprovalStatus.SUSPENDED)
    assert public_items(world.client) == []


def test_nobody_new_can_choose_a_suspended_blood_bank(world, db):
    set_approval(db, BloodBank, BANK_NAME, ApprovalStatus.SUSPENDED)

    new_hospital = sign_up(world.client, "hospital", "second-hospital@edem-demo.org")
    hospital_response = world.client.post(
        HOSPITAL_URL, json=hospital_body(world.bank_id), headers=new_hospital
    )
    assert hospital_response.status_code == 400

    new_donor = sign_up(
        world.client, "donor", "second-donor@edem-demo.org", phone="+251911234500"
    )
    donor_response = world.client.post(
        DONOR_URL, json=donor_body(world.bank_id), headers=new_donor
    )
    assert donor_response.status_code == 400


def test_existing_hospital_and_donor_keep_their_profiles_when_their_bank_is_suspended(
    world, db
):
    set_approval(db, BloodBank, BANK_NAME, ApprovalStatus.SUSPENDED)
    hospital = world.client.get(HOSPITAL_URL, headers=world.hospital)
    donor = world.client.get(DONOR_URL, headers=world.donor)
    assert hospital.status_code == donor.status_code == 200
    assert hospital.json()["data"]["blood_bank_id"] == world.bank_id
    assert donor.json()["data"]["blood_bank_id"] == world.bank_id


def test_a_suspended_blood_bank_can_see_its_status_but_not_act(world, db):
    set_approval(db, BloodBank, BANK_NAME, ApprovalStatus.SUSPENDED)
    profile = world.client.get(BANK_URL, headers=world.bank)
    assert profile.status_code == 200
    assert profile.json()["data"]["approval_status"] == "suspended"

    action = world.client.get("/_test/approved-blood-bank", headers=world.bank)
    assert action.status_code == 403
    assert error_code(action) == "ACCOUNT_NOT_APPROVED"
    assert "suspended" in action.json()["error"]["message"]


def test_a_suspended_hospital_can_see_its_status_but_not_act(world, db):
    set_approval(db, Hospital, HOSPITAL_NAME, ApprovalStatus.SUSPENDED)
    profile = world.client.get(HOSPITAL_URL, headers=world.hospital)
    assert profile.status_code == 200
    assert profile.json()["data"]["approval_status"] == "suspended"

    action = world.client.get("/_test/approved-hospital", headers=world.hospital)
    assert action.status_code == 403
    assert error_code(action) == "ACCOUNT_NOT_APPROVED"


# ------------------------------------------------------------- token flows


def test_a_refreshed_access_token_works_on_a_profile_endpoint(world):
    login = world.client.post(
        LOGIN_URL, json={"email": EMAILS["donor"], "password": PASSWORD}
    )
    refresh_token = login.json()["data"]["refresh_token"]

    refreshed = world.client.post(
        "/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refreshed.status_code == 200
    new_access = refreshed.json()["data"]["access_token"]

    profile = world.client.get(
        DONOR_URL, headers={"Authorization": f"Bearer {new_access}"}
    )
    assert profile.status_code == 200


@pytest.mark.parametrize("role", ["bank", "hospital", "donor"])
def test_a_deactivated_user_is_locked_out_of_their_profile(world, db, role):
    user = db.scalar(select(User).where(User.email == EMAILS[role]))
    user.is_active = False
    db.commit()
    response = world.client.get(PROFILE_URLS[role], headers=getattr(world, role))
    assert response.status_code == 403
    assert "deactivated" in response.json()["error"]["message"]


def test_a_donor_can_change_their_password_and_still_reach_their_profile(world):
    changed = world.client.post(
        "/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "Br4nd-new-password"},
        headers=world.donor,
    )
    assert changed.status_code == 200

    assert (
        world.client.post(
            LOGIN_URL, json={"email": EMAILS["donor"], "password": PASSWORD}
        ).status_code
        == 401
    )
    login = world.client.post(
        LOGIN_URL, json={"email": EMAILS["donor"], "password": "Br4nd-new-password"}
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
    assert world.client.get(DONOR_URL, headers=headers).status_code == 200
