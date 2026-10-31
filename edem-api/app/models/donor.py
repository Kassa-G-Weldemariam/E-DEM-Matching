import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import (
    BloodType,
    Gender,
    VerificationStatus,
    blood_type_type,
    gender_type,
    verification_status_type,
)
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Donor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "donors"
    __table_args__ = (
        CheckConstraint("weight_kg > 0", name="weight_positive"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
        # Suspensions must record who, when, and why.
        CheckConstraint(
            "verification_status <> 'suspended' OR "
            "(suspended_by IS NOT NULL AND suspended_at IS NOT NULL AND suspension_reason IS NOT NULL)",
            name="suspension_has_details",
        ),
        Index("ix_donors_blood_bank_id", "blood_bank_id"),
        # Used by the matching query.
        Index(
            "ix_donors_matching", "blood_type", "is_available", "verification_status"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), unique=True, nullable=False
    )
    # The blood bank the donor is registered under (onboarding and oversight, NOT matching).
    blood_bank_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("blood_banks.id"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    blood_type: Mapped[BloodType] = mapped_column(blood_type_type, nullable=False)
    gender: Mapped[Gender] = mapped_column(gender_type, nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    latitude: Mapped[float] = mapped_column(
        Float, nullable=False
    )  # current / last known location
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    # Empty for first-time donors. Updated when a hospital confirms a donation.
    last_donation_date: Mapped[date | None] = mapped_column(Date)
    is_available: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        verification_status_type,
        default=VerificationStatus.UNVERIFIED,
        server_default="unverified",
        nullable=False,
    )
    suspended_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspension_reason: Mapped[str | None] = mapped_column(Text)
