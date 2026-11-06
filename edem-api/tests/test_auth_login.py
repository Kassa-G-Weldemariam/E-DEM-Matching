import uuid
from datetime import timedelta

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select

from app.core.security import (
    TokenType,
    create_access_token,
    decode_token,
    verify_password,
)
from app.models.user import User

PASSWORD = "S3cure-password"
EMAIL = "hospital@edem-demo.org"


def register(client, email=EMAIL, password=PASSWORD, role="hospital") -> dict:
    response = client.post(
        "/v1/auth/register", json={"email": email, "password": password, "role": role}
    )
    assert response.status_code == 201
    return response.json()["data"]


def login(client, email=EMAIL, password=PASSWORD):
    return client.post("/v1/auth/login", json={"email": email, "password": password})


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def tokens_for(client) -> dict:
    register(client)
    return login(client).json()["data"]


def get_user(db, email=EMAIL) -> User:
    return db.scalar(select(User).where(User.email == email))


def error_code(response) -> str:
    return response.json()["error"]["code"]


# ---------------------------------------------------------------- login


def test_login_returns_tokens_and_the_user(client):
    register(client)
    response = login(client)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["access_token"] and data["refresh_token"]
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0
    assert data["user"]["email"] == EMAIL
    assert data["user"]["role"] == "hospital"
    assert "password" not in data["user"] and "password_hash" not in data["user"]


def test_login_tokens_belong_to_the_user_and_have_the_right_type(client):
    registered = register(client)
    data = login(client).json()["data"]
    access = decode_token(data["access_token"], TokenType.ACCESS)
    refresh = decode_token(data["refresh_token"], TokenType.REFRESH)
    assert str(access.user_id) == registered["id"]
    assert str(refresh.user_id) == registered["id"]


def test_login_email_is_case_insensitive(client):
    register(client)
    assert login(client, email="  HOSPITAL@Edem-Demo.org ").status_code == 200


def test_wrong_password_is_rejected(client):
    register(client)
    response = login(client, password="wrong-password")
    assert response.status_code == 401
    assert error_code(response) == "UNAUTHORIZED"


def test_unknown_email_looks_the_same_as_a_wrong_password(client):
    register(client)
    wrong_password = login(client, password="wrong-password")
    unknown_email = login(client, email="nobody@edem-demo.org")
    assert unknown_email.status_code == wrong_password.status_code == 401
    assert unknown_email.json()["error"] == wrong_password.json()["error"]


def test_deactivated_account_cannot_log_in(client, db):
    register(client)
    get_user(db).is_active = False
    db.commit()
    response = login(client)
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_login_upgrades_a_weak_password_hash(client, db):
    register(client)
    user = get_user(db)
    weak_hash = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
    user.password_hash = weak_hash
    db.commit()

    assert login(client).status_code == 200

    db.refresh(user)
    assert user.password_hash != weak_hash
    assert verify_password(PASSWORD, user.password_hash) is True


def test_login_rejects_unknown_fields(client):
    register(client)
    response = client.post(
        "/v1/auth/login", json={"email": EMAIL, "password": PASSWORD, "role": "admin"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize("missing", ["email", "password"])
def test_login_requires_email_and_password(client, missing):
    body = {"email": EMAIL, "password": PASSWORD}
    body.pop(missing)
    assert client.post("/v1/auth/login", json=body).status_code == 422


# -------------------------------------------------------------- refresh


def test_refresh_gives_a_working_access_token(client):
    tokens = tokens_for(client)
    response = client.post(
        "/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 200
    new_access = response.json()["data"]["access_token"]
    assert client.get("/v1/auth/me", headers=bearer(new_access)).status_code == 200


def test_access_token_cannot_be_used_to_refresh(client):
    tokens = tokens_for(client)
    response = client.post(
        "/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}
    )
    assert response.status_code == 401


def test_garbage_refresh_token_is_rejected(client):
    response = client.post("/v1/auth/refresh", json={"refresh_token": "not-a-token"})
    assert response.status_code == 401
    assert error_code(response) == "UNAUTHORIZED"


def test_refresh_for_a_deactivated_account_is_forbidden(client, db):
    tokens = tokens_for(client)
    get_user(db).is_active = False
    db.commit()
    response = client.post(
        "/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 403


def test_refresh_for_a_deleted_user_is_rejected(client, db):
    tokens = tokens_for(client)
    db.delete(get_user(db))
    db.commit()
    response = client.post(
        "/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 401


def test_refresh_requires_the_token_field(client):
    assert client.post("/v1/auth/refresh", json={}).status_code == 422


# ------------------------------------------------------------------- me


def test_me_returns_the_current_user(client):
    tokens = tokens_for(client)
    response = client.get("/v1/auth/me", headers=bearer(tokens["access_token"]))
    assert response.status_code == 200
    assert response.json()["data"]["email"] == EMAIL


def test_me_requires_a_token(client):
    response = client.get("/v1/auth/me")
    assert response.status_code == 401
    assert error_code(response) == "UNAUTHORIZED"


def test_refresh_token_is_not_accepted_as_an_access_token(client):
    tokens = tokens_for(client)
    assert (
        client.get("/v1/auth/me", headers=bearer(tokens["refresh_token"])).status_code
        == 401
    )


def test_expired_access_token_is_rejected(client):
    registered = register(client)
    expired = create_access_token(
        uuid.UUID(registered["id"]), expires_delta=timedelta(seconds=-5)
    )
    assert client.get("/v1/auth/me", headers=bearer(expired)).status_code == 401


def test_garbage_bearer_token_is_rejected(client):
    assert client.get("/v1/auth/me", headers=bearer("garbage")).status_code == 401


def test_a_non_bearer_authorization_scheme_is_rejected(client):
    response = client.get(
        "/v1/auth/me", headers={"Authorization": "Basic dXNlcjpwYXNz"}
    )
    assert response.status_code == 401


def test_deactivated_user_is_forbidden_even_with_a_valid_token(client, db):
    tokens = tokens_for(client)
    get_user(db).is_active = False
    db.commit()
    response = client.get("/v1/auth/me", headers=bearer(tokens["access_token"]))
    assert response.status_code == 403


def test_token_for_a_user_that_does_not_exist_is_rejected(client):
    ghost = create_access_token(uuid.uuid4())
    assert client.get("/v1/auth/me", headers=bearer(ghost)).status_code == 401


# ------------------------------------------------------ change password


def change(client, token, current=PASSWORD, new="Br4nd-new-password"):
    return client.post(
        "/v1/auth/change-password",
        json={"current_password": current, "new_password": new},
        headers=bearer(token),
    )


def test_change_password_replaces_the_old_one(client):
    tokens = tokens_for(client)
    assert change(client, tokens["access_token"]).status_code == 200
    assert login(client, password=PASSWORD).status_code == 401
    assert login(client, password="Br4nd-new-password").status_code == 200


def test_change_password_needs_the_correct_current_password(client):
    tokens = tokens_for(client)
    response = change(client, tokens["access_token"], current="not-my-password")
    assert response.status_code == 400
    assert error_code(response) == "INVALID_CURRENT_PASSWORD"
    assert login(client).status_code == 200  # the password did not change


def test_new_password_must_differ_from_the_current_one(client):
    tokens = tokens_for(client)
    response = change(client, tokens["access_token"], new=PASSWORD)
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "new_password"


@pytest.mark.parametrize("length", [7, 129])
def test_new_password_must_respect_the_length_limits(client, length):
    tokens = tokens_for(client)
    assert change(client, tokens["access_token"], new="a" * length).status_code == 422


def test_change_password_requires_a_token(client):
    response = client.post(
        "/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "Br4nd-new-password"},
    )
    assert response.status_code == 401
