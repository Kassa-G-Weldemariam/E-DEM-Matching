from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import RequestStatus as S
from app.services.request_state import record_initial_status, transition_request
from scripts import show_requests as cli
from tests.factories import make_blood_request, make_hospital

NOW = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)


def provider(db):
    return lambda: nullcontext(db)


# ------------------------------------------------------- the countdown text


def test_a_pending_request_shows_the_seconds_left():
    assert (
        cli.time_left_text(S.PENDING_BLOOD_BANK, NOW + timedelta(seconds=8), NOW)
        == "in 8s"
    )


def test_a_distant_deadline_is_shown_in_minutes():
    assert (
        cli.time_left_text(S.PENDING_BLOOD_BANK, NOW + timedelta(minutes=9), NOW)
        == "in 9 min"
    )


def test_a_deadline_that_has_passed_shows_how_late_it_is():
    assert (
        cli.time_left_text(S.PENDING_BLOOD_BANK, NOW - timedelta(seconds=31), NOW)
        == "overdue 31s"
    )


def test_a_request_without_a_deadline_shows_a_dash():
    assert cli.time_left_text(S.PENDING_BLOOD_BANK, None, NOW) == "-"


@pytest.mark.parametrize(
    "status", [S.MATCHING_DONORS, S.FULFILLED, S.UNFULFILLED, S.CANCELLED]
)
def test_only_pending_requests_have_a_countdown(status):
    assert cli.time_left_text(status, NOW - timedelta(minutes=5), NOW) == "-"


# ------------------------------------------------------------- the table


def test_requests_are_listed_newest_first_with_their_status_and_short_id(db):
    hospital = make_hospital(db)
    older = make_blood_request(
        db, hospital=hospital, response_deadline=NOW + timedelta(minutes=5)
    )
    newer = make_blood_request(
        db, hospital=hospital, response_deadline=NOW - timedelta(seconds=40)
    )
    older.created_at = NOW - timedelta(
        minutes=10
    )  # created_at is the same inside one test transaction
    newer.created_at = NOW - timedelta(minutes=1)
    db.commit()

    text = "\n".join(cli.build_lines(db, NOW))
    assert text.index(str(newer.id)[:8]) < text.index(str(older.id)[:8])
    assert "pending_blood_bank" in text
    assert "overdue 40s" in text
    assert "in 5 min" in text


def test_the_number_of_history_rows_is_shown(db):
    blood_request = make_blood_request(db, hospital=make_hospital(db))
    record_initial_status(db, blood_request)
    transition_request(db, blood_request.id, S.PENDING_BLOOD_BANK, S.MATCHING_DONORS)
    db.commit()

    request_line = cli.build_lines(db, NOW)[1]
    assert str(blood_request.id)[:8] in request_line
    assert "matching_donors" in request_line
    assert request_line.rstrip().endswith("2")


def test_an_empty_database_says_so(db):
    assert cli.build_lines(db, NOW) == ["No blood requests yet"]


def test_the_script_prints_the_table_and_succeeds(db, capsys):
    make_blood_request(db, hospital=make_hospital(db))
    assert cli.main([], provider(db)) == 0
    assert "pending_blood_bank" in capsys.readouterr().out
