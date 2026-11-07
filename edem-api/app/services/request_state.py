"""Blood request status changes.

EVERY status change goes through transition_request(). Never assign
`blood_request.status = ...` anywhere else.

The allowed moves match the state machine in the Workflows document.
T6 (next batch), T7 (accept) and T9 (defer / no-show) are not listed because the
request stays in matching_donors: they change counters or match statuses only.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidStatusTransitionException
from app.models.blood_request import BloodRequest
from app.models.enums import RequestStatus
from app.models.request_status_history import RequestStatusHistory

S = RequestStatus

ALLOWED_TRANSITIONS: dict[RequestStatus, frozenset[RequestStatus]] = {
    S.PENDING_BLOOD_BANK: frozenset(
        {S.FULFILLED, S.MATCHING_DONORS, S.CANCELLED}
    ),  # T2, T3 T4 T5, T11
    S.MATCHING_DONORS: frozenset(
        {S.FULFILLED, S.UNFULFILLED, S.CANCELLED}
    ),  # T8, T10, T11
    S.FULFILLED: frozenset(),
    S.UNFULFILLED: frozenset(),
    S.CANCELLED: frozenset(),
}

# Other columns that may change in the same atomic update as the status.
_ALLOWED_EXTRA_FIELDS = frozenset(
    {
        "response_deadline",
        "donor_deadline",
        "current_batch",
        "units_from_inventory",
        "units_confirmed",
    }
)


def transition_request(
    db: Session,
    request_id: uuid.UUID,
    from_status: RequestStatus,
    to_status: RequestStatus,
    *,
    changed_by: uuid.UUID | None = None,
    note: str | None = None,
    set_fields: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> bool:
    """Move a request from one status to another, only if it is still in `from_status`.

    Returns True if this call made the change, or False if the request was no longer in
    `from_status` (someone else got there first) or does not exist. Nothing is changed
    and no history is written in that case.

    Raises InvalidStatusTransitionException if the move is never allowed
    (for example fulfilled -> pending_blood_bank): that is a bug in the caller.

    The caller must commit. The status change and its history row are part of the
    caller's transaction, so they succeed or fail together with the rest of its work.

    changed_by is empty when the system (a timer or the sweeper) made the change.
    set_fields lets the same atomic update change other columns, for example
    {"donor_deadline": ..., "current_batch": 1}.
    """
    if to_status not in ALLOWED_TRANSITIONS[from_status]:
        raise InvalidStatusTransitionException(
            f"A request cannot go from {from_status.value} to {to_status.value}"
        )

    extra = dict(set_fields or {})
    unknown = set(extra) - _ALLOWED_EXTRA_FIELDS
    if unknown:
        raise ValueError(
            f"These fields cannot be set during a transition: {sorted(unknown)}"
        )

    moment = now or datetime.now(UTC)
    values: dict[str, Any] = {**extra, "status": to_status}
    if to_status == RequestStatus.FULFILLED:
        values["fulfilled_at"] = moment
    if to_status == RequestStatus.CANCELLED:
        values["cancelled_at"] = moment

    # One conditional UPDATE: PostgreSQL lets only one concurrent caller match the old status.
    result = cast(
        "CursorResult[Any]",
        db.execute(
            update(BloodRequest)
            .where(BloodRequest.id == request_id, BloodRequest.status == from_status)
            .values(**values)
        ),
    )
    if result.rowcount != 1:
        return False

    db.add(
        RequestStatusHistory(
            request_id=request_id,
            from_status=from_status,
            to_status=to_status,
            changed_by=changed_by,
            note=note,
        )
    )
    db.flush()
    return True


def record_initial_status(
    db: Session,
    blood_request: BloodRequest,
    *,
    changed_by: uuid.UUID | None = None,
    note: str | None = None,
) -> None:
    """The first history row of a request (T1): there is no previous status."""
    db.add(
        RequestStatusHistory(
            request_id=blood_request.id,
            from_status=None,
            to_status=blood_request.status,
            changed_by=changed_by,
            note=note,
        )
    )
    db.flush()
