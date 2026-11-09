import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.device_token import DeviceToken
from app.models.enums import UserRole
from app.services import push
from app.services.push import (
    DEFAULT_TTL,
    EMERGENCY_CHANNEL_ID,
    FirebasePushClient,
    PushNotConfiguredError,
    PushOutcome,
    build_message,
    classify_send_error,
    clean_data,
    get_push_client,
    mask_token,
    send_push_to_user,
)
from tests.factories import make_device, make_user

BASE = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
DEAD, RETRY, FAILED, SENT = (
    PushOutcome.DEAD_TOKEN,
    PushOutcome.RETRYABLE,
    PushOutcome.FAILED,
    PushOutcome.SENT,
)


class FakeFirebaseError(Exception):
    def __init__(self, code, message="details"):
        super().__init__(message)
        self.code = code


class FakeClient:
    def __init__(self, errors=None):
        self.errors = errors or {}
        self.calls = []

    def send(self, token, title, body, data, *, ttl):
        self.calls.append(
            SimpleNamespace(token=token, title=title, body=body, data=data, ttl=ttl)
        )
        if token in self.errors:
            raise self.errors[token]


def donor(db):
    return make_user(db, UserRole.DONOR)


def devices_for(db, user, count):
    """Devices with increasing ages: the LAST one in the list is the newest (sent first)."""
    devices = []
    for number in range(count):
        device = make_device(db, user=user, token=f"token-{number}-" + "x" * 40)
        device.updated_at = BASE + timedelta(minutes=number)
        devices.append(device)
    db.commit()
    return devices


def stored_tokens(db, user) -> set[str]:
    return {
        device.token
        for device in db.scalars(
            select(DeviceToken).where(DeviceToken.user_id == user.id)
        )
    }


# ----------------------------------------------------- what an error means


@pytest.mark.parametrize(
    "error,expected",
    [
        (FakeFirebaseError("NOT_FOUND"), DEAD),
        (
            FakeFirebaseError(
                "INVALID_ARGUMENT",
                "The registration token is not a valid FCM registration token",
            ),
            DEAD,
        ),
        (
            FakeFirebaseError("INVALID_ARGUMENT", "Invalid JSON payload received"),
            FAILED,
        ),
        (FakeFirebaseError("PERMISSION_DENIED", "SenderId mismatch"), DEAD),
        (FakeFirebaseError("PERMISSION_DENIED", "The API is disabled"), FAILED),
        (FakeFirebaseError("UNAUTHENTICATED"), FAILED),
        (FakeFirebaseError("UNAVAILABLE"), RETRY),
        (FakeFirebaseError("INTERNAL"), RETRY),
        (FakeFirebaseError("DEADLINE_EXCEEDED"), RETRY),
        (FakeFirebaseError("RESOURCE_EXHAUSTED"), RETRY),
        (ConnectionError("no route"), RETRY),
        (TimeoutError("slow"), RETRY),
        (ValueError("a bug on our side"), FAILED),
    ],
    ids=[
        "not found",
        "invalid token",
        "invalid payload",
        "sender mismatch",
        "api disabled",
        "unauthenticated",
        "unavailable",
        "internal",
        "deadline",
        "quota",
        "connection",
        "timeout",
        "bug",
    ],
)
def test_each_error_is_classified_safely(error, expected):
    assert classify_send_error(error)[0] == expected


# ----------------------------------------------------------- the data payload


def test_data_values_become_strings_and_none_is_dropped():
    assert clean_data({"count": 7, "flag": True, "skip": None, "name": "x"}) == {
        "count": "7",
        "flag": "True",
        "name": "x",
    }
    assert clean_data(None) == {}


@pytest.mark.parametrize(
    "key", ["from", "notification", "message_type", "google.sent_time", "gcm.title"]
)
def test_reserved_data_keys_are_refused(key):
    with pytest.raises(ValueError, match="reserved"):
        clean_data({key: "x"})


# --------------------------------------------------------- the FCM message


def test_the_message_carries_the_token_title_body_and_data():
    message = build_message(
        "tok" * 10, "Title", "Body", {"type": "x"}, timedelta(minutes=5)
    )
    assert message.token == "tok" * 10
    assert message.notification.title == "Title"
    assert message.notification.body == "Body"
    assert message.data == {"type": "x"}


def test_the_message_asks_for_high_priority_delivery():
    message = build_message("tok" * 10, "T", "B", {}, DEFAULT_TTL)
    assert message.android.priority == "high"


def test_the_message_expires_and_uses_the_emergency_channel():
    message = build_message("tok" * 10, "T", "B", {}, timedelta(minutes=3))
    assert message.android.ttl == timedelta(minutes=3)
    assert message.android.notification.channel_id == EMERGENCY_CHANNEL_ID


def test_empty_data_is_left_out():
    assert build_message("tok" * 10, "T", "B", {}, DEFAULT_TTL).data is None


# ------------------------------------------------------------- sending


def test_a_notification_is_sent_to_every_device_of_the_user(db):
    user = donor(db)
    devices = devices_for(db, user, 3)
    client = FakeClient()
    report = send_push_to_user(db, user.id, "Title", "Body", client=client)
    assert report.total == report.sent == 3
    assert {call.token for call in client.calls} == {device.token for device in devices}


def test_the_client_receives_the_title_body_data_and_time_limit(db):
    user = donor(db)
    devices_for(db, user, 1)
    client = FakeClient()
    send_push_to_user(
        db,
        user.id,
        "Urgent",
        "O+ needed",
        data={"type": "blood_request", "request_id": 7},
        client=client,
        ttl=timedelta(minutes=2),
    )
    [call] = client.calls
    assert (call.title, call.body) == ("Urgent", "O+ needed")
    assert call.data == {"type": "blood_request", "request_id": "7"}
    assert call.ttl == timedelta(minutes=2)


def test_the_default_time_limit_is_ten_minutes(db):
    user = donor(db)
    devices_for(db, user, 1)
    client = FakeClient()
    send_push_to_user(db, user.id, "T", "B", client=client)
    assert client.calls[0].ttl == timedelta(minutes=10)


def test_the_newest_device_is_sent_first(db):
    user = donor(db)
    devices = devices_for(db, user, 3)
    client = FakeClient()
    send_push_to_user(db, user.id, "T", "B", client=client)
    assert [call.token for call in client.calls] == [
        device.token for device in reversed(devices)
    ]


def test_a_dead_token_is_removed_and_the_others_are_kept(db):
    user = donor(db)
    first, second = devices_for(db, user, 2)
    client = FakeClient({first.token: FakeFirebaseError("NOT_FOUND")})
    report = send_push_to_user(db, user.id, "T", "B", client=client)
    assert (report.sent, report.removed) == (1, 1)
    assert stored_tokens(db, user) == {second.token}


def test_a_temporary_error_keeps_the_token_and_is_reported(db):
    user = donor(db)
    [device] = devices_for(db, user, 1)
    client = FakeClient({device.token: FakeFirebaseError("UNAVAILABLE")})
    report = send_push_to_user(db, user.id, "T", "B", client=client)
    assert report.retryable == 1 and report.removed == 0
    assert stored_tokens(db, user) == {device.token}


def test_a_failure_such_as_permission_denied_keeps_the_token(db):
    user = donor(db)
    [device] = devices_for(db, user, 1)
    client = FakeClient(
        {device.token: FakeFirebaseError("PERMISSION_DENIED", "The API is disabled")}
    )
    report = send_push_to_user(db, user.id, "T", "B", client=client)
    assert report.failed == 1 and report.removed == 0
    assert stored_tokens(db, user) == {device.token}


def test_an_unexpected_exception_from_the_client_is_a_failure_not_a_crash(db):
    user = donor(db)
    [device] = devices_for(db, user, 1)
    client = FakeClient({device.token: RuntimeError("something odd")})
    report = send_push_to_user(db, user.id, "T", "B", client=client)
    assert report.failed == 1
    assert "RuntimeError" in report.results[0].detail


def test_one_failing_device_does_not_stop_the_others(db):
    user = donor(db)
    devices = devices_for(db, user, 3)
    newest = devices[-1]
    client = FakeClient({newest.token: FakeFirebaseError("INTERNAL")})
    report = send_push_to_user(db, user.id, "T", "B", client=client)
    assert len(client.calls) == 3  # all three were tried, the failing one first
    assert client.calls[0].token == newest.token
    assert (report.sent, report.retryable) == (2, 1)


def test_the_report_counts_every_kind_of_outcome(db):
    user = donor(db)
    _sent, dead, retry, failed = devices_for(db, user, 4)
    client = FakeClient(
        {
            dead.token: FakeFirebaseError("NOT_FOUND"),
            retry.token: FakeFirebaseError("UNAVAILABLE"),
            failed.token: FakeFirebaseError("UNAUTHENTICATED"),
        }
    )
    report = send_push_to_user(db, user.id, "T", "B", client=client)
    assert (
        report.total,
        report.sent,
        report.removed,
        report.retryable,
        report.failed,
    ) == (4, 1, 1, 1, 1)


def test_a_user_without_devices_sends_nothing_and_needs_no_credentials(db):
    report = send_push_to_user(
        db, donor(db).id, "T", "B"
    )  # no client given, none needed
    assert report.total == 0


def test_only_the_targeted_users_devices_are_used(db):
    target, other = donor(db), donor(db)
    [target_device] = devices_for(db, target, 1)
    make_device(db, user=other, token="someone-elses-token-" + "x" * 30)
    client = FakeClient()
    send_push_to_user(db, target.id, "T", "B", client=client)
    assert [call.token for call in client.calls] == [target_device.token]


def test_tokens_never_appear_in_the_log(db, caplog):
    user = donor(db)
    [device] = devices_for(db, user, 1)
    client = FakeClient({device.token: FakeFirebaseError("UNAVAILABLE")})
    with caplog.at_level(logging.DEBUG, logger="app.push"):
        send_push_to_user(db, user.id, "T", "B", client=client)
    assert caplog.text
    assert device.token not in caplog.text


@pytest.mark.parametrize("title,body", [("", "body"), ("title", ""), ("  ", "body")])
def test_a_blank_title_or_body_is_refused(db, title, body):
    user = donor(db)
    devices_for(db, user, 1)
    client = FakeClient()
    with pytest.raises(ValueError, match="title and a body"):
        send_push_to_user(db, user.id, title, body, client=client)
    assert client.calls == []


# --------------------------------------------------- the real client setup


def test_the_real_client_needs_the_credentials_path(monkeypatch):
    monkeypatch.setattr(
        push, "get_settings", lambda: SimpleNamespace(FIREBASE_CREDENTIALS_PATH=None)
    )
    get_push_client.cache_clear()
    with pytest.raises(PushNotConfiguredError, match="FIREBASE_CREDENTIALS_PATH"):
        get_push_client()


def test_the_real_client_is_created_from_the_configured_path(monkeypatch):
    monkeypatch.setattr(
        push,
        "get_settings",
        lambda: SimpleNamespace(FIREBASE_CREDENTIALS_PATH="./key.json"),
    )
    get_push_client.cache_clear()
    client = get_push_client()
    assert isinstance(client, FirebasePushClient)
    assert client._credentials_path == "./key.json"
    get_push_client.cache_clear()


def test_tokens_are_masked_to_their_first_characters():
    assert mask_token("abcdefgh-the-rest-is-secret") == "abcdefgh..."
