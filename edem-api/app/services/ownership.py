"""Ownership checks: does this record belong to the person asking for it?

Order of checks in a route:
  1. login
  2. role
  3. approval
  4. ownership

A record that does not exist gives 404 NOT_FOUND.
A record that exists but belongs to someone else gives 403 FORBIDDEN.
"""

import uuid
from typing import TypeVar

from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.blood_bank import BloodBank
from app.models.blood_request import BloodRequest
from app.models.donor import Donor
from app.models.hospital import Hospital
from app.models.match import Match

T = TypeVar("T")


def _get_or_404[T](db: Session, model: type[T], object_id: uuid.UUID, label: str) -> T:
    found = db.get(model, object_id)
    if found is None:
        raise NotFoundException(f"{label} not found")
    return found


def _not_yours(label: str) -> ForbiddenException:
    return ForbiddenException(f"You do not have permission to access this {label}")


def get_request_for_hospital(
    db: Session, request_id: uuid.UUID, hospital: Hospital
) -> BloodRequest:
    """A blood request that the given hospital created."""
    blood_request = _get_or_404(db, BloodRequest, request_id, "Blood request")
    if blood_request.hospital_id != hospital.id:
        raise _not_yours("blood request")
    return blood_request


def get_request_for_blood_bank(
    db: Session, request_id: uuid.UUID, blood_bank: BloodBank
) -> BloodRequest:
    """A blood request that is assigned to the given blood bank."""
    blood_request = _get_or_404(db, BloodRequest, request_id, "Blood request")
    if blood_request.blood_bank_id != blood_bank.id:
        raise _not_yours("blood request")
    return blood_request


def get_donor_for_blood_bank(
    db: Session, donor_id: uuid.UUID, blood_bank: BloodBank
) -> Donor:
    """A donor that is registered under the given blood bank."""
    donor = _get_or_404(db, Donor, donor_id, "Donor")
    if donor.blood_bank_id != blood_bank.id:
        raise _not_yours("donor")
    return donor


def get_match_for_donor(db: Session, match_id: uuid.UUID, donor: Donor) -> Match:
    """A match that belongs to the given donor."""
    match = _get_or_404(db, Match, match_id, "Match")
    if match.donor_id != donor.id:
        raise _not_yours("match")
    return match


def get_match_for_hospital(
    db: Session, request_id: uuid.UUID, match_id: uuid.UUID, hospital: Hospital
) -> tuple[BloodRequest, Match]:
    """A match of one of the hospital's own requests.

    Both ids from the URL are checked together: the match must belong to THAT request,
    and the request must belong to the hospital.
    """
    blood_request = get_request_for_hospital(db, request_id, hospital)
    match = _get_or_404(db, Match, match_id, "Match")
    if match.request_id != blood_request.id:
        # The match exists, but not as part of this request: from here it does not exist.
        raise NotFoundException("Match not found")
    return blood_request, match
