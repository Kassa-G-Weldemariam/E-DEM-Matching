"""Helpers for creating test data."""

import itertools

from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.models.enums import UserRole
from app.models.user import User

_counter = itertools.count(1)


def make_user(
    db: Session,
    role: UserRole = UserRole.DONOR,
    *,
    email: str | None = None,
    is_active: bool = True,
) -> User:
    """Insert a user directly (admins cannot register through the API).

    The password hash is a placeholder: use the register and login endpoints
    in tests that need a real login.
    """
    user = User(
        email=email or f"{role.value}-{next(_counter)}@edem-demo.org",
        phone="+251911234567",
        password_hash="not-a-real-hash",
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def auth_headers(user: User) -> dict[str, str]:
    """Authorization header with a valid access token for this user."""
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}
