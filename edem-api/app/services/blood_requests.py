import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.blood_request import BloodRequest
from app.models.enums import RequestStatus
from app.models.hospital import Hospital
from app.schemas.blood_request import BloodRequestCreate
from app.services.blood_banks import get_available_blood_bank
from app.services.matching import start_matching
from app.services.request_state import record_initial_status

logger = logging.getLogger("app.requests")


def create_blood_request(
    db: Session,
    hospital: Hospital,
    data: BloodRequestCreate,
    *,
    now: datetime | None = None,
) -> BloodRequest:
    """Create a request (T1). `hospital` must already be approved: the route guarantees it.

    * Primary blood bank available: status pending_blood_bank, with a response deadline.
    * Primary blood bank unavailable (suspended or paused): straight to matching_donors,
      so a dead blood bank never delays an emergency.
    """
    moment = now or datetime.now(UTC)
    bank_available = get_available_blood_bank(db, hospital.blood_bank_id) is not None

    if bank_available:
        status = RequestStatus.PENDING_BLOOD_BANK
        deadline = moment + get_settings().blood_bank_timeout(data.urgency.value)
        note = "Request created"
    else:
        status = RequestStatus.MATCHING_DONORS
        deadline = None
        note = "Request created. The primary blood bank is unavailable, so it went straight to donor matching"

    blood_request = BloodRequest(
        hospital_id=hospital.id,
        blood_bank_id=hospital.blood_bank_id,
        blood_type=data.blood_type,
        units_needed=data.units_needed,
        urgency=data.urgency,
        notes=data.notes,
        status=status,
        latitude=hospital.latitude,  # copied, so matching does not need a join
        longitude=hospital.longitude,
        response_deadline=deadline,
    )
    db.add(blood_request)
    db.flush()  # assigns the id used by the history row
    record_initial_status(db, blood_request, changed_by=hospital.user_id, note=note)
    db.commit()
    db.refresh(blood_request)

    if status == RequestStatus.MATCHING_DONORS:
        start_matching_safely(db, blood_request)
    return blood_request


def start_matching_safely(db: Session, blood_request: BloodRequest) -> None:
    """The request already exists, so a failure here must not make the hospital's call fail.

    Later a request that is in matching_donors with no batch yet is exactly what
    the sweeper should pick up and retry.
    """
    try:
        start_matching(db, blood_request)
    except Exception:
        db.rollback()
        logger.exception("Could not start matching for request %s", blood_request.id)
