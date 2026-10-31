import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import (
    BloodType,
    RequestStatus,
    Urgency,
    blood_type_type,
    request_status_type,
    urgency_type,
)
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class BloodRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "blood_requests"
    __table_args__ = (
        CheckConstraint("units_needed > 0", name="units_needed_positive"),
        CheckConstraint(
            "units_from_inventory >= 0 AND units_confirmed >= 0",
            name="units_non_negative",
        ),
        # Units from stock + units confirmed from donors can never exceed what was requested.
        CheckConstraint(
            "units_from_inventory + units_confirmed <= units_needed",
            name="units_within_needed",
        ),
        CheckConstraint("current_batch >= 0", name="current_batch_non_negative"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
        Index("ix_blood_requests_hospital_id", "hospital_id"),
        Index("ix_blood_requests_blood_bank_id", "blood_bank_id"),
        # Used by the worker and the deadline sweeper.
        Index(
            "ix_blood_requests_status_response_deadline", "status", "response_deadline"
        ),
        Index("ix_blood_requests_status_donor_deadline", "status", "donor_deadline"),
    )

    hospital_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("hospitals.id"), nullable=False
    )
    blood_bank_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("blood_banks.id"), nullable=False
    )
    blood_type: Mapped[BloodType] = mapped_column(blood_type_type, nullable=False)
    units_needed: Mapped[int] = mapped_column(Integer, nullable=False)
    units_from_inventory: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    units_confirmed: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    urgency: Mapped[Urgency] = mapped_column(
        urgency_type, default=Urgency.NORMAL, server_default="normal", nullable=False
    )
    status: Mapped[RequestStatus] = mapped_column(
        request_status_type,
        default=RequestStatus.PENDING_BLOOD_BANK,
        server_default="pending_blood_bank",
        nullable=False,
    )
    # Hospital location, copied so matching does not need a join.
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    # Empty when the assigned blood bank is inactive and the request goes straight to matching.
    response_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 0 = no donor batch notified yet.
    current_batch: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    donor_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
