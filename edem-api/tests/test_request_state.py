import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.core.exceptions import InvalidStatusTransitionException
from app.models.enums import RequestStatus as S
from app.models.enums import UserRole
from app.models.request_status_history import RequestStatusHistory
from app.services.request_state import (
    ALLOWED_TRANSITIONS,
    record_initial_status,
    transition_request,
)
from tests.factories import make_blood_request, make_user

LEGAL = [
    (a, b)
    for a, targets in ALLOWED_TRANSITIONS.items()
    for b in sorted(targets, key=lambda s: s.value)
]
ILLEGAL = [(a, b) for a in S for b in S if b not in ALLOWED_TRANSITIONS[a]]
FINAL = [S.FULFILLED, S.UNFULFILLED, S.CANCELLED]

MOMENT = datetime(2026, 11, 20, 10, 30, tzinfo=UTC)


def ids(pairs):
    return [f"{a.value}->{b.value}" for a, b in pairs]


def history(db, blood_request) -> list[RequestStatusHistory]:
    return list(
        db.scalars(
            select(RequestStatusHistory).where(
                RequestStatusHistory.request_id == blood_request.id
            )
        )
    )


def current_status(db, blood_request) -> S:
    db.refresh(blood_request)
    return blood_request.status


# ----------------------------------------------------------- the rules table


def test_allowed_transitions_match_the_state_machine_document():
    assert ALLOWED_TRANSITIONS == {
        S.PENDING_BLOOD_BANK: {S.FULFILLED, S.MATCHING_DONORS, S.CANCELLED},
        S.MATCHING_DONORS: {S.FULFILLED, S.UNFULFILLED, S.CANCELLED},
        S.FULFILLED: set(),
        S.UNFULFILLED: set(),
        S.CANCELLED: set(),
    }


@pytest.mark.parametrize("final", FINAL)
def test_final_statuses_have_no_way_out(final):
    assert ALLOWED_TRANSITIONS[final] == frozenset()


# ------------------------------------------------------------ legal moves


@pytest.mark.parametrize("from_status,to_status", LEGAL, ids=ids(LEGAL))
def test_a_legal_transition_changes_the_status(db, from_status, to_status):
    blood_request = make_blood_request(db, status=from_status)
    assert transition_request(db, blood_request.id, from_status, to_status) is True
    db.commit()
    assert current_status(db, blood_request) == to_status


def test_a_transition_writes_exactly_one_history_row(db):
    blood_request = make_blood_request(db)
    transition_request(
        db,
        blood_request.id,
        S.PENDING_BLOOD_BANK,
        S.MATCHING_DONORS,
        note="Blood bank response timeout",
    )
    db.commit()
    rows = history(db, blood_request)
    assert len(rows) == 1
    assert rows[0].from_status == S.PENDING_BLOOD_BANK
    assert rows[0].to_status == S.MATCHING_DONORS
    assert rows[0].changed_by is None  # the system made the change
    assert rows[0].note == "Blood bank response timeout"


def test_the_history_records_who_made_the_change(db):
    actor = make_user(db, UserRole.BLOOD_BANK)
    blood_request = make_blood_request(db)
    transition_request(
        db,
        blood_request.id,
        S.PENDING_BLOOD_BANK,
        S.MATCHING_DONORS,
        changed_by=actor.id,
    )
    db.commit()
    assert history(db, blood_request)[0].changed_by == actor.id


def test_fulfilled_records_when_it_happened(db):
    blood_request = make_blood_request(db, status=S.MATCHING_DONORS)
    transition_request(db, blood_request.id, S.MATCHING_DONORS, S.FULFILLED, now=MOMENT)
    db.commit()
    db.refresh(blood_request)
    assert blood_request.fulfilled_at == MOMENT
    assert blood_request.cancelled_at is None


def test_cancelled_records_when_it_happened(db):
    blood_request = make_blood_request(db)
    transition_request(
        db, blood_request.id, S.PENDING_BLOOD_BANK, S.CANCELLED, now=MOMENT
    )
    db.commit()
    db.refresh(blood_request)
    assert blood_request.cancelled_at == MOMENT
    assert blood_request.fulfilled_at is None


def test_other_columns_change_in_the_same_atomic_update(db):
    blood_request = make_blood_request(db)
    transition_request(
        db,
        blood_request.id,
        S.PENDING_BLOOD_BANK,
        S.MATCHING_DONORS,
        set_fields={
            "donor_deadline": MOMENT,
            "current_batch": 1,
            "units_from_inventory": 1,
        },
    )
    db.commit()
    db.refresh(blood_request)
    assert blood_request.status == S.MATCHING_DONORS
    assert blood_request.donor_deadline == MOMENT
    assert blood_request.current_batch == 1
    assert blood_request.units_from_inventory == 1


# ---------------------------------------------------------- losing a race


def test_a_lost_race_returns_false_and_changes_nothing(db):
    blood_request = make_blood_request(
        db, status=S.MATCHING_DONORS
    )  # someone already moved it
    assert (
        transition_request(
            db, blood_request.id, S.PENDING_BLOOD_BANK, S.MATCHING_DONORS
        )
        is False
    )
    db.commit()
    assert current_status(db, blood_request) == S.MATCHING_DONORS
    assert history(db, blood_request) == []


def test_the_same_transition_cannot_happen_twice(db):
    blood_request = make_blood_request(db)
    assert (
        transition_request(
            db, blood_request.id, S.PENDING_BLOOD_BANK, S.MATCHING_DONORS
        )
        is True
    )
    assert (
        transition_request(
            db, blood_request.id, S.PENDING_BLOOD_BANK, S.MATCHING_DONORS
        )
        is False
    )
    db.commit()
    assert len(history(db, blood_request)) == 1


def test_a_request_that_does_not_exist_returns_false(db):
    assert (
        transition_request(db, uuid.uuid4(), S.PENDING_BLOOD_BANK, S.MATCHING_DONORS)
        is False
    )
    assert db.scalar(select(func.count()).select_from(RequestStatusHistory)) == 0


def test_only_the_targeted_request_changes(db):
    target = make_blood_request(db)
    bystander = make_blood_request(db)
    transition_request(db, target.id, S.PENDING_BLOOD_BANK, S.MATCHING_DONORS)
    db.commit()
    assert current_status(db, target) == S.MATCHING_DONORS
    assert current_status(db, bystander) == S.PENDING_BLOOD_BANK
    assert history(db, bystander) == []


# ----------------------------------------------------------- illegal moves


@pytest.mark.parametrize("from_status,to_status", ILLEGAL, ids=ids(ILLEGAL))
def test_an_illegal_transition_is_refused_and_changes_nothing(
    db, from_status, to_status
):
    blood_request = make_blood_request(db, status=from_status)
    with pytest.raises(InvalidStatusTransitionException):
        transition_request(db, blood_request.id, from_status, to_status)
    db.commit()
    assert current_status(db, blood_request) == from_status
    assert history(db, blood_request) == []


@pytest.mark.parametrize("field", ["status", "id", "hospital_id", "not_a_column"])
def test_columns_that_must_not_change_are_refused(db, field):
    blood_request = make_blood_request(db)
    with pytest.raises(ValueError):
        transition_request(
            db,
            blood_request.id,
            S.PENDING_BLOOD_BANK,
            S.MATCHING_DONORS,
            set_fields={field: "anything"},
        )
    assert current_status(db, blood_request) == S.PENDING_BLOOD_BANK


# ------------------------------------------------------ the caller's commit


def test_a_rollback_undoes_the_status_change_and_its_history_together(db):
    blood_request = make_blood_request(db)
    assert (
        transition_request(
            db, blood_request.id, S.PENDING_BLOOD_BANK, S.MATCHING_DONORS
        )
        is True
    )
    db.rollback()
    assert current_status(db, blood_request) == S.PENDING_BLOOD_BANK
    assert history(db, blood_request) == []


# --------------------------------------------------------- the first history row


def test_the_first_history_row_has_no_previous_status(db):
    creator = make_user(db, UserRole.HOSPITAL)
    blood_request = make_blood_request(db)
    record_initial_status(
        db, blood_request, changed_by=creator.id, note="Request created"
    )
    db.commit()
    rows = history(db, blood_request)
    assert len(rows) == 1
    assert rows[0].from_status is None
    assert rows[0].to_status == S.PENDING_BLOOD_BANK
    assert rows[0].changed_by == creator.id
    assert rows[0].note == "Request created"
