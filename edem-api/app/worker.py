"""Background worker. Start it with:

    uv run arq app.worker.WorkerSettings

It runs the deadline sweep on a schedule. PostgreSQL holds the deadlines, so the
worker can be stopped, crashed or restarted, and Redis can be emptied, without
losing a timer: the next sweep simply finds whatever is overdue.
"""

import asyncio
import logging
import sys
from dataclasses import asdict
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import get_engine, get_session_factory
from app.services.sweeper import SweepResult, run_sweep

logger = logging.getLogger("app.worker")

JOB_TIMEOUT_SECONDS = 60


def sweep_seconds(interval: int) -> set[int]:
    """The seconds of every minute at which the sweep runs, for a given interval.

    The interval must divide 60 evenly, so the runs are evenly spaced
    (15 gives 0, 15, 30 and 45).
    """
    if not 1 <= interval <= 60 or 60 % interval != 0:
        raise ValueError(
            "SWEEPER_INTERVAL_SECONDS must divide 60 evenly "
            f"(1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30 or 60), got {interval}"
        )
    return set(range(0, 60, interval))


def _sweep_once() -> SweepResult:
    with get_session_factory()() as db:
        return run_sweep(db)


async def sweep_deadlines(ctx: dict[str, Any]) -> dict[str, int]:
    """One pass over everything that can time out. Returns plain numbers for the log."""
    result = await asyncio.to_thread(_sweep_once)
    if result.response_timeouts:
        logger.info("Sweep finished: %s", result)
    return asdict(result)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    setup_logging(settings)  # copy the call your main.py uses if this differs
    logger.info(
        "Worker started. Sweeping every %s seconds", settings.SWEEPER_INTERVAL_SECONDS
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    get_engine().dispose()
    logger.info("Worker stopped")


class WorkerSettings:
    functions: ClassVar[list[Any]] = [sweep_deadlines]
    cron_jobs: ClassVar[list[Any]] = [
        cron(
            sweep_deadlines,
            second=sweep_seconds(get_settings().SWEEPER_INTERVAL_SECONDS),
            run_at_startup=True,  # catch up at once after downtime
            unique=True,  # one run per slot, even with several workers
            timeout=JOB_TIMEOUT_SECONDS,
        )
    ]
    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(
        get_settings().REDIS_URL
    )
    on_startup: ClassVar[Any] = startup
    on_shutdown: ClassVar[Any] = shutdown
    job_timeout: ClassVar[int] = JOB_TIMEOUT_SECONDS
    # ARQ's signal handlers do not work on Windows. Ctrl+C still stops the worker there.
    handle_signals: ClassVar[bool] = sys.platform != "win32"
