"""All enums used by the database.

They are stored as native PostgreSQL enum types (see `pg_enum`). Adding a value later needs an Alembic migration (ALTER TYPE ... ADD VALUE).
"""

import enum

from sqlalchemy import Enum


class UserRole(str, enum.Enum):
    DONOR = "donor"
    HOSPITAL = "hospital"
    BLOOD_BANK = "blood_bank"
    ADMIN = "admin"


class BloodType(str, enum.Enum):
    A_POS = "A+"
    A_NEG = "A-"
    B_POS = "B+"
    B_NEG = "B-"
    AB_POS = "AB+"
    AB_NEG = "AB-"
    O_POS = "O+"
    O_NEG = "O-"


class Gender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"


class Urgency(str, enum.Enum):
    NORMAL = "normal"
    URGENT = "urgent"
    CRITICAL = "critical"


class RequestStatus(str, enum.Enum):
    PENDING_BLOOD_BANK = "pending_blood_bank"
    MATCHING_DONORS = "matching_donors"
    FULFILLED = "fulfilled"  # final
    UNFULFILLED = "unfulfilled"  # final
    CANCELLED = "cancelled"  # final


FINAL_REQUEST_STATUSES = frozenset(
    {RequestStatus.FULFILLED, RequestStatus.UNFULFILLED, RequestStatus.CANCELLED}
)


class MatchStatus(str, enum.Enum):
    NOTIFIED = "notified"
    ACCEPTED = "accepted"
    ARRIVED = "arrived"
    DONATED = "donated"
    DECLINED = "declined"
    EXPIRED = "expired"
    DEFERRED = "deferred"
    NO_SHOW = "no_show"
    RELEASED = "released"


class VerificationStatus(str, enum.Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    SUSPENDED = "suspended"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    SUSPENDED = "suspended"


class DevicePlatform(str, enum.Enum):
    ANDROID = "android"
    IOS = "ios"


def pg_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    """Native PostgreSQL enum that stores the enum VALUES (e.g. 'A+'), not the member names."""
    return Enum(
        enum_cls,
        name=name,
        values_callable=lambda e: [member.value for member in e],
        validate_strings=True,
    )


# One shared type object per PostgreSQL enum (several tables reuse some of them).
user_role_type = pg_enum(UserRole, "user_role")
blood_type_type = pg_enum(BloodType, "blood_type")
gender_type = pg_enum(Gender, "gender")
urgency_type = pg_enum(Urgency, "urgency")
request_status_type = pg_enum(RequestStatus, "request_status")
match_status_type = pg_enum(MatchStatus, "match_status")
verification_status_type = pg_enum(VerificationStatus, "verification_status")
approval_status_type = pg_enum(ApprovalStatus, "approval_status")
device_platform_type = pg_enum(DevicePlatform, "device_platform")
