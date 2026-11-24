import dataclasses
import random
import uuid
from datetime import date, timedelta
from typing import Any

import pytest

from app.core.config import get_settings
from app.core.geo import haversine_km
from app.models.enums import BloodType as B
from app.models.enums import VerificationStatus as V
from app.services.matching_rules import (
    DonorCandidate,
    MatchingRules,
    RankedCandidate,
    Rejection,
    evaluate_candidates,
    rank_candidates,
    rejection_reason,
    select_batch,
)
from tests.geo_helpers import destination

TODAY = date(2026, 11, 20)
HOSPITAL = (9.03, 38.74)
RULES = MatchingRules(
    min_age_years=18, min_weight_kg=50, min_days_between_donations=56, max_radius_km=25
)


def at_km(km: float, bearing: float = 90.0) -> tuple[float, float]:
    return destination(*HOSPITAL, bearing, km)


def make(**overrides: Any) -> DonorCandidate:
    latitude, longitude = at_km(5)
    fields: dict[str, Any] = {
        "donor_id": uuid.uuid4(),
        "blood_type": B.O_POS,
        "latitude": latitude,
        "longitude": longitude,
        "date_of_birth": date(1995, 1, 1),
        "weight_kg": 65.0,
        "last_donation_date": None,
        "is_available": True,
        "account_active": True,
        "verification_status": V.UNVERIFIED,
    }
    fields.update(overrides)
    return DonorCandidate(**fields)


def reason(
    candidate: DonorCandidate,
    requested: B = B.O_POS,
    rules: MatchingRules = RULES,
    today: date = TODAY,
):
    distance = haversine_km(*HOSPITAL, candidate.latitude, candidate.longitude)
    return rejection_reason(candidate, requested, rules, today, distance)


def evaluate(
    candidates,
    requested: B = B.O_POS,
    exclude=frozenset(),
    rules: MatchingRules = RULES,
):
    return evaluate_candidates(
        candidates,
        requested_type=requested,
        hospital_latitude=HOSPITAL[0],
        hospital_longitude=HOSPITAL[1],
        rules=rules,
        today=TODAY,
        exclude=exclude,
    )


def ranked_ids(candidates, requested: B = B.O_POS, **kwargs) -> list[uuid.UUID]:
    return [
        item.candidate.donor_id
        for item in evaluate(candidates, requested, **kwargs).ranked
    ]


# ============================================================ eligibility


def test_a_normal_donor_is_accepted():
    assert reason(make()) is None


def test_an_incompatible_blood_type_is_refused():
    assert (
        reason(make(blood_type=B.A_POS), requested=B.O_NEG) == Rejection.NOT_COMPATIBLE
    )


def test_a_compatible_but_different_blood_type_is_accepted():
    assert reason(make(blood_type=B.O_NEG), requested=B.A_POS) is None


def test_an_inactive_account_is_refused():
    assert reason(make(account_active=False)) == Rejection.ACCOUNT_INACTIVE


def test_a_suspended_donor_is_refused():
    assert reason(make(verification_status=V.SUSPENDED)) == Rejection.SUSPENDED


@pytest.mark.parametrize("status", [V.UNVERIFIED, V.VERIFIED])
def test_unverified_and_verified_donors_are_both_accepted(status):
    assert reason(make(verification_status=status)) is None


def test_an_unavailable_donor_is_refused():
    assert reason(make(is_available=False)) == Rejection.UNAVAILABLE


# ------------------------------------------------------------------- age


def test_a_donor_who_turns_18_today_is_accepted():
    assert reason(make(date_of_birth=date(2008, 11, 20))) is None


def test_a_donor_one_day_short_of_18_is_refused():
    assert reason(make(date_of_birth=date(2008, 11, 21))) == Rejection.TOO_YOUNG


@pytest.mark.parametrize(
    "today,expected",
    [(date(2026, 2, 28), Rejection.TOO_YOUNG), (date(2026, 3, 1), None)],
    ids=["28 February", "1 March"],
)
def test_a_leap_day_birthday_counts_from_1_march(today, expected):
    assert reason(make(date_of_birth=date(2008, 2, 29)), today=today) == expected


@pytest.mark.parametrize(
    "born,expected",
    [(date(2005, 11, 21), Rejection.TOO_YOUNG), (date(2005, 11, 20), None)],
    ids=["one day short", "exactly 21"],
)
def test_the_minimum_age_comes_from_the_rules(born, expected):
    rules = dataclasses.replace(RULES, min_age_years=21)
    assert reason(make(date_of_birth=born), rules=rules) == expected


# ---------------------------------------------------------------- weight


@pytest.mark.parametrize(
    "weight,expected", [(50.0, None), (49.9, Rejection.UNDERWEIGHT)]
)
def test_the_minimum_weight_is_inclusive(weight, expected):
    assert reason(make(weight_kg=weight)) == expected


def test_the_minimum_weight_comes_from_the_rules():
    rules = dataclasses.replace(RULES, min_weight_kg=55)
    assert reason(make(weight_kg=54.9), rules=rules) == Rejection.UNDERWEIGHT


# -------------------------------------------------------- waiting period


def test_a_donor_who_never_donated_is_accepted():
    assert reason(make(last_donation_date=None)) is None


def test_a_donor_is_eligible_again_on_day_56():
    assert reason(make(last_donation_date=TODAY - timedelta(days=56))) is None


def test_a_donor_is_not_eligible_on_day_55():
    assert (
        reason(make(last_donation_date=TODAY - timedelta(days=55)))
        == Rejection.DONATED_RECENTLY
    )


def test_a_donor_who_donated_today_is_refused():
    assert reason(make(last_donation_date=TODAY)) == Rejection.DONATED_RECENTLY


def test_a_donation_long_ago_is_fine():
    assert reason(make(last_donation_date=date(2020, 1, 1))) is None


def test_a_donation_date_in_the_future_is_refused():
    assert (
        reason(make(last_donation_date=TODAY + timedelta(days=1)))
        == Rejection.DONATED_RECENTLY
    )


@pytest.mark.parametrize(
    "days,expected", [(89, Rejection.DONATED_RECENTLY), (90, None)]
)
def test_the_waiting_period_comes_from_the_rules(days, expected):
    rules = dataclasses.replace(RULES, min_days_between_donations=90)
    assert (
        reason(make(last_donation_date=TODAY - timedelta(days=days)), rules=rules)
        == expected
    )


# -------------------------------------------------------------- distance


def test_a_donor_just_inside_the_radius_is_accepted():
    assert reason(make(latitude=at_km(24.9)[0], longitude=at_km(24.9)[1])) is None


def test_a_donor_just_outside_the_radius_is_refused():
    assert (
        reason(make(latitude=at_km(25.1)[0], longitude=at_km(25.1)[1]))
        == Rejection.TOO_FAR
    )


def test_a_donor_at_the_hospital_is_accepted():
    assert reason(make(latitude=HOSPITAL[0], longitude=HOSPITAL[1])) is None


def test_a_donor_exactly_at_the_limit_is_accepted():
    candidate = make(latitude=at_km(25)[0], longitude=at_km(25)[1])
    limit = haversine_km(*HOSPITAL, candidate.latitude, candidate.longitude)
    assert (
        reason(candidate, rules=dataclasses.replace(RULES, max_radius_km=limit)) is None
    )


@pytest.mark.parametrize("bearing", [0, 90, 180, 270])
def test_a_donor_inside_the_radius_is_accepted_in_every_direction(bearing):
    latitude, longitude = at_km(24, bearing)
    assert reason(make(latitude=latitude, longitude=longitude)) is None


@pytest.mark.parametrize("bearing", [0, 90, 180, 270])
def test_a_donor_outside_the_radius_is_refused_in_every_direction(bearing):
    latitude, longitude = at_km(26, bearing)
    assert reason(make(latitude=latitude, longitude=longitude)) == Rejection.TOO_FAR


# ------------------------------------------------- which reason is reported


FAR = {"latitude": at_km(30)[0], "longitude": at_km(30)[1]}
PRECEDENCE = [
    ({"blood_type": B.A_POS, "account_active": False}, Rejection.NOT_COMPATIBLE),
    (
        {"account_active": False, "verification_status": V.SUSPENDED},
        Rejection.ACCOUNT_INACTIVE,
    ),
    ({"verification_status": V.SUSPENDED, "is_available": False}, Rejection.SUSPENDED),
    ({"is_available": False, "date_of_birth": date(2015, 1, 1)}, Rejection.UNAVAILABLE),
    ({"date_of_birth": date(2015, 1, 1), "weight_kg": 30.0}, Rejection.TOO_YOUNG),
    ({"weight_kg": 30.0, "last_donation_date": TODAY}, Rejection.UNDERWEIGHT),
    ({"last_donation_date": TODAY, **FAR}, Rejection.DONATED_RECENTLY),
]


@pytest.mark.parametrize(
    "fields,expected", PRECEDENCE, ids=[expected.value for _, expected in PRECEDENCE]
)
def test_a_donor_failing_several_rules_is_reported_under_the_first(fields, expected):
    assert reason(make(**fields)) == expected


# ================================================================ ranking


def test_a_verified_donor_comes_before_an_unverified_one_even_if_farther():
    near_unverified = make(latitude=at_km(1)[0], longitude=at_km(1)[1])
    far_verified = make(
        latitude=at_km(20)[0], longitude=at_km(20)[1], verification_status=V.VERIFIED
    )
    assert ranked_ids([near_unverified, far_verified]) == [
        far_verified.donor_id,
        near_unverified.donor_id,
    ]


def test_an_exact_blood_type_comes_before_a_compatible_one_even_if_farther():
    near_compatible = make(
        blood_type=B.O_NEG, latitude=at_km(1)[0], longitude=at_km(1)[1]
    )
    far_exact = make(blood_type=B.A_POS, latitude=at_km(20)[0], longitude=at_km(20)[1])
    assert ranked_ids([near_compatible, far_exact], requested=B.A_POS) == [
        far_exact.donor_id,
        near_compatible.donor_id,
    ]


def test_being_verified_outranks_having_the_exact_blood_type():
    verified_compatible = make(blood_type=B.O_NEG, verification_status=V.VERIFIED)
    unverified_exact = make(blood_type=B.A_POS)
    assert ranked_ids([unverified_exact, verified_compatible], requested=B.A_POS) == [
        verified_compatible.donor_id,
        unverified_exact.donor_id,
    ]


def test_the_nearest_donor_comes_first_within_the_same_group():
    far, middle, near = (
        make(latitude=at_km(km)[0], longitude=at_km(km)[1]) for km in (20, 10, 2)
    )
    assert ranked_ids([far, near, middle]) == [
        near.donor_id,
        middle.donor_id,
        far.donor_id,
    ]


def test_equal_distances_are_ordered_by_donor_id():
    first = make(donor_id=uuid.UUID(int=1))
    second = make(donor_id=uuid.UUID(int=2))
    assert ranked_ids([second, first]) == [first.donor_id, second.donor_id]
    assert ranked_ids([first, second]) == [first.donor_id, second.donor_id]


def test_a_full_ranking_example():
    def donor(blood_type, km, status):
        latitude, longitude = at_km(km)
        return make(
            blood_type=blood_type,
            latitude=latitude,
            longitude=longitude,
            verification_status=status,
        )

    verified_exact_near = donor(B.A_POS, 2, V.VERIFIED)
    verified_exact_far = donor(B.A_POS, 20, V.VERIFIED)
    verified_compatible = donor(B.O_NEG, 1, V.VERIFIED)
    unverified_exact = donor(B.A_POS, 3, V.UNVERIFIED)
    unverified_compatible_near = donor(B.O_POS, 1, V.UNVERIFIED)
    unverified_compatible_far = donor(B.O_NEG, 15, V.UNVERIFIED)

    expected = [
        verified_exact_near,
        verified_exact_far,
        verified_compatible,
        unverified_exact,
        unverified_compatible_near,
        unverified_compatible_far,
    ]
    shuffled = [
        unverified_compatible_far,
        verified_compatible,
        unverified_exact,
        verified_exact_far,
        unverified_compatible_near,
        verified_exact_near,
    ]
    assert ranked_ids(shuffled, requested=B.A_POS) == [
        item.donor_id for item in expected
    ]


def test_the_input_order_never_changes_the_result():
    candidates = [
        make(latitude=at_km(km)[0], longitude=at_km(km)[1]) for km in (3, 8, 12, 17, 22)
    ]
    expected = ranked_ids(candidates)
    generator = random.Random(7)
    for _ in range(5):
        generator.shuffle(candidates)
        assert ranked_ids(candidates) == expected


def test_donors_already_matched_are_skipped_and_counted():
    already = make()
    already_and_ineligible = make(is_available=False)
    fresh = make()
    evaluation = evaluate(
        [already, already_and_ineligible, fresh],
        exclude={already.donor_id, already_and_ineligible.donor_id},
    )
    assert [item.candidate.donor_id for item in evaluation.ranked] == [fresh.donor_id]
    assert evaluation.rejections[Rejection.ALREADY_MATCHED] == 2
    assert evaluation.rejections[Rejection.UNAVAILABLE] == 0


def test_every_refusal_is_counted_under_its_reason():
    candidates = [
        make(),
        make(),
        make(blood_type=B.A_POS),
        make(account_active=False),
        make(account_active=False),
        make(verification_status=V.SUSPENDED),
        make(is_available=False),
        make(date_of_birth=date(2015, 1, 1)),
        make(weight_kg=30.0),
        make(last_donation_date=TODAY),
        make(**FAR),
    ]
    evaluation = evaluate(candidates, requested=B.O_POS)
    assert len(evaluation.ranked) == 2
    assert dict(evaluation.rejections) == {
        Rejection.NOT_COMPATIBLE: 1,
        Rejection.ACCOUNT_INACTIVE: 2,
        Rejection.SUSPENDED: 1,
        Rejection.UNAVAILABLE: 1,
        Rejection.TOO_YOUNG: 1,
        Rejection.UNDERWEIGHT: 1,
        Rejection.DONATED_RECENTLY: 1,
        Rejection.TOO_FAR: 1,
    }


def test_no_candidates_gives_an_empty_result():
    evaluation = evaluate([])
    assert evaluation.ranked == []
    assert dict(evaluation.rejections) == {}


def test_the_distance_is_measured_from_the_hospital():
    [item] = evaluate([make(latitude=at_km(5)[0], longitude=at_km(5)[1])]).ranked
    assert item.distance_km == pytest.approx(5.0, abs=0.05)


def test_the_exact_match_and_verified_flags_are_set():
    exact_verified = make(blood_type=B.O_POS, verification_status=V.VERIFIED)
    compatible_unverified = make(blood_type=B.O_NEG)
    by_id = {
        item.candidate.donor_id: item
        for item in evaluate([exact_verified, compatible_unverified]).ranked
    }
    assert (
        by_id[exact_verified.donor_id].exact_match,
        by_id[exact_verified.donor_id].verified,
    ) == (True, True)
    assert (
        by_id[compatible_unverified.donor_id].exact_match,
        by_id[compatible_unverified.donor_id].verified,
    ) == (
        False,
        False,
    )


def test_refused_donors_never_appear_in_the_ranking():
    good = make()
    refused = [
        make(blood_type=B.A_POS),
        make(account_active=False),
        make(is_available=False),
        make(**FAR),
    ]
    assert ranked_ids([*refused, good]) == [good.donor_id]


def test_rank_candidates_returns_the_same_order_as_evaluate_candidates():
    candidates = [
        make(latitude=at_km(km)[0], longitude=at_km(km)[1]) for km in (9, 4, 14)
    ]
    direct = rank_candidates(
        candidates,
        requested_type=B.O_POS,
        hospital_latitude=HOSPITAL[0],
        hospital_longitude=HOSPITAL[1],
        rules=RULES,
        today=TODAY,
    )
    assert [item.candidate.donor_id for item in direct] == ranked_ids(candidates)


# ================================================================ batches


@pytest.fixture()
def five_ranked() -> list[RankedCandidate]:
    candidates = [
        make(latitude=at_km(km)[0], longitude=at_km(km)[1]) for km in (1, 2, 3, 4, 5)
    ]
    return evaluate(candidates).ranked


def test_a_batch_is_the_first_donors_of_the_ranking(five_ranked):
    assert select_batch(five_ranked, 3) == five_ranked[:3]


def test_a_batch_larger_than_the_ranking_returns_everyone(five_ranked):
    batch = select_batch(five_ranked, 10)
    assert batch == five_ranked
    assert batch is not five_ranked


def test_a_batch_of_zero_is_empty(five_ranked):
    assert select_batch(five_ranked, 0) == []


def test_a_negative_batch_size_is_refused(five_ranked):
    with pytest.raises(ValueError, match="negative"):
        select_batch(five_ranked, -1)


# ================================================================== rules


def test_the_rules_are_read_from_the_settings():
    settings = get_settings()
    rules = MatchingRules.from_settings(settings)
    assert rules.min_age_years == settings.MIN_AGE_YEARS
    assert rules.min_weight_kg == settings.MIN_WEIGHT_KG
    assert rules.min_days_between_donations == settings.MIN_DAYS_BETWEEN_DONATIONS
    assert rules.max_radius_km == settings.MAX_MATCHING_RADIUS_KM


@pytest.mark.parametrize(
    "changes",
    [
        {"min_age_years": 0},
        {"min_weight_kg": 0},
        {"min_days_between_donations": -1},
        {"max_radius_km": 0},
    ],
    ids=["age", "weight", "waiting period", "radius"],
)
def test_nonsense_rules_are_refused(changes):
    with pytest.raises(ValueError):
        dataclasses.replace(RULES, **changes)


def test_the_rules_cannot_be_changed_after_they_are_made():
    with pytest.raises(dataclasses.FrozenInstanceError):
        RULES.max_radius_km = 100  # type: ignore[misc]
