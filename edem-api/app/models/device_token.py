import uuid

from sqlalchemy import ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import DevicePlatform, device_platform_type
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class DeviceToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Push notification token of one device (a user can have several)."""

    __tablename__ = "device_tokens"
    __table_args__ = (Index("ix_device_tokens_user_id", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    token: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    platform: Mapped[DevicePlatform | None] = mapped_column(device_platform_type)
