"""Create an admin account. Admins can never register through the API.

Run from the edem-api folder:

    uv run python -m scripts.create_admin --email admin@example.org

The password is read from the ADMIN_PASSWORD environment variable, or asked for
(twice, hidden). It is never accepted as a command-line argument.
"""

import argparse
import getpass
import os
import sys
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.services.admin import (
    ADMIN_PASSWORD_MIN_LENGTH,
    AdminCreationError,
    create_admin,
)

SessionProvider = Callable[[], AbstractContextManager[Session]]


def _read_password() -> str:
    from_environment = os.environ.get("ADMIN_PASSWORD")
    if from_environment:
        return from_environment
    first = getpass.getpass(
        f"Password (at least {ADMIN_PASSWORD_MIN_LENGTH} characters): "
    )
    if first != getpass.getpass("Repeat password: "):
        raise AdminCreationError("The two passwords do not match")
    return first


def main(
    argv: Sequence[str] | None = None, session_provider: SessionProvider | None = None
) -> int:
    """Returns the exit code: 0 on success, 1 on failure. session_provider is for tests."""
    parser = argparse.ArgumentParser(description="Create an E-DEM admin account.")
    parser.add_argument("--email", required=True, help="Email address of the new admin")
    args = parser.parse_args(argv)

    provider = session_provider or get_session_factory()

    # Show where the admin will be created, with the password hidden.
    database = make_url(get_settings().active_database_url).render_as_string(
        hide_password=True
    )
    print(f"Database: {database}")

    try:
        password = _read_password()
        with provider() as db:
            user = create_admin(db, args.email, password)
            email, user_id = user.email, user.id
    except AdminCreationError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Admin created: {email} (id {user_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
