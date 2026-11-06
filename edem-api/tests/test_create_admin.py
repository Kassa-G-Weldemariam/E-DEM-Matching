from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core.security import verify_password
from app.models.enums import UserRole
from app.models.user import User
from app.services.admin import (
    ADMIN_PASSWORD_MIN_LENGTH,
    AdminCreationError,
    create_admin,
)
from scripts import create_admin as cli
from tests.factories import make_user

EMAIL = "admin@edem-demo.org"
PASSWORD = "Admin-S3cure-pass"


def count_users(db) -> int:
    return db.scalar(select(func.count()).select_from(User))


def get_user(db, email=EMAIL) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def provider(db):
    """Lets the script use the test session (and not close it)."""
    return lambda: nullcontext(db)


@pytest.fixture(autouse=True)
def no_ambient_password(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)


# ----------------------------------------------------------------- service


def test_create_admin_makes_an_active_admin_with_a_hashed_password(db):
    user = create_admin(db, EMAIL, PASSWORD)
    assert user.role == UserRole.ADMIN
    assert user.is_active is True
    assert user.phone is None
    assert user.password_hash != PASSWORD
    assert verify_password(PASSWORD, user.password_hash) is True


def test_email_is_trimmed_and_lowercased(db):
    assert create_admin(db, "  Admin@EDEM-Demo.org ", PASSWORD).email == EMAIL


def test_an_existing_email_is_refused_and_the_user_is_not_promoted(db):
    make_user(db, UserRole.DONOR, email=EMAIL)
    with pytest.raises(AdminCreationError, match="already exists"):
        create_admin(db, EMAIL, PASSWORD)
    assert count_users(db) == 1
    assert get_user(db).role == UserRole.DONOR


@pytest.mark.parametrize(
    "password",
    ["a" * (ADMIN_PASSWORD_MIN_LENGTH - 1), "a" * 129, " " * 20],
)
def test_unacceptable_passwords_are_refused(db, password):
    with pytest.raises(AdminCreationError, match="[Pp]assword"):
        create_admin(db, EMAIL, password)
    assert count_users(db) == 0


@pytest.mark.parametrize("length", [ADMIN_PASSWORD_MIN_LENGTH, 128])
def test_password_length_limits_are_inclusive(db, length):
    assert create_admin(db, EMAIL, "a" * length).role == UserRole.ADMIN


@pytest.mark.parametrize("email", ["not-an-email", "a@b", ""])
def test_invalid_emails_are_refused(db, email):
    with pytest.raises(AdminCreationError, match="valid email"):
        create_admin(db, email, PASSWORD)
    assert count_users(db) == 0


def test_the_new_admin_can_log_in(client, db):
    create_admin(db, EMAIL, PASSWORD)
    response = client.post(
        "/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["data"]["user"]["role"] == "admin"


# ------------------------------------------------------------------ script


def test_script_creates_an_admin_from_the_environment_password(monkeypatch, db, capsys):
    monkeypatch.setenv("ADMIN_PASSWORD", PASSWORD)
    assert cli.main(["--email", EMAIL], provider(db)) == 0
    out = capsys.readouterr().out
    assert "Admin created" in out and EMAIL in out
    assert PASSWORD not in out
    assert get_user(db).role == UserRole.ADMIN


def test_script_shows_the_database_without_its_password(monkeypatch, db, capsys):
    monkeypatch.setenv("ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(
            active_database_url="postgresql+psycopg://someuser:top-secret-db-pw@dbhost:5432/edem"
        ),
    )
    cli.main(["--email", EMAIL], provider(db))
    out = capsys.readouterr().out
    assert "dbhost" in out
    assert "top-secret-db-pw" not in out


def test_script_fails_cleanly_when_the_email_exists(monkeypatch, db, capsys):
    make_user(db, UserRole.HOSPITAL, email=EMAIL)
    monkeypatch.setenv("ADMIN_PASSWORD", PASSWORD)
    assert cli.main(["--email", EMAIL], provider(db)) == 1
    captured = capsys.readouterr()
    assert "already exists" in captured.err
    assert "Admin created" not in captured.out


def test_script_asks_for_the_password_twice_when_it_is_not_in_the_environment(
    monkeypatch, db
):
    answers = iter([PASSWORD, PASSWORD])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert cli.main(["--email", EMAIL], provider(db)) == 0
    assert get_user(db) is not None


def test_script_refuses_when_the_two_typed_passwords_differ(monkeypatch, db, capsys):
    answers = iter([PASSWORD, "something-else-entirely"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert cli.main(["--email", EMAIL], provider(db)) == 1
    assert "do not match" in capsys.readouterr().err
    assert count_users(db) == 0


def test_script_requires_an_email():
    with pytest.raises(SystemExit) as exit_info:
        cli.main([])
    assert exit_info.value.code == 2


def test_script_refuses_a_short_password_from_the_environment(monkeypatch, db, capsys):
    monkeypatch.setenv("ADMIN_PASSWORD", "short")
    assert cli.main(["--email", EMAIL], provider(db)) == 1
    assert "Password" in capsys.readouterr().err
    assert count_users(db) == 0
