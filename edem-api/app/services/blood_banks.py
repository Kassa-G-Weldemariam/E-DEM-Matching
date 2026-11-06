from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.geo import haversine_km
from app.models.blood_bank import BloodBank
from app.models.enums import ApprovalStatus


def list_public_blood_banks(
    db: Session,
    *,
    city: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> list[tuple[BloodBank, float | None]]:
    """Approved, active blood banks. Sorted by name, or nearest first when coordinates are given.

    Distances are computed in Python. That is fine for the number of blood banks in a
    country (tens to hundreds). Revisit it if the list ever grows into the thousands.
    """
    query = select(BloodBank).where(
        BloodBank.approval_status == ApprovalStatus.APPROVED,
        BloodBank.is_active.is_(True),
    )
    if city and city.strip():
        query = query.where(func.lower(BloodBank.city) == city.strip().lower())
    banks = list(db.scalars(query.order_by(BloodBank.name, BloodBank.id)))

    if latitude is None or longitude is None:
        return [(bank, None) for bank in banks]

    ranked = sorted(
        (
            (
                bank,
                round(
                    haversine_km(latitude, longitude, bank.latitude, bank.longitude), 1
                ),
            )
            for bank in banks
        ),
        key=lambda pair: (pair[1], pair[0].name),
    )
    return [(bank, distance) for bank, distance in ranked]
