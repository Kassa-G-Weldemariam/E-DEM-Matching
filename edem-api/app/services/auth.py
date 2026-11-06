from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import (
    EmailAlreadyRegisteredException,
    ForbiddenException,
    InvalidCurrentPasswordException,
    UnauthorizedException,
)
from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_and_upgrade,
    verify_password,
)
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.auth import RegisterRequest

# Used when the email is unknown, so a failed login takes as long as a real password check.
_DUMMY_HASH = hash_password("timing-protection-dummy-password")

_LOGIN_FAILED = "Invalid email or password"
_ACCOUNT_DEACTIVATED = "This account has been deactivated"


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.strip().lower()))


def register_user(db: Session, data: RegisterRequest) -> User:
    """Create a user account. Profiles are created separately (Phase 1.4)."""
    if get_user_by_email(db, data.email):
        raise EmailAlreadyRegisteredException()

    user = User(
        email=data.email,
        phone=data.phone,
        password_hash=hash_password(data.password),
        role=UserRole(data.role.value),
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Two sign-ups with the same email at the same moment: the database unique rule wins.
        db.rollback()
        raise EmailAlreadyRegisteredException() from None
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    """Check the credentials. Unknown email and wrong password give the same error."""
    user = get_user_by_email(db, email)
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise UnauthorizedException(_LOGIN_FAILED)

    valid, new_hash = verify_and_upgrade(password, user.password_hash)
    if not valid:
        raise UnauthorizedException(_LOGIN_FAILED)
    if not user.is_active:
        raise ForbiddenException(_ACCOUNT_DEACTIVATED)

    if new_hash:  # the stored hash used outdated settings: save the stronger one
        user.password_hash = new_hash
        db.commit()
    return user


def issue_tokens(user: User) -> dict:
    settings = get_settings()
    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


def refresh_access_token(db: Session, refresh_token: str) -> dict:
    payload = decode_token(refresh_token, TokenType.REFRESH)
    user = db.get(User, payload.user_id)
    if user is None:
        raise UnauthorizedException("Invalid token")
    if not user.is_active:
        raise ForbiddenException(_ACCOUNT_DEACTIVATED)

    settings = get_settings()
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


def change_password(
    db: Session, user: User, current_password: str, new_password: str
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise InvalidCurrentPasswordException()
    user.password_hash = hash_password(new_password)
    db.commit()
