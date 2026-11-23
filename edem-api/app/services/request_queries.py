"""Read-only queries behind the request screens (hospital and donor)."""

import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundException
from app.models.blood_request import BloodRequest
from app.models.donor import Donor
from app.models.enums import MatchStatus, RequestStatus, VerificationStatus
from app.models.hospital import Hospital
from app.models.match import Match
from app.models.request_status_history import RequestStatusHistory
from app.models.user import User

# A hospital sees a donor's details only while it deals with that donor in person.
CONTACT_VISIBLE_MATCH_STATUSES = frozenset(
    {
        MatchStatus.ACCEPTED,
        MatchStatus.ARRIVED,
        MatchStatus.DONATED,
        MatchStatus.DEFERRED,
    }
)

# Matches still in progress from the donor's point of view.
OPEN_MATCH_STATUSES = (MatchStatus.NOTIFIED, MatchStatus.ACCEPTED, MatchStatus.ARRIVED)


@dataclass(frozen=True)
class HistoryEntry:
    row: RequestStatusHistory
    actor: str  # "system", or the role of the person who made the change


@dataclass(frozen=True)
class MatchEntry:
    match: Match
    donor: Donor
    phone: str | None


@dataclass(frozen=True)
class DonorRequestEntry:
    match: Match
    request: BloodRequest
    hospital: Hospital
    can_respond: bool


# ------------------------------------------------------------------ hospital


def list_hospital_requests(
    db: Session,
    hospital_id: uuid.UUID,
    *,
    status: RequestStatus | None,
    limit: int,
    offset: int,
) -> tuple[list[BloodRequest], int]:
    """The hospital's own requests, newest first, and the total number that match the filter."""
    filters: list[ColumnElement[bool]] = [BloodRequest.hospital_id == hospital_id]
    if status is not None:
        filters.append(BloodRequest.status == status)

    total = (
        db.scalar(select(func.count()).select_from(BloodRequest).where(*filters)) or 0
    )
    rows = list(
        db.scalars(
            select(BloodRequest)
            .where(*filters)
            .order_by(BloodRequest.created_at.desc(), BloodRequest.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return rows, total


def list_request_history(db: Session, request_id: uuid.UUID) -> list[HistoryEntry]:
    """The status timeline, oldest first."""
    rows = db.execute(
        select(RequestStatusHistory, User.role)
        .outerjoin(User, User.id == RequestStatusHistory.changed_by)
        .where(RequestStatusHistory.request_id == request_id)
        .order_by(RequestStatusHistory.created_at, RequestStatusHistory.id)
    ).all()
    return [
        HistoryEntry(row=row, actor=role.value if role else "system")
        for row, role in rows
    ]


def list_request_matches(db: Session, request_id: uuid.UUID) -> list[MatchEntry]:
    """The donors notified for a request: first batch first, then the nearest."""
    rows = db.execute(
        select(Match, Donor, User.phone)
        .join(Donor, Donor.id == Match.donor_id)
        .join(User, User.id == Donor.user_id)
        .where(Match.request_id == request_id)
        .order_by(Match.batch_number, Match.distance_km, Match.id)
    ).all()
    return [
        MatchEntry(match=match, donor=donor, phone=phone)
        for match, donor, phone in rows
    ]


# --------------------------------------------------------------------- donor


def can_respond(match: Match, blood_request: BloodRequest, donor: Donor) -> bool:
    """Whether the donor should be offered Accept and Decline.

    The acceptance cap is checked when the donor accepts, because it changes from
    second to second.
    """
    return (
        match.status == MatchStatus.NOTIFIED
        and blood_request.status == RequestStatus.MATCHING_DONORS
        and donor.verification_status != VerificationStatus.SUSPENDED
    )


def list_donor_requests(
    db: Session,
    donor: Donor,
    *,
    open_only: bool,
    limit: int,
    offset: int,
) -> tuple[list[DonorRequestEntry], int]:
    """The requests sent to a donor, newest first. open_only keeps the ones still in progress."""
    filters: list[ColumnElement[bool]] = [Match.donor_id == donor.id]
    if open_only:
        filters.append(Match.status.in_(OPEN_MATCH_STATUSES))
        filters.append(BloodRequest.status == RequestStatus.MATCHING_DONORS)

    total = (
        db.scalar(
            select(func.count())
            .select_from(Match)
            .join(BloodRequest, BloodRequest.id == Match.request_id)
            .where(*filters)
        )
        or 0
    )
    rows = db.execute(
        select(Match, BloodRequest, Hospital)
        .join(BloodRequest, BloodRequest.id == Match.request_id)
        .join(Hospital, Hospital.id == BloodRequest.hospital_id)
        .where(*filters)
        .order_by(Match.notified_at.desc(), Match.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    entries = [
        DonorRequestEntry(
            match=match,
            request=request,
            hospital=hospital,
            can_respond=can_respond(match, request, donor),
        )
        for match, request, hospital in rows
    ]
    return entries, total


def get_donor_request(db: Session, match: Match, donor: Donor) -> DonorRequestEntry:
    """One request as the donor sees it. The match must already be checked as the donor's own."""
    blood_request = db.get(BloodRequest, match.request_id)
    hospital = db.get(Hospital, blood_request.hospital_id) if blood_request else None
    if blood_request is None or hospital is None:
        raise NotFoundException("Request not found")
    return DonorRequestEntry(
        match=match,
        request=blood_request,
        hospital=hospital,
        can_respond=can_respond(match, blood_request, donor),
    )
