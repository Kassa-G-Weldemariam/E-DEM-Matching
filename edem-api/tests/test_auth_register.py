import pytest
from sqlalchemy import func, select

from app.core.security import verify_password
from app.models.user import User

URL = "/v1/auth/register"
PASSWORD = "S3cure-password"


def payload(drop=(), **overrides):
    data = {
        "email": "donor@edem-demo.org",
        "password": PASSWORD,
        "role": "donor",
        "phone": "+251911234567",
    }
    data.update(overrides)
    for key in drop:
        data.pop(key, None)
    return data


def user_count(db) -> int:
    return db.scalar(select(func.count()).select_from(User))


def error_fields(response) -> list[str]:
    return [item["field"] for item in response.json()["error"]["details"]]


def test_donor_registers_and_gets_the_user_back(client):
    response = client.post(URL, json=payload())
    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["data"]["email"] == "donor@edem-demo.org"
    assert body["data"]["role"] == "donor"
    assert body["data"]["is_active"] is True
    assert body["data"]["id"]


def test_response_never_contains_password_data(client):
    data = client.post(URL, json=payload()).json()["data"]
    assert "password" not in data
    assert "password_hash" not in data


def test_password_is_stored_hashed(client, db):
    client.post(URL, json=payload())
    user = db.scalar(select(User).where(User.email == "donor@edem-demo.org"))
    assert user.password_hash != PASSWORD
    assert user.password_hash.startswith("$argon2")
    assert verify_password(PASSWORD, user.password_hash) is True


def test_password_with_spaces_is_kept_exactly(client, db):
    spaced = "  spaced password  "
    client.post(URL, json=payload(password=spaced))
    user = db.scalar(select(User).where(User.email == "donor@edem-demo.org"))
    assert verify_password(spaced, user.password_hash) is True


def test_email_is_trimmed_and_lowercased(client, db):
    response = client.post(URL, json=payload(email="  Donor@EDEM-Demo.org "))
    assert response.status_code == 201
    assert response.json()["data"]["email"] == "donor@edem-demo.org"


def test_duplicate_email_is_rejected_even_with_different_case(client, db):
    assert client.post(URL, json=payload()).status_code == 201
    response = client.post(URL, json=payload(email="DONOR@edem-demo.org"))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"
    assert user_count(db) == 1


def test_admin_cannot_be_created_through_registration(client, db):
    response = client.post(URL, json=payload(role="admin"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "role" in error_fields(response)
    assert user_count(db) == 0


@pytest.mark.parametrize("field", ["is_admin", "is_active"])
def test_unknown_fields_are_rejected(client, db, field):
    response = client.post(URL, json=payload(**{field: True}))
    assert response.status_code == 422
    assert field in error_fields(response)
    assert user_count(db) == 0


@pytest.mark.parametrize("role", ["hospital", "blood_bank"])
def test_hospital_and_blood_bank_can_register_without_a_phone(client, role):
    response = client.post(URL, json=payload(role=role, drop=("phone",)))
    assert response.status_code == 201
    assert response.json()["data"]["phone"] is None


def test_donor_must_give_a_phone_number(client, db):
    response = client.post(URL, json=payload(drop=("phone",)))
    assert response.status_code == 422
    assert "phone" in error_fields(response)
    assert user_count(db) == 0


def test_phone_is_cleaned(client):
    response = client.post(URL, json=payload(phone="+251 911-234-567"))
    assert response.status_code == 201
    assert response.json()["data"]["phone"] == "+251911234567"


@pytest.mark.parametrize("phone", ["abc", "123"])
def test_invalid_phone_is_rejected(client, phone):
    response = client.post(URL, json=payload(phone=phone))
    assert response.status_code == 422
    assert "phone" in error_fields(response)


@pytest.mark.parametrize("length", [7, 129])
def test_password_outside_the_length_limits_is_rejected(client, length):
    response = client.post(URL, json=payload(password="a" * length))
    assert response.status_code == 422
    assert "password" in error_fields(response)


@pytest.mark.parametrize("length", [8, 128])
def test_password_at_the_length_limits_is_accepted(client, length):
    response = client.post(URL, json=payload(password="a" * length))
    assert response.status_code == 201


@pytest.mark.parametrize("email", ["not-an-email", "a@b"])
def test_invalid_email_is_rejected(client, email):
    response = client.post(URL, json=payload(email=email))
    assert response.status_code == 422
    assert "email" in error_fields(response)


@pytest.mark.parametrize("missing", ["email", "password", "role"])
def test_missing_required_fields_are_rejected(client, missing):
    response = client.post(URL, json=payload(drop=(missing,)))
    assert response.status_code == 422
    assert missing in error_fields(response)