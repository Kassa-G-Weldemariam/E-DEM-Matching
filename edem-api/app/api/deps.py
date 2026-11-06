"""Shared FastAPI dependencies."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import (
    AccountNotApprovedException,
    ForbiddenException,
    UnauthorizedException,
)
from app.core.security import TokenType, decode_token
from app.db.session import get_db
from app.models.blood_bank import BloodBank
from app.models.enums import ApprovalStatus, UserRole
from app.models.hospital import Hospital
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


# ---------------------------------------------------------------------------
# Role guards
# ---------------------------------------------------------------------------


def require_roles(*allowed_roles: UserRole) -> Callable[..., User]:
    """Build a dependency that lets only the listed roles through.

    Usage in a route:
        user: Annotated[User, Depends(require_roles(UserRole.BLOOD_BANK, UserRole.ADMIN))]
    """
    if not allowed_roles:
        raise ValueError("require_roles() needs at least one role")
    allowed = frozenset(allowed_roles)

    def dependency(current_user: CurrentUser) -> User:
        if current_user.role not in allowed:
            raise ForbiddenException(
                "You do not have permission to perform this action"
            )
        return current_user

    return dependency


# Ready-made guards for the common single-role cases.
DonorUser = Annotated[User, Depends(require_roles(UserRole.DONOR))]
HospitalUser = Annotated[User, Depends(require_roles(UserRole.HOSPITAL))]
BloodBankUser = Annotated[User, Depends(require_roles(UserRole.BLOOD_BANK))]
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


# ---------------------------------------------------------------------------
# Approval guards: action endpoints for hospitals and blood banks
# ---------------------------------------------------------------------------


def _ensure_approved(profile: Hospital | BloodBank | None, label: str) -> None:
    if profile is None:
        raise AccountNotApprovedException(
            f"Create your {label} profile before using this feature"
        )
    if profile.approval_status == ApprovalStatus.PENDING:
        raise AccountNotApprovedException(
            f"Your {label} account is waiting for Admin approval"
        )
    if profile.approval_status != ApprovalStatus.APPROVED:
        raise AccountNotApprovedException(f"Your {label} account has been suspended")


def get_approved_hospital(user: HospitalUser, db: DbSession) -> Hospital:
    """The caller's own hospital profile, only if an Admin has approved it."""
    hospital = db.scalar(select(Hospital).where(Hospital.user_id == user.id))
    _ensure_approved(hospital, "hospital")
    assert (
        hospital is not None
    )  # _ensure_approved raised otherwise (this also helps mypy)
    return hospital


def get_approved_blood_bank(user: BloodBankUser, db: DbSession) -> BloodBank:
    """The caller's own blood bank profile, only if an Admin has approved it."""
    blood_bank = db.scalar(select(BloodBank).where(BloodBank.user_id == user.id))
    _ensure_approved(blood_bank, "blood bank")
    assert blood_bank is not None
    return blood_bank


# Use these on ACTION endpoints (create a request, fulfill a request, ...).
# Profile endpoints must use plain HospitalUser / BloodBankUser, so a new
# account can create its profile and a pending one can see its status.
ApprovedHospital = Annotated[Hospital, Depends(get_approved_hospital)]
ApprovedBloodBank = Annotated[BloodBank, Depends(get_approved_blood_bank)]
