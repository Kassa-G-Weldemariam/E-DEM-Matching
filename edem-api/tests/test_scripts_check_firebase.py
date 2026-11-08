import json
from types import SimpleNamespace

import pytest

from scripts import check_firebase as cli

PRIVATE_KEY = (
    "-----BEGIN PRIVATE KEY-----\nSECRETSECRETSECRET\n-----END PRIVATE KEY-----\n"
)
CLIENT_EMAIL = "firebase-adminsdk-abc@edem-matching.iam.gserviceaccount.com"


class FakeFirebaseError(Exception):
    def __init__(self, code, message="details from google"):
        super().__init__(message)
        self.code = code


class RefreshError(Exception):
    """Same class name as the Google error, so classify() recognises it."""


def write_key(tmp_path, **changes) -> str:
    data = {
        "type": "service_account",
        "project_id": "edem-matching",
        "client_email": CLIENT_EMAIL,
        "private_key": PRIVATE_KEY,
    }
    data.update(changes)
    data = {
        key: value for key, value in data.items() if value is not None
    }  # None removes a field
    path = tmp_path / "firebase-key.json"
    path.write_text(json.dumps(data))
    return str(path)


def rejecting_with(error):
    def send(path):
        raise error

    return send


def accepting(path):
    return None


# ------------------------------------------------------------- classify


@pytest.mark.parametrize("code", ["INVALID_ARGUMENT", "NOT_FOUND"])
def test_a_rejected_fake_token_means_the_credentials_work(code):
    ok, message = cli.classify(FakeFirebaseError(code))
    assert ok is True
    assert "accepted the credentials" in message


def test_permission_denied_points_at_the_sending_api():
    ok, message = cli.classify(
        FakeFirebaseError("PERMISSION_DENIED", "API is disabled")
    )
    assert ok is False
    assert "Cloud Messaging API" in message
    assert "API is disabled" in message


def test_unauthenticated_asks_for_a_new_key():
    ok, message = cli.classify(FakeFirebaseError("UNAUTHENTICATED"))
    assert ok is False
    assert "new key" in message


def test_a_rejected_key_is_recognised_by_the_google_error_name():
    ok, message = cli.classify(RefreshError("invalid_grant"))
    assert ok is False
    assert "service account key" in message


@pytest.mark.parametrize(
    "error",
    [
        FakeFirebaseError("UNAVAILABLE"),
        ConnectionError("no route"),
        TimeoutError("slow"),
    ],
    ids=["unavailable", "connection", "timeout"],
)
def test_network_problems_are_reported_as_such(error):
    ok, message = cli.classify(error)
    assert ok is False
    assert "Could not reach Firebase" in message


def test_an_unknown_error_is_shown_with_its_type():
    ok, message = cli.classify(ValueError("strange"))
    assert ok is False
    assert "ValueError" in message and "strange" in message


# ---------------------------------------------------------------- check


@pytest.mark.parametrize("path", [None, ""])
def test_a_missing_setting_is_explained(path):
    ok, lines = cli.check(path, send=accepting)
    assert ok is False
    assert "FIREBASE_CREDENTIALS_PATH" in lines[0]


def test_a_missing_file_is_explained(tmp_path):
    ok, lines = cli.check(str(tmp_path / "nothing.json"), send=accepting)
    assert ok is False
    assert "not found" in lines[0]


def test_a_file_that_is_not_json_is_explained(tmp_path):
    path = tmp_path / "firebase-key.json"
    path.write_text("this is not json")
    ok, lines = cli.check(str(path), send=accepting)
    assert ok is False
    assert "not valid JSON" in lines[0]


def test_google_services_json_is_recognised_as_the_wrong_file(tmp_path):
    ok, lines = cli.check(write_key(tmp_path, type="client"), send=accepting)
    assert ok is False
    assert "not a service account key" in lines[0]


@pytest.mark.parametrize("field", ["project_id", "client_email", "private_key"])
def test_a_key_missing_a_field_is_explained(tmp_path, field):
    ok, lines = cli.check(write_key(tmp_path, **{field: None}), send=accepting)
    assert ok is False
    assert field in lines[0]


def test_working_credentials_report_the_project_and_never_the_private_key(tmp_path):
    ok, lines = cli.check(
        write_key(tmp_path), send=rejecting_with(FakeFirebaseError("INVALID_ARGUMENT"))
    )
    text = "\n".join(lines)
    assert ok is True
    assert "edem-matching" in text
    assert CLIENT_EMAIL in text
    assert "OK:" in text
    assert "SECRETSECRETSECRET" not in text
    assert "PRIVATE KEY" not in text


def test_an_accepted_dry_run_is_also_a_success(tmp_path):
    ok, lines = cli.check(write_key(tmp_path), send=accepting)
    assert ok is True
    assert "OK:" in lines[-1]


def test_a_firebase_failure_is_reported_as_failed(tmp_path):
    ok, lines = cli.check(
        write_key(tmp_path), send=rejecting_with(FakeFirebaseError("PERMISSION_DENIED"))
    )
    assert ok is False
    assert lines[-1].startswith("FAILED:")


# ----------------------------------------------------------------- main


def test_main_succeeds_and_prints_the_result(tmp_path, monkeypatch, capsys):
    path = write_key(tmp_path)
    monkeypatch.setattr(
        cli, "get_settings", lambda: SimpleNamespace(FIREBASE_CREDENTIALS_PATH=path)
    )
    assert (
        cli.main([], sender=rejecting_with(FakeFirebaseError("INVALID_ARGUMENT"))) == 0
    )
    assert "OK:" in capsys.readouterr().out


def test_main_fails_with_exit_code_1_when_the_key_is_missing(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "get_settings", lambda: SimpleNamespace(FIREBASE_CREDENTIALS_PATH=None)
    )
    assert cli.main([], sender=accepting) == 1
    assert "FIREBASE_CREDENTIALS_PATH" in capsys.readouterr().out
