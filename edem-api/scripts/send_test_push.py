"""Send a test push notification to every device a user has registered.

Run from the edem-api folder:

    uv run python -m scripts.send_test_push --email donor@edem-demo.org
    uv run python -m scripts.send_test_push --email donor@edem-demo.org --delay 20
    uv run python -m scripts.send_test_push --email donor@edem-demo.org --ttl 30
    uv run python -m scripts.send_test_push --email donor@edem-demo.org --dry-run

--delay waits before sending, so you can lock the phone or close the app first.
--ttl is how many seconds Firebase keeps the message if the phone is offline.
--dry-run only lists the devices. It refuses to run when ENVIRONMENT=production.
"""

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models.device_token import DeviceToken
from app.models.user import User
from app.services.push import (
    DEFAULT_TTL,
    PushClient,
    PushNotConfiguredError,
    get_push_client,
    mask_token,
    send_push_to_user,
)

SessionProvider = Callable[[], AbstractContextManager[Session]]

DEFAULT_TITLE = "E-DEM test"
DEFAULT_BODY = "If you can read this, push notifications work on this phone."
MAX_DELAY_SECONDS = 300
MAX_TTL_SECONDS = 3600


def _bounded_int(name: str, maximum: int, minimum: int = 0) -> Callable[[str], int]:
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError("must be a whole number") from None
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(
                f"{name} must be between {minimum} and {maximum}"
            )
        return number

    return parse


def main(
    argv: Sequence[str] | None = None,
    session_provider: SessionProvider | None = None,
    client: PushClient | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    parser = argparse.ArgumentParser(
        description="Send a test push notification to a user's devices."
    )
    parser.add_argument("--email", required=True, help="login email of the user")
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--body", default=DEFAULT_BODY)
    parser.add_argument(
        "--delay",
        type=_bounded_int("delay", MAX_DELAY_SECONDS),
        default=0,
        help="seconds to wait before sending",
    )
    parser.add_argument(
        "--ttl",
        type=_bounded_int("ttl", MAX_TTL_SECONDS, minimum=1),
        default=None,
        help=f"seconds Firebase keeps the message when the phone is offline (default {int(DEFAULT_TTL.total_seconds())})",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="list the devices and send nothing"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if settings.ENVIRONMENT == "production":
        print(
            "Error: this test helper refuses to run when ENVIRONMENT=production.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Database: {make_url(settings.active_database_url).render_as_string(hide_password=True)}"
    )

    provider = session_provider or get_session_factory()
    with provider() as db:
        user = db.scalar(
            select(User).where(func.lower(User.email) == args.email.strip().lower())
        )
        if user is None:
            print(f"No user with the email {args.email}")
            return 1

        devices = list(
            db.scalars(
                select(DeviceToken)
                .where(DeviceToken.user_id == user.id)
                .order_by(DeviceToken.updated_at.desc(), DeviceToken.id)
            )
        )
        if not devices:
            print(
                f"{user.email} has no registered devices. Register one from the app (POST /v1/devices) first"
            )
            return 1

        print(f"{'DEVICE':<10}{'PLATFORM':<10}{'TOKEN':<14}LAST SEEN")
        for device in devices:
            platform = device.platform.value if device.platform else "-"
            seen = f"{device.updated_at:%Y-%m-%d %H:%M} UTC"
            print(
                f"{str(device.id)[:8]:<10}{platform:<10}{mask_token(device.token):<14}{seen}"
            )

        if args.dry_run:
            print("Dry run: nothing was sent")
            return 0

        try:
            sender = client or get_push_client()
        except PushNotConfiguredError as error:
            print(f"Error: {error}", file=sys.stderr)
            return 1

        if args.delay:
            print(
                f"Sending in {args.delay} seconds. Lock the phone or close the app now..."
            )
            sleep(args.delay)

        sent_at = datetime.now(UTC)
        report = send_push_to_user(
            db,
            user.id,
            args.title,
            args.body,
            data={
                "type": "test",
                "sent_at": sent_at.isoformat(timespec="milliseconds"),
            },
            client=sender,
            ttl=timedelta(seconds=args.ttl) if args.ttl else DEFAULT_TTL,
        )

    print(
        f"Sent at {sent_at:%H:%M:%S} UTC ({sent_at.astimezone():%H:%M:%S} on this computer)"
    )
    for result in report.results:
        print(
            f"{result.outcome.value.upper():<12}{result.token_start:<14}{result.detail}"
        )
    print(
        f"{report.sent} sent, {report.removed} removed, "
        f"{report.retryable} to retry later, {report.failed} failed"
    )
    return 0 if report.sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
