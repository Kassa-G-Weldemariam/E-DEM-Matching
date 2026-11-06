"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.security import TokenType, decode_token
from app.db.session import get_db
from app.models.user import User

# auto_error=False: a missing header reaches our code, so the response uses the standard
# error format with status 401 (FastAPI's own default would be 403).
bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Paste the access token returned by /v1/auth/login (without the word Bearer).",
)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: DbSession,
) -> User:
    """The logged-in user. Roles and active status are read from the database on every
    request, never from the token, so changes by an admin take effect immediately."""
    if credentials is None:
        raise UnauthorizedException("Missing or invalid token")

    payload = decode_token(credentials.credentials, TokenType.ACCESS)

    user = db.get(User, payload.user_id)
    if user is None:
        raise UnauthorizedException("Invalid token")
    if not user.is_active:
        raise ForbiddenException("This account has been deactivated")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
