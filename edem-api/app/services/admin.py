"""Creating admin accounts. Admins can never register through the API."""

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.auth import PASSWORD_MAX_LENGTH
from app.services.auth import get_user_by_email

# Admins are powerful, so their password minimum is higher than for normal users (8).
ADMIN_PASSWORD_MIN_LENGTH = 12

_email_adapter = TypeAdapter(EmailStr)


class AdminCreationError(Exception):
    """An admin could not be created. The message is meant to be shown to a person."""


def create_admin(db: Session, email: str, password: str) -> User:
    try:
        clean_email = _email_adapter.validate_python(email.strip().lower())
    except ValidationError:
        raise AdminCreationError("That is not a valid email address") from None

    if not ADMIN_PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise AdminCreationError(
            f"Password must be between {ADMIN_PASSWORD_MIN_LENGTH} and {PASSWORD_MAX_LENGTH} characters"
        )
    if not password.strip():
        raise AdminCreationError("Password cannot be blank")

    # Never promote an existing account: that would be a quiet way to escalate privileges.
    if get_user_by_email(db, clean_email):
        raise AdminCreationError("A user with this email already exists")

    user = User(
        email=clean_email,
        phone=None,
        password_hash=hash_password(password),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AdminCreationError("A user with this email already exists") from None
    db.refresh(user)
    return user
