from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.api.pagination import PageDep, paginated
from app.core.exceptions import BadRequestException
from app.core.responses import success_response
from app.schemas.blood_bank import BloodBankPublic
from app.services.blood_banks import list_public_blood_banks

router = APIRouter(prefix="/blood-banks", tags=["Blood Banks"])


@router.get("")
def list_blood_banks(
    db: DbSession,
    page: PageDep,
    city: Annotated[
        str | None, Query(max_length=100, description="Only banks in this city")
    ] = None,
    lat: Annotated[
        float | None, Query(ge=-90, le=90, description="Your latitude (with lng)")
    ] = None,
    lng: Annotated[
        float | None, Query(ge=-180, le=180, description="Your longitude (with lat)")
    ] = None,
):
    """Public. Lists approved, active blood banks so donors and hospitals can pick one at signup."""
    if (lat is None) != (lng is None):
        raise BadRequestException("Send both lat and lng, or neither")

    ranked = list_public_blood_banks(db, city=city, latitude=lat, longitude=lng)
    window = ranked[page.offset : page.offset + page.page_size]
    items = [
        BloodBankPublic.model_validate(bank)
        .model_copy(update={"distance_km": distance})
        .model_dump(mode="json")
        for bank, distance in window
    ]
    return success_response(paginated(items, len(ranked), page))
