"""Create a blood request that times out soon, for trying the worker by hand.

Run from the edem-api folder:

    uv run python -m scripts.create_test_request --seconds 15

It uses the first APPROVED hospital whose blood bank is available (approved and
operating). The request is created exactly as through the API; only its response
deadline is replaced with "now + the seconds you give", so you do not have to wait
10 minutes.
"""

import argparse
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_session_factory
from app.models.enums import ApprovalStatus, BloodType, Urgency
from app.models.hospital import Hospital
from app.schemas.blood_request import BloodRequestCreate
from app.services.blood_banks import get_available_blood_bank
from app.services.blood_requests import create_blood_request

SessionProvider = Callable[[], AbstractContextManager[Session]]


def _seconds(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a whole number") from None
    if not 1 <= number <= 3600:
        raise argparse.ArgumentTypeError("must be between 1 and 3600")
    return number


def _find_hospital(db: Session) -> Hospital | None:
    hospitals = db.scalars(
        select(Hospital)
        .where(Hospital.approval_status == ApprovalStatus.APPROVED)
        .order_by(Hospital.created_at, Hospital.id)
    )
    for hospital in hospitals:
        if get_available_blood_bank(db, hospital.blood_bank_id) is not None:
            return hospital
    return None


def main(
    argv: Sequence[str] | None = None, session_provider: SessionProvider | None = None
) -> int:
    parser = argparse.ArgumentParser(
        description="Create a blood request that times out soon."
    )
    parser.add_argument(
        "--seconds",
        type=_seconds,
        default=15,
        help="seconds until the blood bank timeout (default 15)",
    )
    args = parser.parse_args(argv)

    provider = session_provider or get_session_factory()
    with provider() as db:
        hospital = _find_hospital(db)
        if hospital is None:
            print(
                "No approved hospital with an available blood bank was found. "
                "Create and approve a blood bank and a hospital first."
            )
            return 1

        moment = datetime.now(UTC)
        data = BloodRequestCreate(
            blood_type=BloodType.O_POS,
            units_needed=1,
            urgency=Urgency.URGENT,
            notes="Created by scripts.create_test_request",
        )
        blood_request = create_blood_request(db, hospital, data, now=moment)
        blood_request.response_deadline = moment + timedelta(seconds=args.seconds)
        db.commit()
        print(
            f"Created request {blood_request.id} ({hospital.name}). It times out at {blood_request.response_deadline:%H:%M:%S} UTC"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
