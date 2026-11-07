"""Donor matching.

This only writes a log line so the rest of
the flow can be built and tested. later code replaces the body with the real matching engine
(eligibility filters, distance, ranking, batches and push notifications).
"""

import logging

from sqlalchemy.orm import Session

from app.models.blood_request import BloodRequest

logger = logging.getLogger("app.matching")


def start_matching(db: Session, blood_request: BloodRequest) -> None:
    logger.info(
        "Matching would start now for request %s (%s, %s units)",
        blood_request.id,
        blood_request.blood_type.value,
        blood_request.units_needed,
    )
