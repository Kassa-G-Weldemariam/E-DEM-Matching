"""Show the latest blood requests and how much time is left on their deadlines.

Run from the edem-api folder:

    uv run python -m scripts.show_requests            # once
    uv run python -m scripts.show_requests --watch    # refresh every 2 seconds, Ctrl+C to stop
"""

import argparse
import time
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_session_factory
from app.models.blood_request import BloodRequest
from app.models.enums import RequestStatus
from app.models.request_status_history import RequestStatusHistory

SessionProvider = Callable[[], AbstractContextManager[Session]]

ROW_LIMIT = 10
REFRESH_SECONDS = 2


def _short(seconds: int) -> str:
    return f"{seconds}s" if seconds < 120 else f"{seconds // 60} min"


def time_left_text(
    status: RequestStatus, deadline: datetime | None, now: datetime
) -> str:
    """Only a request that is waiting for its blood bank has a deadline that matters."""
    if status != RequestStatus.PENDING_BLOOD_BANK or deadline is None:
        return "-"
    seconds = int((deadline - now).total_seconds())
    return f"in {_short(seconds)}" if seconds >= 0 else f"overdue {_short(-seconds)}"


def build_lines(db: Session, now: datetime, limit: int = ROW_LIMIT) -> list[str]:
    requests = list(
        db.scalars(
            select(BloodRequest)
            .order_by(BloodRequest.created_at.desc(), BloodRequest.id)
            .limit(limit)
        )
    )
    if not requests:
        return ["No blood requests yet"]

    rows = db.execute(
        select(RequestStatusHistory.request_id, func.count())
        .where(
            RequestStatusHistory.request_id.in_([request.id for request in requests])
        )
        .group_by(RequestStatusHistory.request_id)
    ).all()
    history_counts = {row[0]: row[1] for row in rows}

    lines = [
        f"{'ID':<10}{'STATUS':<22}{'URGENCY':<10}{'RESPONSE DEADLINE':<20}HISTORY ROWS"
    ]
    for request in requests:
        deadline_text = time_left_text(request.status, request.response_deadline, now)
        lines.append(
            f"{str(request.id)[:8]:<10}{request.status.value:<22}{request.urgency.value:<10}"
            f"{deadline_text:<20}{history_counts.get(request.id, 0)}"
        )
    return lines


def main(
    argv: Sequence[str] | None = None, session_provider: SessionProvider | None = None
) -> int:
    parser = argparse.ArgumentParser(description="Show the latest blood requests.")
    parser.add_argument(
        "--watch", action="store_true", help="refresh every 2 seconds until Ctrl+C"
    )
    args = parser.parse_args(argv)

    provider = session_provider or get_session_factory()
    try:
        while True:
            with provider() as db:
                lines = build_lines(db, datetime.now(UTC))
            if args.watch:
                print(f"\n--- {datetime.now(UTC):%H:%M:%S} UTC ---")
            print("\n".join(lines))
            if not args.watch:
                return 0
            time.sleep(REFRESH_SECONDS)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
