"""The matching rules, as plain functions with no database.

Step 3 reads candidates from the database with a looser pre-filter, then passes them here.
These functions are the authority: they apply every rule of the Matching Algorithm document.

Rule order for a rejection (the first failing rule is reported):
    already matched, blood type, account, suspended, availability, age, weight,
    waiting period, distance.
"""

import uuid
from collections import Counter
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date
from enum import Enum

from app.core.config import Settings
from app.core.dates import age_in_years
from app.core.geo import haversine_km
from app.models.enums import BloodType, VerificationStatus

B = BloodType

# Which donor blood types may give to each requested type (Matching Algorithm, section 4).
COMPATIBLE_DONOR_TYPES: dict[BloodType, frozenset[BloodType]] = {
    B.O_NEG: frozenset({B.O_NEG}),
    B.O_POS: frozenset({B.O_NEG, B.O_POS}),
    B.A_NEG: frozenset({B.O_NEG, B.A_NEG}),
    B.A_POS: frozenset({B.O_NEG, B.O_POS, B.A_NEG, B.A_POS}),
    B.B_NEG: frozenset({B.O_NEG, B.B_NEG}),
    B.B_POS: frozenset({B.O_NEG, B.O_POS, B.B_NEG, B.B_POS}),
    B.AB_NEG: frozenset({B.O_NEG, B.A_NEG, B.B_NEG, B.AB_NEG}),
    B.AB_POS: frozenset(BloodType),
}


def compatible_donor_types(requested_type: BloodType) -> frozenset[BloodType]:
    return COMPATIBLE_DONOR_TYPES[requested_type]


def is_compatible(donor_type: BloodType, requested_type: BloodType) -> bool:
    return donor_type in COMPATIBLE_DONOR_TYPES[requested_type]


@dataclass(frozen=True)
class MatchingRules:
    min_age_years: int
    min_weight_kg: float
    min_days_between_donations: int
    max_radius_km: float

    def __post_init__(self) -> None:
        if (
            self.min_age_years <= 0
            or self.min_weight_kg <= 0
            or self.max_radius_km <= 0
        ):
            raise ValueError(
                "The minimum age, minimum weight and radius must be positive"
            )
        if self.min_days_between_donations < 0:
            raise ValueError("The waiting period cannot be negative")

    @classmethod
    def from_settings(cls, settings: Settings) -> "MatchingRules":
        return cls(
            min_age_years=settings.MIN_AGE_YEARS,
            min_weight_kg=settings.MIN_WEIGHT_KG,
            min_days_between_donations=settings.MIN_DAYS_BETWEEN_DONATIONS,
            max_radius_km=settings.MAX_MATCHING_RADIUS_KM,
        )


@dataclass(frozen=True)
class DonorCandidate:
    """The facts about a donor that the rules need. Built from the database in Step 3."""

    donor_id: uuid.UUID
    blood_type: BloodType
    latitude: float
    longitude: float
    date_of_birth: date
    weight_kg: float
    last_donation_date: date | None
    is_available: bool
    account_active: bool
    verification_status: VerificationStatus


class Rejection(str, Enum):
    ALREADY_MATCHED = "already_matched"
    NOT_COMPATIBLE = "not_compatible"
    ACCOUNT_INACTIVE = "account_inactive"
    SUSPENDED = "suspended"
    UNAVAILABLE = "unavailable"
    TOO_YOUNG = "too_young"
    UNDERWEIGHT = "underweight"
    DONATED_RECENTLY = "donated_recently"
    TOO_FAR = "too_far"


@dataclass(frozen=True)
class RankedCandidate:
    candidate: DonorCandidate
    distance_km: float
    exact_match: bool
    verified: bool


@dataclass(frozen=True)
class Evaluation:
    ranked: list[RankedCandidate]
    rejections: Counter[Rejection]


def waiting_period_over(
    last_donation_date: date | None, today: date, min_days: int
) -> bool:
    """True if the donor never donated, or enough days have passed. A future date is never enough."""
    return last_donation_date is None or (today - last_donation_date).days >= min_days


def rejection_reason(
    candidate: DonorCandidate,
    requested_type: BloodType,
    rules: MatchingRules,
    today: date,
    distance_km: float,
) -> Rejection | None:
    """Why this donor cannot be matched, or None when every rule is met."""
    if not is_compatible(candidate.blood_type, requested_type):
        return Rejection.NOT_COMPATIBLE
    if not candidate.account_active:
        return Rejection.ACCOUNT_INACTIVE
    if candidate.verification_status == VerificationStatus.SUSPENDED:
        return Rejection.SUSPENDED
    if not candidate.is_available:
        return Rejection.UNAVAILABLE
    if age_in_years(candidate.date_of_birth, today) < rules.min_age_years:
        return Rejection.TOO_YOUNG
    if candidate.weight_kg < rules.min_weight_kg:
        return Rejection.UNDERWEIGHT
    if not waiting_period_over(
        candidate.last_donation_date, today, rules.min_days_between_donations
    ):
        return Rejection.DONATED_RECENTLY
    if distance_km > rules.max_radius_km:
        return Rejection.TOO_FAR
    return None


def _ranking_key(ranked: RankedCandidate) -> tuple[int, int, float, str]:
    # Verified donors first, then an exact blood type, then the nearest.
    # The donor id makes ties deterministic.
    return (
        0 if ranked.verified else 1,
        0 if ranked.exact_match else 1,
        ranked.distance_km,
        str(ranked.candidate.donor_id),
    )


def evaluate_candidates(
    candidates: Iterable[DonorCandidate],
    *,
    requested_type: BloodType,
    hospital_latitude: float,
    hospital_longitude: float,
    rules: MatchingRules,
    today: date,
    exclude: Collection[uuid.UUID] = frozenset(),
) -> Evaluation:
    """Apply every rule. Returns the eligible donors in ranking order, and why the others were refused."""
    ranked: list[RankedCandidate] = []
    rejections: Counter[Rejection] = Counter()

    for candidate in candidates:
        if candidate.donor_id in exclude:
            rejections[Rejection.ALREADY_MATCHED] += 1
            continue
        distance = haversine_km(
            hospital_latitude,
            hospital_longitude,
            candidate.latitude,
            candidate.longitude,
        )
        reason = rejection_reason(candidate, requested_type, rules, today, distance)
        if reason is not None:
            rejections[reason] += 1
            continue
        ranked.append(
            RankedCandidate(
                candidate=candidate,
                distance_km=distance,
                exact_match=candidate.blood_type == requested_type,
                verified=candidate.verification_status == VerificationStatus.VERIFIED,
            )
        )

    ranked.sort(key=_ranking_key)
    return Evaluation(ranked=ranked, rejections=rejections)


def rank_candidates(
    candidates: Iterable[DonorCandidate],
    *,
    requested_type: BloodType,
    hospital_latitude: float,
    hospital_longitude: float,
    rules: MatchingRules,
    today: date,
    exclude: Collection[uuid.UUID] = frozenset(),
) -> list[RankedCandidate]:
    return evaluate_candidates(
        candidates,
        requested_type=requested_type,
        hospital_latitude=hospital_latitude,
        hospital_longitude=hospital_longitude,
        rules=rules,
        today=today,
        exclude=exclude,
    ).ranked


def select_batch(
    ranked: list[RankedCandidate], batch_size: int
) -> list[RankedCandidate]:
    """The first `batch_size` donors of an already ranked list."""
    if batch_size < 0:
        raise ValueError("batch_size cannot be negative")
    return ranked[:batch_size]
