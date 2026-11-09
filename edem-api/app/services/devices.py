import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.device_token import DeviceToken
from app.models.user import User
from app.schemas.device import DeviceRegisterRequest

MAX_DEVICES_PER_USER = 10


def _find_by_token(db: Session, token: str) -> DeviceToken | None:
    return db.scalar(select(DeviceToken).where(DeviceToken.token == token))


def _prune_old_devices(db: Session, user_id: uuid.UUID, keep_id: uuid.UUID) -> None:
    """Keep the device just registered plus the most recently used others, up to the limit."""
    others = list(
        db.scalars(
            select(DeviceToken)
            .where(DeviceToken.user_id == user_id, DeviceToken.id != keep_id)
            .order_by(DeviceToken.updated_at.desc(), DeviceToken.id)
        )
    )
    for extra in others[MAX_DEVICES_PER_USER - 1 :]:
        db.delete(extra)


def register_device(
    db: Session,
    user: User,
    data: DeviceRegisterRequest,
    *,
    now: datetime | None = None,
) -> tuple[DeviceToken, bool]:
    """Register a token for the user. Returns (device, created).

    A token belongs to a PHONE, not a person. If it was registered by someone else (the
    phone changed hands), it moves to this user, so the previous user stops receiving
    this user's notifications.
    """
    moment = now or datetime.now(UTC)
    device = _find_by_token(db, data.token)
    created = device is None

    if device is None:
        device = DeviceToken(
            user_id=user.id,
            token=data.token,
            platform=data.platform,
            created_at=moment,
            updated_at=moment,
        )
        db.add(device)
    else:
        device.user_id = user.id
        if data.platform is not None:
            device.platform = data.platform
        device.updated_at = moment

    try:
        db.flush()
    except IntegrityError:
        # Another request registered the same new token at the same moment: update that row.
        db.rollback()
        device = _find_by_token(db, data.token)
        if device is None:
            raise
        created = False
        device.user_id = user.id
        if data.platform is not None:
            device.platform = data.platform
        device.updated_at = moment
        db.flush()

    _prune_old_devices(db, user.id, keep_id=device.id)
    db.commit()
    db.refresh(device)
    return device, created


def delete_device(db: Session, device: DeviceToken) -> None:
    db.delete(device)
    db.commit()
