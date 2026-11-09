import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models.device_token import DeviceToken
from app.models.enums import DevicePlatform, UserRole
from app.schemas.device import DeviceRegisterRequest
from app.services.devices import MAX_DEVICES_PER_USER, register_device
from tests.factories import auth_headers, make_device, make_user

URL = "/v1/devices"
BASE = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)


def token(number: int = 1) -> str:
    return f"device-token-{number:03d}-" + "x" * 40


def post(client, user, **body):
    return client.post(URL, json={"token": token(), **body}, headers=auth_headers(user))


def donor(db):
    return make_user(db, UserRole.DONOR)


def error_fields(response) -> list[str]:
    return [item["field"] for item in response.json()["error"]["details"]]


def error_code(response) -> str:
    return response.json()["error"]["code"]


def devices_of(db, user) -> list[DeviceToken]:
    return list(db.scalars(select(DeviceToken).where(DeviceToken.user_id == user.id)))


def device_count(db) -> int:
    return db.scalar(select(func.count()).select_from(DeviceToken))


def register(db, user, number, when=None, **extra):
    return register_device(
        db, user, DeviceRegisterRequest(token=token(number), **extra), now=when
    )


# =================================================================== POST


def test_a_user_registers_a_device(client, db):
    response = post(client, donor(db), platform="android")
    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["data"]["id"]
    assert body["data"]["platform"] == "android"


def test_the_device_is_stored_for_the_user(client, db):
    user = donor(db)
    post(client, user, platform="ios")
    [device] = devices_of(db, user)
    assert device.token == token()
    assert device.platform == DevicePlatform.IOS


def test_the_response_never_contains_the_token(client, db):
    response = post(client, donor(db), platform="android")
    assert set(response.json()["data"]) == {
        "id",
        "platform",
        "created_at",
        "updated_at",
    }
    assert token() not in response.text


def test_registering_the_same_token_again_updates_instead_of_duplicating(client, db):
    user = donor(db)
    first = post(client, user)
    second = post(client, user)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["data"]["id"] == first.json()["data"]["id"]
    assert device_count(db) == 1


def test_the_platform_is_optional(client, db):
    response = post(client, donor(db))
    assert response.status_code == 201
    assert response.json()["data"]["platform"] is None


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_known_platforms_are_accepted(client, db, platform):
    assert (
        post(client, donor(db), platform=platform).json()["data"]["platform"]
        == platform
    )


def test_an_unknown_platform_is_rejected(client, db):
    response = post(client, donor(db), platform="windows")
    assert response.status_code == 422
    assert "platform" in error_fields(response)
    assert device_count(db) == 0


def test_a_token_moves_to_the_new_user_when_a_phone_changes_hands(client, db):
    first, second = donor(db), donor(db)
    assert post(client, first).status_code == 201
    assert post(client, second).status_code == 200  # same phone, different person
    assert devices_of(db, first) == []
    assert [device.token for device in devices_of(db, second)] == [token()]
    assert device_count(db) == 1


def test_the_token_is_trimmed(client, db):
    user = donor(db)
    post(client, user, token="  " + token() + "  ")
    assert devices_of(db, user)[0].token == token()


@pytest.mark.parametrize(
    "bad_token",
    ["x" * 19, "x" * 513, "abc def " + "x" * 20, "", " " * 25],
    ids=["too short", "too long", "inner space", "empty", "blank"],
)
def test_invalid_tokens_are_rejected(client, db, bad_token):
    response = post(client, donor(db), token=bad_token)
    assert response.status_code == 422
    assert "token" in error_fields(response)
    assert device_count(db) == 0


@pytest.mark.parametrize("length", [20, 512])
def test_tokens_at_the_length_limits_are_accepted(client, db, length):
    assert post(client, donor(db), token="x" * length).status_code == 201


def test_the_token_is_required(client, db):
    response = client.post(
        URL, json={"platform": "android"}, headers=auth_headers(donor(db))
    )
    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"
    assert "token" in error_fields(response)


@pytest.mark.parametrize("field", ["user_id", "id", "created_at"])
def test_fields_the_client_must_not_set_are_rejected(client, db, field):
    values = {
        "user_id": str(uuid.uuid4()),
        "id": str(uuid.uuid4()),
        "created_at": "2030-01-01T00:00:00Z",
    }
    response = post(client, donor(db), **{field: values[field]})
    assert response.status_code == 422
    assert field in error_fields(response)
    assert device_count(db) == 0


@pytest.mark.parametrize("role", list(UserRole))
def test_every_role_can_register_a_device(client, db, role):
    assert post(client, make_user(db, role)).status_code == 201


def test_registering_requires_a_login(client, db):
    response = client.post(URL, json={"token": token()})
    assert response.status_code == 401
    assert error_code(response) == "UNAUTHORIZED"


def test_a_deactivated_user_cannot_register(client, db):
    response = post(client, make_user(db, UserRole.DONOR, is_active=False))
    assert response.status_code == 403
    assert "deactivated" in response.json()["error"]["message"]
    assert device_count(db) == 0


def test_one_user_can_have_several_devices(client, db):
    user = donor(db)
    post(client, user, token=token(1))
    post(client, user, token=token(2))
    assert len(devices_of(db, user)) == 2


# ================================================================ service


def test_a_new_device_is_reported_as_created_and_an_existing_one_is_not(db):
    user = donor(db)
    _, first_time = register(db, user, 1)
    _, second_time = register(db, user, 1)
    assert first_time is True
    assert second_time is False


def test_a_new_registration_stores_the_time(db):
    device, _ = register(db, donor(db), 1, BASE)
    assert device.created_at == BASE
    assert device.updated_at == BASE


def test_registering_again_refreshes_updated_at_but_not_created_at(db):
    user = donor(db)
    register(db, user, 1, BASE)
    device, _ = register(db, user, 1, BASE + timedelta(hours=3))
    assert device.created_at == BASE
    assert device.updated_at == BASE + timedelta(hours=3)


def test_the_oldest_devices_are_dropped_beyond_the_limit(db):
    user = donor(db)
    for number in range(1, MAX_DEVICES_PER_USER + 4):
        register(db, user, number, BASE + timedelta(minutes=number))
    tokens = {device.token for device in devices_of(db, user)}
    assert len(tokens) == MAX_DEVICES_PER_USER
    assert all(token(number) not in tokens for number in (1, 2, 3))
    assert all(token(number) in tokens for number in range(4, MAX_DEVICES_PER_USER + 4))


def test_the_device_being_registered_is_always_kept(db):
    user = donor(db)
    for number in range(1, MAX_DEVICES_PER_USER + 1):
        register(db, user, number, BASE + timedelta(minutes=number))
    register(db, user, 99, BASE)  # an older timestamp than all the others
    tokens = {device.token for device in devices_of(db, user)}
    assert len(tokens) == MAX_DEVICES_PER_USER
    assert token(99) in tokens
    assert token(1) not in tokens  # the least recently used one went instead


def test_the_limit_applies_per_user(db):
    busy, quiet = donor(db), donor(db)
    for number in range(1, MAX_DEVICES_PER_USER + 1):
        make_device(db, user=quiet, token=token(100 + number))
    for number in range(1, MAX_DEVICES_PER_USER + 2):
        register(db, busy, number, BASE + timedelta(minutes=number))
    assert len(devices_of(db, quiet)) == MAX_DEVICES_PER_USER
    assert len(devices_of(db, busy)) == MAX_DEVICES_PER_USER


def test_the_platform_is_kept_when_a_later_registration_leaves_it_out(db):
    user = donor(db)
    register(db, user, 1, BASE, platform=DevicePlatform.ANDROID)
    device, _ = register(db, user, 1, BASE + timedelta(minutes=1))
    assert device.platform == DevicePlatform.ANDROID


def test_the_platform_can_be_updated(db):
    user = donor(db)
    register(db, user, 1, BASE, platform=DevicePlatform.ANDROID)
    device, _ = register(
        db, user, 1, BASE + timedelta(minutes=1), platform=DevicePlatform.IOS
    )
    assert device.platform == DevicePlatform.IOS


# ================================================================ DELETE


def test_a_user_removes_their_own_device(client, db):
    user = donor(db)
    device = make_device(db, user=user)
    response = client.delete(f"{URL}/{device.id}", headers=auth_headers(user))
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert device_count(db) == 0


def test_removing_a_device_leaves_the_others(client, db):
    user = donor(db)
    keep = make_device(db, user=user)
    remove = make_device(db, user=user)
    client.delete(f"{URL}/{remove.id}", headers=auth_headers(user))
    assert [device.id for device in devices_of(db, user)] == [keep.id]


def test_another_users_device_cannot_be_removed(client, db):
    owner, intruder = donor(db), donor(db)
    device = make_device(db, user=owner)
    response = client.delete(f"{URL}/{device.id}", headers=auth_headers(intruder))
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"
    assert device_count(db) == 1


def test_an_unknown_device_gives_404(client, db):
    response = client.delete(f"{URL}/{uuid.uuid4()}", headers=auth_headers(donor(db)))
    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_a_malformed_device_id_gives_422(client, db):
    response = client.delete(f"{URL}/not-a-uuid", headers=auth_headers(donor(db)))
    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_removing_the_same_device_twice_gives_404_the_second_time(client, db):
    user = donor(db)
    device = make_device(db, user=user)
    assert (
        client.delete(f"{URL}/{device.id}", headers=auth_headers(user)).status_code
        == 200
    )
    assert (
        client.delete(f"{URL}/{device.id}", headers=auth_headers(user)).status_code
        == 404
    )


def test_removing_requires_a_login(client, db):
    device = make_device(db)
    response = client.delete(f"{URL}/{device.id}")
    assert response.status_code == 401
    assert device_count(db) == 1


def test_a_deactivated_user_cannot_remove_a_device(client, db):
    user = make_user(db, UserRole.DONOR, is_active=False)
    device = make_device(db, user=user)
    response = client.delete(f"{URL}/{device.id}", headers=auth_headers(user))
    assert response.status_code == 403
    assert device_count(db) == 1
