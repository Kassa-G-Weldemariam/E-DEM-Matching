from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models.blood_request import BloodRequest
from app.models.enums import ApprovalStatus, RequestStatus
from app.models.request_status_history import RequestStatusHistory
from scripts import create_test_request as cli
from tests.factories import make_blood_bank, make_hospital


def provider(db):
    return lambda: nullcontext(db)


def requests_in(db) -> list[BloodRequest]:
    return list(db.scalars(select(BloodRequest)))


def test_it_creates_a_pending_request_that_times_out_in_the_given_seconds(db):
    hospital = make_hospital(db)
    before = datetime.now(UTC)
    assert cli.main(["--seconds", "10"], provider(db)) == 0
    after = datetime.now(UTC)

    [blood_request] = requests_in(db)
    assert blood_request.hospital_id == hospital.id
    assert blood_request.status == RequestStatus.PENDING_BLOOD_BANK
    assert (
        before + timedelta(seconds=10)
        <= blood_request.response_deadline
        <= after + timedelta(seconds=10)
    )


def test_it_prints_the_id_of_the_new_request(db, capsys):
    make_hospital(db)
    cli.main(["--seconds", "10"], provider(db))
    [blood_request] = requests_in(db)
    assert str(blood_request.id) in capsys.readouterr().out


def test_the_request_gets_its_first_history_row_like_any_other(db):
    make_hospital(db)
    cli.main([], provider(db))
    rows = list(db.scalars(select(RequestStatusHistory)))
    assert len(rows) == 1
    assert rows[0].from_status is None
    assert rows[0].to_status == RequestStatus.PENDING_BLOOD_BANK


def test_without_a_hospital_it_explains_what_is_missing(db, capsys):
    assert cli.main([], provider(db)) == 1
    assert "approved" in capsys.readouterr().out
    assert db.scalar(select(func.count()).select_from(BloodRequest)) == 0


def test_a_hospital_that_is_not_approved_is_ignored(db):
    make_hospital(db, approval_status=ApprovalStatus.PENDING)
    approved = make_hospital(db)
    assert cli.main([], provider(db)) == 0
    assert requests_in(db)[0].hospital_id == approved.id


def test_a_hospital_whose_blood_bank_is_unavailable_is_skipped(db):
    make_hospital(db, blood_bank=make_blood_bank(db, is_active=False))
    working = make_hospital(db)
    assert cli.main([], provider(db)) == 0
    assert requests_in(db)[0].hospital_id == working.id


@pytest.mark.parametrize("seconds", ["0", "-5", "3601"])
def test_a_number_of_seconds_out_of_range_is_refused(db, seconds):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--seconds", seconds], provider(db))
    assert exit_info.value.code == 2
