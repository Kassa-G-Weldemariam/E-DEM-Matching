"""Turns query results into response models (and decides what each reader may see)."""

from app.schemas.blood_request import (
    DonorRequestItem,
    DonorRequestSummary,
    HistoryItem,
    HospitalContact,
    MatchedDonor,
    RequestMatchItem,
)
from app.services.request_queries import (
    CONTACT_VISIBLE_MATCH_STATUSES,
    DonorRequestEntry,
    HistoryEntry,
    MatchEntry,
)


def history_item(entry: HistoryEntry) -> HistoryItem:
    row = entry.row
    return HistoryItem(
        from_status=row.from_status,
        to_status=row.to_status,
        actor=entry.actor,
        note=row.note,
        created_at=row.created_at,
    )


def match_item(entry: MatchEntry) -> RequestMatchItem:
    match = entry.match
    in_person = match.status in CONTACT_VISIBLE_MATCH_STATUSES
    return RequestMatchItem(
        match_id=match.id,
        batch_number=match.batch_number,
        status=match.status,
        distance_km=match.distance_km,
        notified_at=match.notified_at,
        responded_at=match.responded_at,
        arrived_at=match.arrived_at,
        donated_at=match.donated_at,
        donor=(
            MatchedDonor(
                full_name=entry.donor.full_name,
                blood_type=entry.donor.blood_type,
                phone=entry.phone,
            )
            if in_person
            else None
        ),
    )


def donor_request_item(entry: DonorRequestEntry) -> DonorRequestItem:
    match = entry.match
    return DonorRequestItem(
        match_id=match.id,
        match_status=match.status,
        distance_km=match.distance_km,
        notified_at=match.notified_at,
        responded_at=match.responded_at,
        can_respond=entry.can_respond,
        request=DonorRequestSummary.model_validate(entry.request),
        hospital=HospitalContact.model_validate(entry.hospital),
    )
