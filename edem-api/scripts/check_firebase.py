"""Check that the Firebase credentials work, without sending a real notification.

Run from the edem-api folder:

    uv run python -m scripts.check_firebase

It reads FIREBASE_CREDENTIALS_PATH from your .env, then asks Firebase to validate
("dry run") a message to a deliberately fake token. Firebase answering "that token is
invalid" proves the key, the project and the sending API are all accepted.
"""

import json
from collections.abc import Callable, Sequence
from pathlib import Path

from app.core.config import get_settings

Sender = Callable[[str], None]

REQUIRED_FIELDS = ("project_id", "client_email", "private_key")


def _dry_run_send(credentials_path: str) -> None:
    import firebase_admin
    from firebase_admin import credentials, messaging

    app = firebase_admin.initialize_app(
        credentials.Certificate(credentials_path), name="edem-credentials-check"
    )
    try:
        message = messaging.Message(token="invalid-token-for-credential-check")
        messaging.send(message, dry_run=True, app=app)
    finally:
        firebase_admin.delete_app(app)


def classify(error: Exception) -> tuple[bool, str]:
    """Turn what Firebase answered into (credentials work?, what to tell the person)."""
    code = getattr(error, "code", None)
    text = str(error)

    if code in ("INVALID_ARGUMENT", "NOT_FOUND"):
        return (
            True,
            "Firebase accepted the credentials (a test message to a fake token was rejected, as expected)",
        )
    if type(error).__name__ == "RefreshError":
        return False, (
            "Google rejected the service account key. It may have been deleted, or belong to another "
            "project. Generate a new one under Project settings, Service accounts. "
            f"Google said: {text}"
        )
    if code == "UNAUTHENTICATED":
        return (
            False,
            f"Firebase did not accept the credentials. Generate a new key. Google said: {text}",
        )
    if code == "PERMISSION_DENIED":
        return False, (
            "Permission denied. Check that the Firebase Cloud Messaging API (V1) is enabled "
            "(Project settings, Cloud Messaging tab) and that this key belongs to the same project. "
            f"Google said: {text}"
        )
    if code in ("UNAVAILABLE", "DEADLINE_EXCEEDED") or isinstance(
        error, (ConnectionError, TimeoutError, OSError)
    ):
        return (
            False,
            f"Could not reach Firebase. Check your internet connection and try again. ({text})",
        )
    return False, f"Unexpected error ({type(error).__name__}): {text}"


def check(
    credentials_path: str | None, *, send: Sender | None = None
) -> tuple[bool, list[str]]:
    """Returns (everything is fine?, lines to print). Never includes the private key."""
    if not credentials_path:
        return False, ["FIREBASE_CREDENTIALS_PATH is not set. Add it to your .env file"]

    path = Path(credentials_path)
    if not path.is_file():
        return False, [f"Credentials file not found: {credentials_path}"]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, [
            f"{credentials_path} is not valid JSON. Did you download the right file?"
        ]
    if not isinstance(data, dict) or data.get("type") != "service_account":
        return False, [
            (
                f"{credentials_path} is not a service account key. "
                "Use Project settings, Service accounts, Generate new private key "
                "(google-services.json is a different file)"
            )
        ]
    missing = [field for field in REQUIRED_FIELDS if not data.get(field)]
    if missing:
        return False, [f"The key file is missing: {', '.join(missing)}"]

    lines = [
        f"Credentials file: {credentials_path}",
        f"Project: {data['project_id']}",
        f"Service account: {data['client_email']}",
    ]
    try:
        (send or _dry_run_send)(credentials_path)
    except Exception as error:  # noqa: BLE001
        ok, message = classify(error)
        lines.append(("OK: " if ok else "FAILED: ") + message)
        return ok, lines

    lines.append("OK: Firebase accepted the dry-run message")
    return True, lines


def main(argv: Sequence[str] | None = None, sender: Sender | None = None) -> int:
    ok, lines = check(get_settings().FIREBASE_CREDENTIALS_PATH, send=sender)
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
