import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import BloodType, blood_type_type
from app.models.mixins import UUIDPrimaryKeyMixin


class Inventory(UUIDPrimaryKeyMixin, Base):
    """Basic stock: one row per blood type per blood bank."""

    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint(
            "blood_bank_id", "blood_type", name="uq_inventory_bank_blood_type"
        ),
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
    )

    blood_bank_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("blood_banks.id"), nullable=False
    )
    blood_type: Mapped[BloodType] = mapped_column(blood_type_type, nullable=False)
    quantity: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
