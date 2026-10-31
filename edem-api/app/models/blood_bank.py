import uuid

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ApprovalStatus, approval_status_type
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class BloodBank(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One blood bank center/branch."""

    __tablename__ = "blood_banks"
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), unique=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    # Operating flag: if False, new requests skip this bank and go straight to donor matching.
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    # Admin onboarding approval.
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        approval_status_type,
        default=ApprovalStatus.PENDING,
        server_default="pending",
        nullable=False,
    )
