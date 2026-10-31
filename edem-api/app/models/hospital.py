import uuid

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ApprovalStatus, approval_status_type
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Hospital(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "hospitals"
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
        Index("ix_hospitals_blood_bank_id", "blood_bank_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), unique=True, nullable=False
    )
    # Primary / assigned blood bank: new requests are sent here first.
    blood_bank_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("blood_banks.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    # Only approved hospitals can create requests.
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        approval_status_type,
        default=ApprovalStatus.PENDING,
        server_default="pending",
        nullable=False,
    )
