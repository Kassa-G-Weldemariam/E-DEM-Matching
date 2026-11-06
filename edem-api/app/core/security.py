"""Security helpers: password hashing (Step 1) and JWT tokens (Step 2)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedException

# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

_password_hash = PasswordHash.recommended()


def hash_password(plain_password: str) -> str:
    """Return a salted one-way hash. Store this in users.password_hash, never the password."""
    return _password_hash.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """True only if the password matches the stored hash. Never raises on a bad hash."""
    try:
        return _password_hash.verify(plain_password, hashed_password)
    except UnknownHashError:
        return False


def verify_and_upgrade(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    """Check a password and, if the stored hash uses outdated settings, return a fresh one.

    Returns (is_valid, new_hash). new_hash is None when no upgrade is needed.
    """
    try:
        return _password_hash.verify_and_update(plain_password, hashed_password)
    except UnknownHashError:
        return False, None


# ---------------------------------------------------------------------------
# JWT tokens
# ---------------------------------------------------------------------------


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


@dataclass(frozen=True)
class TokenPayload:
    user_id: uuid.UUID
    token_type: TokenType
    jti: str
    expires_at: datetime


_REQUIRED_CLAIMS = ["exp", "iat", "sub", "type", "jti"]


def _create_token(
    user_id: uuid.UUID, token_type: TokenType, expires_delta: timedelta
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "type": token_type.value,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(
        claims,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_access_token(
    user_id: uuid.UUID, expires_delta: timedelta | None = None
) -> str:
    """Short-lived token sent with every request. expires_delta is for tests."""
    settings = get_settings()
    delta = (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return _create_token(user_id, TokenType.ACCESS, delta)


def create_refresh_token(
    user_id: uuid.UUID, expires_delta: timedelta | None = None
) -> str:
    """Long-lived token used only to get a new access token. expires_delta is for tests."""
    settings = get_settings()
    delta = (
        expires_delta
        if expires_delta is not None
        else timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    return _create_token(user_id, TokenType.REFRESH, delta)


def decode_token(token: str, expected_type: TokenType) -> TokenPayload:
    """Check signature, expiry, required claims and token type.

    Raises UnauthorizedException (401) for anything wrong.
    """
    if not token:
        raise UnauthorizedException("Invalid token")

    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": _REQUIRED_CLAIMS},
        )
    except jwt.ExpiredSignatureError:
        raise UnauthorizedException("Token has expired") from None
    except jwt.InvalidTokenError:
        raise UnauthorizedException("Invalid token") from None

    if claims["type"] != expected_type.value:
        raise UnauthorizedException("Wrong token type")

    try:
        user_id = uuid.UUID(claims["sub"])
    except (ValueError, TypeError, AttributeError):
        raise UnauthorizedException("Invalid token") from None

    return TokenPayload(
        user_id=user_id,
        token_type=expected_type,
        jti=claims["jti"],
        expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
    )