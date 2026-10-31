import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import RequestStatus, request_status_type
from app.models.mixins import UUIDPrimaryKeyMixin


class RequestStatusHistory(UUIDPrimaryKeyMixin, Base):
    """Every status change of a blood request (for the timeline and audit)."""

    __tablename__ = "request_status_history"
    __table_args__ = (
        Index("ix_request_status_history_request_id", "request_id", "created_at"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("blood_requests.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[RequestStatus | None] = mapped_column(
        request_status_type
    )  # empty for the first status
    to_status: Mapped[RequestStatus] = mapped_column(
        request_status_type, nullable=False
    )
    # Empty when the system (timer or sweeper) made the change.
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
