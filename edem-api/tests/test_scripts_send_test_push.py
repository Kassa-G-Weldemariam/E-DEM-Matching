import re
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.device_token import DeviceToken
from app.models.enums import UserRole
from app.services.push import DEFAULT_TTL, PushNotConfiguredError
from scripts import send_test_push as cli
from tests.factories import make_device, make_user

EMAIL = "donor@edem-demo.org"


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


def provider(db):
    return lambda: nullcontext(db)


def donor_with_devices(db, count=1):
    user = make_user(db, UserRole.DONOR, email=EMAIL)
    devices = [
        make_device(db, user=user, token=f"secret-token-{number}-" + "x" * 40)
        for number in range(count)
    ]
    return user, devices


def stored_count(db) -> int:
    return len(list(db.scalars(select(DeviceToken))))


def run(db, *argv, client=None, **kwargs):
    return cli.main(["--email", EMAIL, *argv], provider(db), client, **kwargs)


# ------------------------------------------------------------- sending


def test_it_sends_to_every_device_and_reports_success(db, capsys):
    donor_with_devices(db, 2)
    client = FakeClient()
    assert run(db, client=client) == 0
    out = capsys.readouterr().out
    assert len(client.calls) == 2
    assert out.count("SENT") == 2
    assert "2 sent, 0 removed" in out


def test_the_default_message_and_a_test_payload_are_sent(db):
    donor_with_devices(db)
    client = FakeClient()
    run(db, client=client)
    [call] = client.calls
    assert call.title == cli.DEFAULT_TITLE
    assert call.body == cli.DEFAULT_BODY
    assert call.data["type"] == "test"
    assert call.data["sent_at"]


def test_a_custom_title_and_body_can_be_given(db):
    donor_with_devices(db)
    client = FakeClient()
    run(db, "--title", "Hello", "--body", "From the terminal", client=client)
    assert (client.calls[0].title, client.calls[0].body) == (
        "Hello",
        "From the terminal",
    )


def test_the_email_is_matched_ignoring_case(db):
    donor_with_devices(db)
    client = FakeClient()
    assert cli.main(["--email", "  DONOR@Edem-Demo.org "], provider(db), client) == 0
    assert len(client.calls) == 1


def test_a_dead_token_is_removed_and_reported(db, capsys):
    _, [device] = donor_with_devices(db)
    client = FakeClient({device.token: FakeFirebaseError("NOT_FOUND")})
    assert run(db, client=client) == 1  # nothing was delivered
    out = capsys.readouterr().out
    assert "DEAD_TOKEN" in out
    assert "1 removed" in out
    assert stored_count(db) == 0


def test_the_exit_code_is_1_when_nothing_was_sent(db):
    _, [device] = donor_with_devices(db)
    client = FakeClient({device.token: FakeFirebaseError("UNAVAILABLE")})
    assert run(db, client=client) == 1
    assert stored_count(db) == 1  # a temporary problem keeps the token


def test_a_partial_success_still_exits_with_0(db, capsys):
    _, [first, _second] = donor_with_devices(db, 2)
    client = FakeClient({first.token: FakeFirebaseError("NOT_FOUND")})
    assert run(db, client=client) == 0
    assert "1 sent, 1 removed" in capsys.readouterr().out
    assert stored_count(db) == 1


# ------------------------------------------------------------- mistakes


def test_a_user_without_devices_is_explained(db, capsys):
    make_user(db, UserRole.DONOR, email=EMAIL)
    client = FakeClient()
    assert run(db, client=client) == 1
    assert "no registered devices" in capsys.readouterr().out
    assert client.calls == []


def test_an_unknown_email_is_explained(db, capsys):
    assert run(db, client=FakeClient()) == 1
    assert "No user with the email" in capsys.readouterr().out


def test_missing_credentials_are_explained(db, monkeypatch, capsys):
    donor_with_devices(db)

    def not_configured():
        raise PushNotConfiguredError("FIREBASE_CREDENTIALS_PATH is not set")

    monkeypatch.setattr(cli, "get_push_client", not_configured)
    assert run(db) == 1
    assert "FIREBASE_CREDENTIALS_PATH" in capsys.readouterr().err


# ------------------------------------------------------------- dry run


def test_a_dry_run_lists_the_devices_and_sends_nothing(db, capsys):
    donor_with_devices(db, 2)
    client = FakeClient()
    assert run(db, "--dry-run", client=client) == 0
    out = capsys.readouterr().out
    assert "Dry run" in out
    assert client.calls == []


def test_a_dry_run_works_without_credentials(db, monkeypatch):
    donor_with_devices(db)

    def not_configured():
        raise PushNotConfiguredError("not set")

    monkeypatch.setattr(cli, "get_push_client", not_configured)
    assert run(db, "--dry-run") == 0


def test_tokens_are_shown_only_in_part(db, capsys):
    _, [device] = donor_with_devices(db)
    run(db, "--dry-run")
    out = capsys.readouterr().out
    assert device.token[:8] in out
    assert device.token not in out


# ------------------------------------------------------------- delay


def test_the_delay_waits_before_sending(db, capsys):
    donor_with_devices(db)
    waited = []
    client = FakeClient()
    run(db, "--delay", "5", client=client, sleep=waited.append)
    assert waited == [5]
    assert "5 seconds" in capsys.readouterr().out
    assert len(client.calls) == 1


@pytest.mark.parametrize("delay", ["-1", "301", "abc"])
def test_a_delay_out_of_range_is_refused(db, delay):
    with pytest.raises(SystemExit) as exit_info:
        run(db, "--delay", delay, client=FakeClient())
    assert exit_info.value.code == 2


# -------------------------------------------------------- safety rules


def test_it_refuses_to_run_in_production(db, monkeypatch, capsys):
    donor_with_devices(db)
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(
            ENVIRONMENT="production",
            active_database_url="postgresql+psycopg://u:p@dbhost/edem",
        ),
    )
    client = FakeClient()
    assert run(db, client=client) == 1
    assert "production" in capsys.readouterr().err
    assert client.calls == []


def test_it_shows_the_database_without_its_password(db, monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(
            ENVIRONMENT="development",
            active_database_url="postgresql+psycopg://someuser:top-secret-db-pw@dbhost:5433/edem_matching",
        ),
    )
    run(db, "--dry-run")
    out = capsys.readouterr().out
    assert "dbhost" in out
    assert "top-secret-db-pw" not in out


# --------------------------------------------------- send time and time limit


def test_the_send_time_is_in_the_payload_with_millisecond_precision(db):
    donor_with_devices(db)
    client = FakeClient()
    run(db, client=client)
    sent_at = client.calls[0].data["sent_at"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+00:00", sent_at)


def test_the_send_time_is_printed(db, capsys):
    donor_with_devices(db)
    run(db, client=FakeClient())
    assert "Sent at" in capsys.readouterr().out


def test_a_time_limit_can_be_given_in_seconds(db):
    donor_with_devices(db)
    client = FakeClient()
    run(db, "--ttl", "45", client=client)
    assert client.calls[0].ttl == timedelta(seconds=45)


def test_the_default_time_limit_is_used_without_the_option(db):
    donor_with_devices(db)
    client = FakeClient()
    run(db, client=client)
    assert client.calls[0].ttl == DEFAULT_TTL


@pytest.mark.parametrize("ttl", ["0", "-1", "3601", "abc"])
def test_a_time_limit_out_of_range_is_refused(db, ttl):
    with pytest.raises(SystemExit) as exit_info:
        run(db, "--ttl", ttl, client=FakeClient())
    assert exit_info.value.code == 2
