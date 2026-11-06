from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import EmailAlreadyRegisteredException
from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.auth import RegisterRequest


def _is_email_unique_violation(error: IntegrityError) -> bool:
    constraint_name = getattr(
        getattr(error.orig, "diag", None), "constraint_name", None
    )
    if constraint_name == "uq_users_email":
        return True

    return "UNIQUE constraint failed: users.email" in str(error.orig)


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
    except IntegrityError as error:
        # Two sign-ups with the same email at the same moment: the database unique rule wins.
        db.rollback()
        if _is_email_unique_violation(error):
            raise EmailAlreadyRegisteredException() from None
        raise
    db.refresh(user)
    return user
