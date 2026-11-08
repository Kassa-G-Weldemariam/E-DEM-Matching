import sys
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.models.enums import RequestStatus as S
from app.worker import WorkerSettings, sweep_deadlines, sweep_seconds
from tests.factories import make_blood_request, make_hospital

# ----------------------------------------------------------- the schedule


@pytest.mark.parametrize(
    "interval,expected",
    [
        (15, {0, 15, 30, 45}),
        (30, {0, 30}),
        (60, {0}),
        (10, {0, 10, 20, 30, 40, 50}),
        (1, set(range(60))),
    ],
)
def test_the_sweep_runs_at_evenly_spaced_seconds(interval, expected):
    assert sweep_seconds(interval) == expected


@pytest.mark.parametrize("interval", [0, -5, 7, 25, 45, 61])
def test_an_interval_that_does_not_divide_a_minute_is_refused(interval):
    with pytest.raises(ValueError, match="SWEEPER_INTERVAL_SECONDS"):
        sweep_seconds(interval)


# ------------------------------------------------------- the configuration


def test_the_worker_has_the_sweep_function_registered():
    assert sweep_deadlines in WorkerSettings.functions


def test_the_sweep_is_scheduled_from_the_settings():
    job = WorkerSettings.cron_jobs[0]
    assert job.coroutine is sweep_deadlines
    assert job.second == sweep_seconds(get_settings().SWEEPER_INTERVAL_SECONDS)


def test_the_sweep_also_runs_once_at_startup():
    assert WorkerSettings.cron_jobs[0].run_at_startup is True


def test_the_sweep_is_unique_across_workers():
    assert WorkerSettings.cron_jobs[0].unique is True


def test_redis_comes_from_the_settings():
    expected = RedisSettings.from_dsn(get_settings().REDIS_URL)
    actual = WorkerSettings.redis_settings
    assert (actual.host, actual.port, actual.database) == (
        expected.host,
        expected.port,
        expected.database,
    )


def test_signal_handling_is_switched_off_only_on_windows():
    assert WorkerSettings.handle_signals is (sys.platform != "win32")


# ---------------------------------------------------------------- the job


@pytest.fixture()
def worker_db(db, monkeypatch):
    """Makes the job use the test session, and replaces the matching placeholder."""
    monkeypatch.setattr(
        "app.worker.get_session_factory", lambda: lambda: nullcontext(db)
    )
    monkeypatch.setattr(
        "app.services.blood_requests.start_matching", lambda session, request: None
    )
    return db


async def test_the_job_moves_an_expired_request_and_reports_it(worker_db):
    blood_request = make_blood_request(
        worker_db,
        hospital=make_hospital(worker_db),
        response_deadline=datetime.now(UTC) - timedelta(minutes=1),
    )
    result = await sweep_deadlines({})
    assert result == {"response_timeouts": 1}
    worker_db.refresh(blood_request)
    assert blood_request.status == S.MATCHING_DONORS


async def test_the_job_leaves_a_request_that_has_not_expired(worker_db):
    blood_request = make_blood_request(
        worker_db,
        hospital=make_hospital(worker_db),
        response_deadline=datetime.now(UTC) + timedelta(minutes=5),
    )
    assert await sweep_deadlines({}) == {"response_timeouts": 0}
    worker_db.refresh(blood_request)
    assert blood_request.status == S.PENDING_BLOOD_BANK


async def test_the_job_with_nothing_to_do_reports_zero(worker_db):
    assert await sweep_deadlines({}) == {"response_timeouts": 0}
