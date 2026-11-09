"""Sending push notifications through Firebase Cloud Messaging (FCM).

Usage from other code:

    report = send_push_to_user(db, user.id, "Urgent: O+ needed", "Tikur Anbessa Hospital", data={"type": "blood_request"})

Dead tokens (Firebase says the app was uninstalled or the token is invalid) are deleted
automatically. Temporary problems keep the token and are reported as retryable: retrying
is added in Phase 3 (an ARQ job).
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from functools import lru_cache
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.device_token import DeviceToken

logger = logging.getLogger("app.push")

# Must match the notification channel the mobile app creates.
EMERGENCY_CHANNEL_ID = "emergency_requests"

# An emergency request that is hours old is worse than none, so Firebase drops late messages.
DEFAULT_TTL = timedelta(minutes=10)

_RESERVED_DATA_KEYS = frozenset({"from", "notification", "message_type"})
_RESERVED_DATA_PREFIXES = ("google", "gcm")


class PushNotConfiguredError(Exception):
    """FIREBASE_CREDENTIALS_PATH is not set."""


class PushOutcome(str, Enum):
    SENT = "sent"
    DEAD_TOKEN = "dead_token"  # the token is no longer valid: it is deleted
    RETRYABLE = "retryable"  # a temporary problem: the token is kept
    FAILED = "failed"  # anything else: the token is kept


@dataclass(frozen=True)
class TokenResult:
    device_id: uuid.UUID
    token_start: str
    platform: str | None
    outcome: PushOutcome
    detail: str


@dataclass
class PushReport:
    results: list[TokenResult] = field(default_factory=list)

    def _count(self, outcome: PushOutcome) -> int:
        return sum(1 for result in self.results if result.outcome == outcome)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def sent(self) -> int:
        return self._count(PushOutcome.SENT)

    @property
    def removed(self) -> int:
        return self._count(PushOutcome.DEAD_TOKEN)

    @property
    def retryable(self) -> int:
        return self._count(PushOutcome.RETRYABLE)

    @property
    def failed(self) -> int:
        return self._count(PushOutcome.FAILED)


class PushClient(Protocol):
    def send(
        self, token: str, title: str, body: str, data: dict[str, str], *, ttl: timedelta
    ) -> None:
        """Send one notification. Raises when Firebase refuses or cannot be reached."""


def mask_token(token: str) -> str:
    """Tokens are credentials for one phone: show only the start, never the whole token."""
    return token[:8] + "..."


def clean_data(data: dict[str, Any] | None) -> dict[str, str]:
    """FCM data payloads are string-to-string. Values are converted, None values are dropped."""
    cleaned: dict[str, str] = {}
    for key, value in (data or {}).items():
        lowered = key.lower()
        if lowered in _RESERVED_DATA_KEYS or lowered.startswith(
            _RESERVED_DATA_PREFIXES
        ):
            raise ValueError(f"'{key}' is a reserved word in FCM data payloads")
        if value is not None:
            cleaned[key] = str(value)
    return cleaned


def build_message(
    token: str, title: str, body: str, data: dict[str, str], ttl: timedelta
) -> Any:
    """The FCM message: high priority, a time limit, and the emergency channel."""
    from firebase_admin import messaging

    return messaging.Message(
        token=token,
        notification=messaging.Notification(title=title, body=body),
        data=data or None,
        android=messaging.AndroidConfig(
            priority="high",
            ttl=ttl,
            notification=messaging.AndroidNotification(channel_id=EMERGENCY_CHANNEL_ID),
        ),
    )


class FirebasePushClient:
    """The real sender. Firebase is only initialised on first use."""

    APP_NAME = "edem-push"

    def __init__(self, credentials_path: str) -> None:
        self._credentials_path = credentials_path
        self._app: Any = None

    def _firebase_app(self) -> Any:
        import firebase_admin
        from firebase_admin import credentials

        if self._app is None:
            try:
                self._app = firebase_admin.get_app(self.APP_NAME)
            except ValueError:  # not initialised yet
                self._app = firebase_admin.initialize_app(
                    credentials.Certificate(self._credentials_path), name=self.APP_NAME
                )
        return self._app

    def send(
        self, token: str, title: str, body: str, data: dict[str, str], *, ttl: timedelta
    ) -> None:
        from firebase_admin import messaging

        messaging.send(
            build_message(token, title, body, data, ttl), app=self._firebase_app()
        )


@lru_cache
def get_push_client() -> PushClient:
    path = get_settings().FIREBASE_CREDENTIALS_PATH
    if not path:
        raise PushNotConfiguredError(
            "FIREBASE_CREDENTIALS_PATH is not set. Add it to your .env file"
        )
    return FirebasePushClient(path)


def classify_send_error(error: Exception) -> tuple[PushOutcome, str]:
    """Decide what an error from Firebase means for the token.

    A token is only declared dead on clear evidence, so a bug on our side can never
    wipe the tokens of working phones.
    """
    code = getattr(error, "code", None)
    text = str(error)
    lowered = text.lower()

    if code == "NOT_FOUND":
        return (
            PushOutcome.DEAD_TOKEN,
            "Firebase says this token is no longer registered",
        )
    if code == "INVALID_ARGUMENT" and "registration token" in lowered:
        return PushOutcome.DEAD_TOKEN, "Firebase says this is not a valid token"
    if code == "PERMISSION_DENIED" and "sender" in lowered and "mismatch" in lowered:
        return (
            PushOutcome.DEAD_TOKEN,
            "The token belongs to a different Firebase project",
        )
    if code in (
        "UNAVAILABLE",
        "INTERNAL",
        "DEADLINE_EXCEEDED",
        "RESOURCE_EXHAUSTED",
    ) or isinstance(error, OSError):
        return (
            PushOutcome.RETRYABLE,
            f"Temporary problem, worth retrying: {text or type(error).__name__}",
        )
    return PushOutcome.FAILED, f"{type(error).__name__}: {text}"


def send_to_devices(
    db: Session,
    devices: list[DeviceToken],
    title: str,
    body: str,
    *,
    data: dict[str, Any] | None = None,
    client: PushClient,
    ttl: timedelta = DEFAULT_TTL,
) -> PushReport:
    """Send to each device. One failure never stops the others. Dead tokens are deleted."""
    if not title.strip() or not body.strip():
        raise ValueError("A push notification needs a title and a body")
    payload = clean_data(data)

    report = PushReport()
    dead: list[DeviceToken] = []
    for device in devices:
        token_start = mask_token(device.token)
        try:
            client.send(device.token, title, body, payload, ttl=ttl)
            outcome, detail = PushOutcome.SENT, "sent"
        except Exception as error:  # noqa: BLE001
            # Firebase and the network raise many kinds of error
            outcome, detail = classify_send_error(error)

        if outcome == PushOutcome.DEAD_TOKEN:
            dead.append(device)
        platform = device.platform.value if device.platform else None
        report.results.append(
            TokenResult(device.id, token_start, platform, outcome, detail)
        )
        logger.log(
            logging.INFO if outcome == PushOutcome.SENT else logging.WARNING,
            "Push to device %s (%s): %s - %s",
            device.id,
            token_start,
            outcome.value,
            detail,
        )

    for device in dead:
        db.delete(device)
    if dead:
        db.commit()
    return report


def send_push_to_user(
    db: Session,
    user_id: uuid.UUID,
    title: str,
    body: str,
    *,
    data: dict[str, Any] | None = None,
    client: PushClient | None = None,
    ttl: timedelta = DEFAULT_TTL,
) -> PushReport:
    """Send a notification to every device the user has registered, newest device first."""
    devices = list(
        db.scalars(
            select(DeviceToken)
            .where(DeviceToken.user_id == user_id)
            .order_by(DeviceToken.updated_at.desc(), DeviceToken.id)
        )
    )
    if not devices:
        return PushReport()  # nothing to send, so no Firebase setup is needed either
    return send_to_devices(
        db, devices, title, body, data=data, client=client or get_push_client(), ttl=ttl
    )
