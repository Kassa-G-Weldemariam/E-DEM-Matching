"""The deadline sweeper.

It reads the deadlines stored in PostgreSQL and acts on the ones that have passed.
PostgreSQL is the source of truth for timers: a restart, a crash or a flushed Redis
cannot lose one, because the next sweep simply finds the overdue rows.

Step 3 of phase 2 only handles the Blood Bank response deadline (T5). Phase 3 adds the
donor batch deadlines and the arrival window to run_sweep().
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.blood_request import BloodRequest
from app.models.enums import RequestStatus
from app.services.blood_requests import start_matching_safely
from app.services.request_state import transition_request

logger = logging.getLogger("app.sweeper")

# One sweep never handles more than this, so it stays short. The rest wait for the next sweep.
MAX_REQUESTS_PER_SWEEP = 100


@dataclass(frozen=True)
class SweepResult:
    response_timeouts: int = 0


def process_expired_response_deadlines(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = MAX_REQUESTS_PER_SWEEP,
) -> int:
    """Blood bank did not answer in time (T5): pending_blood_bank -> matching_donors.

    Returns how many requests THIS call moved. Oldest deadlines go first.
    """
    moment = now or datetime.now(UTC)
    expired_ids = list(
        db.scalars(
            select(BloodRequest.id)
            .where(
                BloodRequest.status == RequestStatus.PENDING_BLOOD_BANK,
                BloodRequest.response_deadline.is_not(None),
                BloodRequest.response_deadline <= moment,
            )
            .order_by(BloodRequest.response_deadline, BloodRequest.id)
            .limit(limit)
        )
    )

    moved = 0
    for request_id in expired_ids:
        try:
            changed = transition_request(
                db,
                request_id,
                RequestStatus.PENDING_BLOOD_BANK,
                RequestStatus.MATCHING_DONORS,
                note="Blood bank response timeout",
                now=moment,
            )
            db.commit()
        except Exception:
            # One bad request must never stop the others.
            db.rollback()
            logger.exception(
                "Could not process the response timeout of request %s", request_id
            )
            continue

        if not changed:
            # The blood bank (or the hospital) acted first. Nothing to do.
            logger.debug("Request %s was no longer pending, skipped", request_id)
            continue

        moved += 1
        logger.info(
            "Blood bank response timeout: request %s moved to matching_donors",
            request_id,
        )
        blood_request = db.get(BloodRequest, request_id)
        if blood_request is not None:
            db.refresh(blood_request)
            start_matching_safely(db, blood_request)
    return moved


def run_sweep(db: Session, *, now: datetime | None = None) -> SweepResult:
    """One pass over everything that can time out. The worker (Step 4) calls this."""
    return SweepResult(
        response_timeouts=process_expired_response_deadlines(db, now=now)
    )
