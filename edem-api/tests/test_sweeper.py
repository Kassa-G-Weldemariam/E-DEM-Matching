import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.models.blood_request import BloodRequest
from app.models.enums import RequestStatus as S
from app.models.request_status_history import RequestStatusHistory
from app.services import sweeper
from app.services.sweeper import (
    SweepResult,
    process_expired_response_deadlines,
    run_sweep,
)
from tests.factories import make_blood_request, make_hospital

NOW = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)


@pytest.fixture()
def hospital(db):
    return make_hospital(db)


@pytest.fixture()
def matching_calls(monkeypatch):
    """Replaces the matching placeholder and records which requests it was started for."""
    calls = []
    monkeypatch.setattr(
        "app.services.blood_requests.start_matching",
        lambda db, request: calls.append(request.id),
    )
    return calls


def expired(db, hospital, minutes_ago=5, **options):
    """A pending request whose deadline passed `minutes_ago` minutes before NOW."""
    return make_blood_request(
        db,
        hospital=hospital,
        response_deadline=NOW - timedelta(minutes=minutes_ago),
        **options,
    )


def status_of(db, blood_request) -> S:
    db.refresh(blood_request)
    return blood_request.status


def history_of(db, blood_request) -> list[RequestStatusHistory]:
    return list(
        db.scalars(
            select(RequestStatusHistory).where(
                RequestStatusHistory.request_id == blood_request.id
            )
        )
    )


# ------------------------------------------------------------ the timeout


def test_an_expired_request_moves_to_matching_donors(db, hospital, matching_calls):
    blood_request = expired(db, hospital)
    assert process_expired_response_deadlines(db, now=NOW) == 1
    assert status_of(db, blood_request) == S.MATCHING_DONORS


def test_the_timeout_is_recorded_in_the_history_by_the_system(
    db, hospital, matching_calls
):
    blood_request = expired(db, hospital)
    process_expired_response_deadlines(db, now=NOW)
    rows = history_of(db, blood_request)
    assert len(rows) == 1
    assert rows[0].from_status == S.PENDING_BLOOD_BANK
    assert rows[0].to_status == S.MATCHING_DONORS
    assert rows[0].changed_by is None
    assert rows[0].note == "Blood bank response timeout"


def test_matching_is_started_for_the_request_that_timed_out(
    db, hospital, matching_calls
):
    blood_request = expired(db, hospital)
    process_expired_response_deadlines(db, now=NOW)
    assert matching_calls == [blood_request.id]


def test_a_request_exactly_at_its_deadline_has_timed_out(db, hospital, matching_calls):
    blood_request = make_blood_request(db, hospital=hospital, response_deadline=NOW)
    assert process_expired_response_deadlines(db, now=NOW) == 1
    assert status_of(db, blood_request) == S.MATCHING_DONORS


def test_the_deadline_itself_is_kept_after_the_timeout(db, hospital, matching_calls):
    blood_request = expired(db, hospital, minutes_ago=5)
    process_expired_response_deadlines(db, now=NOW)
    db.refresh(blood_request)
    assert blood_request.response_deadline == NOW - timedelta(minutes=5)


# ------------------------------------------------------ what it leaves alone


def test_a_request_that_has_not_expired_is_left_alone(db, hospital, matching_calls):
    blood_request = make_blood_request(
        db, hospital=hospital, response_deadline=NOW + timedelta(seconds=1)
    )
    assert process_expired_response_deadlines(db, now=NOW) == 0
    assert status_of(db, blood_request) == S.PENDING_BLOOD_BANK
    assert history_of(db, blood_request) == []
    assert matching_calls == []


def test_a_pending_request_without_a_deadline_is_left_alone(
    db, hospital, matching_calls
):
    blood_request = make_blood_request(db, hospital=hospital, response_deadline=None)
    assert process_expired_response_deadlines(db, now=NOW) == 0
    assert status_of(db, blood_request) == S.PENDING_BLOOD_BANK


@pytest.mark.parametrize(
    "other_status", [S.MATCHING_DONORS, S.FULFILLED, S.UNFULFILLED, S.CANCELLED]
)
def test_requests_in_other_statuses_are_left_alone(
    db, hospital, matching_calls, other_status
):
    blood_request = expired(db, hospital, status=other_status)
    assert process_expired_response_deadlines(db, now=NOW) == 0
    assert status_of(db, blood_request) == other_status
    assert history_of(db, blood_request) == []
    assert matching_calls == []


def test_only_expired_requests_are_processed(db, hospital, matching_calls):
    overdue = [expired(db, hospital, minutes_ago=minutes) for minutes in (1, 2, 3)]
    waiting = [
        make_blood_request(
            db, hospital=hospital, response_deadline=NOW + timedelta(minutes=minutes)
        )
        for minutes in (1, 2)
    ]
    assert process_expired_response_deadlines(db, now=NOW) == 3
    assert all(status_of(db, request) == S.MATCHING_DONORS for request in overdue)
    assert all(status_of(db, request) == S.PENDING_BLOOD_BANK for request in waiting)
    assert set(matching_calls) == {request.id for request in overdue}


# ----------------------------------------------------- running more than once


def test_running_twice_does_not_process_a_request_twice(db, hospital, matching_calls):
    blood_request = expired(db, hospital)
    assert process_expired_response_deadlines(db, now=NOW) == 1
    assert process_expired_response_deadlines(db, now=NOW) == 0
    assert len(history_of(db, blood_request)) == 1
    assert matching_calls == [blood_request.id]


def test_requests_that_expired_while_the_worker_was_down_are_all_caught(
    db, hospital, matching_calls
):
    overdue = [
        expired(db, hospital, minutes_ago=minutes)
        for minutes in (600, 300, 120, 60, 30)
    ]
    assert process_expired_response_deadlines(db, now=NOW) == 5
    assert all(status_of(db, request) == S.MATCHING_DONORS for request in overdue)


def test_the_oldest_deadlines_go_first_and_the_limit_is_respected(
    db, hospital, matching_calls
):
    oldest_first = [
        expired(db, hospital, minutes_ago=minutes) for minutes in (50, 40, 30, 20, 10)
    ]

    assert process_expired_response_deadlines(db, now=NOW, limit=2) == 2
    assert [status_of(db, request) for request in oldest_first] == [
        S.MATCHING_DONORS,
        S.MATCHING_DONORS,
        S.PENDING_BLOOD_BANK,
        S.PENDING_BLOOD_BANK,
        S.PENDING_BLOOD_BANK,
    ]

    assert process_expired_response_deadlines(db, now=NOW, limit=2) == 2
    assert process_expired_response_deadlines(db, now=NOW, limit=2) == 1
    assert process_expired_response_deadlines(db, now=NOW, limit=2) == 0
    assert all(status_of(db, request) == S.MATCHING_DONORS for request in oldest_first)


# --------------------------------------------------- races and failures


def test_a_request_cancelled_at_the_last_moment_is_not_touched(
    db, hospital, matching_calls, monkeypatch
):
    blood_request = expired(db, hospital)
    real_transition = sweeper.transition_request

    def hospital_cancels_first(session, request_id, from_status, to_status, **kwargs):
        session.execute(
            update(BloodRequest)
            .where(BloodRequest.id == request_id)
            .values(status=S.CANCELLED)
        )
        session.commit()
        return real_transition(session, request_id, from_status, to_status, **kwargs)

    monkeypatch.setattr(sweeper, "transition_request", hospital_cancels_first)

    assert process_expired_response_deadlines(db, now=NOW) == 0
    assert status_of(db, blood_request) == S.CANCELLED
    assert history_of(db, blood_request) == []
    assert matching_calls == []


def test_a_matching_failure_does_not_undo_the_timeout(db, hospital, monkeypatch):
    def broken(session, request):
        raise RuntimeError("matching crashed")

    monkeypatch.setattr("app.services.blood_requests.start_matching", broken)
    first, second = (
        expired(db, hospital, minutes_ago=10),
        expired(db, hospital, minutes_ago=5),
    )

    assert process_expired_response_deadlines(db, now=NOW) == 2
    assert status_of(db, first) == S.MATCHING_DONORS
    assert status_of(db, second) == S.MATCHING_DONORS


def test_an_unexpected_error_on_one_request_does_not_stop_the_others(
    db, hospital, matching_calls, monkeypatch, caplog
):
    broken_one = expired(
        db, hospital, minutes_ago=10
    )  # the oldest, so it is handled first
    healthy_one = expired(db, hospital, minutes_ago=5)
    real_transition = sweeper.transition_request

    def fails_for_one(session, request_id, from_status, to_status, **kwargs):
        if request_id == broken_one.id:
            raise RuntimeError("database hiccup")
        return real_transition(session, request_id, from_status, to_status, **kwargs)

    monkeypatch.setattr(sweeper, "transition_request", fails_for_one)

    with caplog.at_level(logging.ERROR, logger="app.sweeper"):
        assert process_expired_response_deadlines(db, now=NOW) == 1

    assert (
        status_of(db, broken_one) == S.PENDING_BLOOD_BANK
    )  # left alone, to be retried next sweep
    assert status_of(db, healthy_one) == S.MATCHING_DONORS
    assert matching_calls == [healthy_one.id]
    errors = [record for record in caplog.records if record.name == "app.sweeper"]
    assert len(errors) == 1 and errors[0].exc_info is not None


# ------------------------------------------------------------ run_sweep


def test_run_sweep_reports_how_many_timeouts_it_processed(db, hospital, matching_calls):
    expired(db, hospital, minutes_ago=3)
    expired(db, hospital, minutes_ago=2)
    assert run_sweep(db, now=NOW) == SweepResult(response_timeouts=2)


def test_run_sweep_with_nothing_to_do_reports_zero(db, matching_calls):
    assert run_sweep(db, now=NOW) == SweepResult(response_timeouts=0)


def test_the_default_time_is_the_current_time(db, hospital, matching_calls):
    blood_request = make_blood_request(
        db,
        hospital=hospital,
        response_deadline=datetime.now(UTC) - timedelta(minutes=1),
    )
    assert process_expired_response_deadlines(db) == 1
    assert status_of(db, blood_request) == S.MATCHING_DONORS
