import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import MatchStatus, match_status_type
from app.models.mixins import UUIDPrimaryKeyMixin


class Match(UUIDPrimaryKeyMixin, Base):
    """One donor notified for one request."""

    __tablename__ = "matches"
    __table_args__ = (
        # A donor can appear only once per request (later batches never repeat a donor).
        UniqueConstraint("request_id", "donor_id", name="uq_matches_request_donor"),
        CheckConstraint("batch_number >= 1", name="batch_number_positive"),
        CheckConstraint("distance_km >= 0", name="distance_non_negative"),
        Index("ix_matches_request_status", "request_id", "status"),
        Index("ix_matches_donor_id", "donor_id"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("blood_requests.id", ondelete="CASCADE"), nullable=False
    )
    donor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("donors.id"), nullable=False
    )
    batch_number: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[MatchStatus] = mapped_column(
        match_status_type,
        default=MatchStatus.NOTIFIED,
        server_default="notified",
        nullable=False,
    )
    notified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )  # accepted or declined
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    donated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
