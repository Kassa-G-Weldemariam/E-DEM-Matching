"""Importing this package registers every table on Base.metadata (needed by Alembic)."""

from app.models.blood_bank import BloodBank
from app.models.blood_request import BloodRequest
from app.models.device_token import DeviceToken
from app.models.donor import Donor
from app.models.hospital import Hospital
from app.models.inventory import Inventory
from app.models.match import Match
from app.models.notification import Notification
from app.models.request_status_history import RequestStatusHistory
from app.models.user import User

__all__ = [
    "BloodBank",
    "BloodRequest",
    "DeviceToken",
    "Donor",
    "Hospital",
    "Inventory",
    "Match",
    "Notification",
    "RequestStatusHistory",
    "User",
]
