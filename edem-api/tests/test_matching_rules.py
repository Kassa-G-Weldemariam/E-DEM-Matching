import dataclasses
import random
import uuid
from datetime import date, timedelta
from typing import Any

import pytest

from app.core.config import get_settings
from app.core.geo import haversine_km
from app.models.enums import BloodType as B
from app.models.enums import Gender as G
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
    min_age_years=18,
    upper_age_limit_years=65,
    min_weight_kg=50,
    min_days_male=90,
    min_days_female=120,
    max_radius_km=25,
    distance_band_km=2,
)


def at_km(km: float, bearing: float = 90.0) -> tuple[float, float]:
    return destination(*HOSPITAL, bearing, km)


def spot(km: float, bearing: float = 90.0) -> dict[str, float]:
    latitude, longitude = at_km(km, bearing)
    return {"latitude": latitude, "longitude": longitude}


def born_aged(years: int) -> date:
    """A birth date that makes the donor exactly this old on TODAY."""
    return TODAY.replace(year=TODAY.year - years)


def make(**overrides: Any) -> DonorCandidate:
    fields: dict[str, Any] = {
        "donor_id": uuid.uuid4(),
        "blood_type": B.O_POS,
        "gender": G.MALE,
        "date_of_birth": date(1995, 1, 1),
        "weight_kg": 65.0,
        "last_donation_date": None,
        "is_available": True,
        "account_active": True,
        "verification_status": V.UNVERIFIED,
        **spot(5),
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
def test_a_leap_day_birthday_counts_from_1_march_for_the_minimum_age(today, expected):
    assert reason(make(date_of_birth=date(2008, 2, 29)), today=today) == expected


@pytest.mark.parametrize(
    "born,expected",
    [(date(2005, 11, 21), Rejection.TOO_YOUNG), (date(2005, 11, 20), None)],
    ids=["one day short", "exactly 21"],
)
def test_the_minimum_age_comes_from_the_rules(born, expected):
    rules = dataclasses.replace(RULES, min_age_years=21)
    assert reason(make(date_of_birth=born), rules=rules) == expected


@pytest.mark.parametrize(
    "age,expected",
    [
        (17, Rejection.TOO_YOUNG),
        (18, None),
        (64, None),
        (65, Rejection.TOO_OLD),
        (80, Rejection.TOO_OLD),
    ],
)
def test_only_ages_18_to_64_are_accepted(age, expected):
    assert reason(make(date_of_birth=born_aged(age))) == expected


def test_a_donor_who_turns_65_today_is_refused():
    assert reason(make(date_of_birth=date(1961, 11, 20))) == Rejection.TOO_OLD


def test_a_donor_who_turns_65_tomorrow_is_still_accepted():
    assert reason(make(date_of_birth=date(1961, 11, 21))) is None


@pytest.mark.parametrize(
    "today,expected",
    [(date(2025, 2, 28), None), (date(2025, 3, 1), Rejection.TOO_OLD)],
    ids=["28 February", "1 March"],
)
def test_a_leap_day_birthday_counts_from_1_march_for_the_upper_limit(today, expected):
    assert reason(make(date_of_birth=date(1960, 2, 29)), today=today) == expected


@pytest.mark.parametrize(
    "born,expected",
    [(date(1966, 11, 21), None), (date(1966, 11, 20), Rejection.TOO_OLD)],
    ids=["59 years old", "exactly 60"],
)
def test_the_upper_age_limit_comes_from_the_rules(born, expected):
    rules = dataclasses.replace(RULES, upper_age_limit_years=60)
    assert reason(make(date_of_birth=born), rules=rules) == expected


def test_a_very_old_donor_is_refused():
    assert reason(make(date_of_birth=date(1930, 1, 1))) == Rejection.TOO_OLD


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


@pytest.mark.parametrize("gender", [G.MALE, G.FEMALE])
def test_a_donor_who_never_donated_is_accepted(gender):
    assert reason(make(gender=gender, last_donation_date=None)) is None


def test_a_man_is_eligible_again_on_day_90():
    assert (
        reason(make(gender=G.MALE, last_donation_date=TODAY - timedelta(days=90)))
        is None
    )


def test_a_man_is_not_eligible_on_day_89():
    candidate = make(gender=G.MALE, last_donation_date=TODAY - timedelta(days=89))
    assert reason(candidate) == Rejection.DONATED_RECENTLY


def test_a_woman_is_eligible_again_on_day_120():
    assert (
        reason(make(gender=G.FEMALE, last_donation_date=TODAY - timedelta(days=120)))
        is None
    )


def test_a_woman_is_not_eligible_on_day_119():
    candidate = make(gender=G.FEMALE, last_donation_date=TODAY - timedelta(days=119))
    assert reason(candidate) == Rejection.DONATED_RECENTLY


@pytest.mark.parametrize(
    "gender,expected", [(G.MALE, None), (G.FEMALE, Rejection.DONATED_RECENTLY)]
)
def test_the_same_donation_date_can_be_fine_for_a_man_and_too_recent_for_a_woman(
    gender, expected
):
    assert (
        reason(make(gender=gender, last_donation_date=TODAY - timedelta(days=100)))
        == expected
    )


@pytest.mark.parametrize("gender", [G.MALE, G.FEMALE])
def test_a_donor_who_donated_today_is_refused(gender):
    assert (
        reason(make(gender=gender, last_donation_date=TODAY))
        == Rejection.DONATED_RECENTLY
    )


def test_a_donation_long_ago_is_fine():
    assert reason(make(last_donation_date=date(2020, 1, 1))) is None


@pytest.mark.parametrize("gender", [G.MALE, G.FEMALE])
def test_a_donation_date_in_the_future_is_refused(gender):
    candidate = make(gender=gender, last_donation_date=TODAY + timedelta(days=1))
    assert reason(candidate) == Rejection.DONATED_RECENTLY


@pytest.mark.parametrize(
    "gender,days,expected",
    [
        (G.MALE, 59, Rejection.DONATED_RECENTLY),
        (G.MALE, 60, None),
        (G.FEMALE, 79, Rejection.DONATED_RECENTLY),
        (G.FEMALE, 80, None),
    ],
)
def test_the_waiting_periods_come_from_the_rules(gender, days, expected):
    rules = dataclasses.replace(RULES, min_days_male=60, min_days_female=80)
    candidate = make(gender=gender, last_donation_date=TODAY - timedelta(days=days))
    assert reason(candidate, rules=rules) == expected


def test_the_rules_report_the_waiting_period_of_each_gender():
    assert RULES.waiting_days(G.MALE) == 90
    assert RULES.waiting_days(G.FEMALE) == 120


# -------------------------------------------------------------- distance


def test_a_donor_just_inside_the_radius_is_accepted():
    assert reason(make(**spot(24.9))) is None


def test_a_donor_just_outside_the_radius_is_refused():
    assert reason(make(**spot(25.1))) == Rejection.TOO_FAR


def test_a_donor_at_the_hospital_is_accepted():
    assert reason(make(latitude=HOSPITAL[0], longitude=HOSPITAL[1])) is None


def test_a_donor_exactly_at_the_limit_is_accepted():
    candidate = make(**spot(25))
    limit = haversine_km(*HOSPITAL, candidate.latitude, candidate.longitude)
    assert (
        reason(candidate, rules=dataclasses.replace(RULES, max_radius_km=limit)) is None
    )


@pytest.mark.parametrize("bearing", [0, 90, 180, 270])
def test_a_donor_inside_the_radius_is_accepted_in_every_direction(bearing):
    assert reason(make(**spot(24, bearing))) is None


@pytest.mark.parametrize("bearing", [0, 90, 180, 270])
def test_a_donor_outside_the_radius_is_refused_in_every_direction(bearing):
    assert reason(make(**spot(26, bearing))) == Rejection.TOO_FAR


# ------------------------------------------------- which reason is reported


FAR = spot(30)
PRECEDENCE = [
    ({"blood_type": B.A_POS, "account_active": False}, Rejection.NOT_COMPATIBLE),
    (
        {"account_active": False, "verification_status": V.SUSPENDED},
        Rejection.ACCOUNT_INACTIVE,
    ),
    ({"verification_status": V.SUSPENDED, "is_available": False}, Rejection.SUSPENDED),
    ({"is_available": False, "date_of_birth": date(2015, 1, 1)}, Rejection.UNAVAILABLE),
    ({"date_of_birth": date(2015, 1, 1), "weight_kg": 30.0}, Rejection.TOO_YOUNG),
    ({"date_of_birth": date(1950, 1, 1), "weight_kg": 30.0}, Rejection.TOO_OLD),
    ({"weight_kg": 30.0, "last_donation_date": TODAY}, Rejection.UNDERWEIGHT),
    ({"last_donation_date": TODAY, **FAR}, Rejection.DONATED_RECENTLY),
]


@pytest.mark.parametrize(
    "fields,expected", PRECEDENCE, ids=[expected.value for _, expected in PRECEDENCE]
)
def test_a_donor_failing_several_rules_is_reported_under_the_first(fields, expected):
    assert reason(make(**fields)) == expected


# ================================================================ ranking
# Distance bands are 2 km wide in these tests: 0-2 km is band 0, 2-4 km is band 1, and so on.


def test_a_nearer_band_beats_being_verified_or_an_exact_match():
    near = make(blood_type=B.O_NEG, **spot(1))  # unverified, compatible only
    far = make(blood_type=B.O_POS, verification_status=V.VERIFIED, **spot(20))
    assert ranked_ids([far, near]) == [near.donor_id, far.donor_id]


def test_in_the_same_band_a_verified_donor_comes_first_even_if_farther():
    nearer_unverified = make(**spot(0.5))
    farther_verified = make(verification_status=V.VERIFIED, **spot(1.5))
    assert ranked_ids([nearer_unverified, farther_verified]) == [
        farther_verified.donor_id,
        nearer_unverified.donor_id,
    ]


def test_in_the_same_band_an_exact_blood_type_comes_first_even_if_farther():
    nearer_compatible = make(blood_type=B.O_NEG, **spot(0.5))
    farther_exact = make(blood_type=B.O_POS, **spot(1.5))
    assert ranked_ids([nearer_compatible, farther_exact]) == [
        farther_exact.donor_id,
        nearer_compatible.donor_id,
    ]


def test_in_the_same_band_being_verified_outranks_an_exact_blood_type():
    verified_compatible = make(
        blood_type=B.O_NEG, verification_status=V.VERIFIED, **spot(1.5)
    )
    unverified_exact = make(blood_type=B.O_POS, **spot(0.5))
    assert ranked_ids([unverified_exact, verified_compatible]) == [
        verified_compatible.donor_id,
        unverified_exact.donor_id,
    ]


def test_in_the_same_band_and_group_the_nearest_comes_first():
    far, near = make(**spot(1.5)), make(**spot(0.5))
    assert ranked_ids([far, near]) == [near.donor_id, far.donor_id]


def test_a_donor_just_across_a_band_boundary_ranks_after_one_just_inside_it():
    inside_unverified = make(**spot(1.9))
    across_verified = make(verification_status=V.VERIFIED, **spot(2.1))
    assert ranked_ids([across_verified, inside_unverified]) == [
        inside_unverified.donor_id,
        across_verified.donor_id,
    ]


def test_equal_distances_are_ordered_by_donor_id():
    first = make(donor_id=uuid.UUID(int=1))
    second = make(donor_id=uuid.UUID(int=2))
    assert ranked_ids([second, first]) == [first.donor_id, second.donor_id]
    assert ranked_ids([first, second]) == [first.donor_id, second.donor_id]


def test_the_band_size_comes_from_the_rules():
    unverified_near = make(**spot(1))
    verified_farther = make(verification_status=V.VERIFIED, **spot(4))
    candidates = [unverified_near, verified_farther]
    assert ranked_ids(candidates) == [
        unverified_near.donor_id,
        verified_farther.donor_id,
    ]  # 2 km bands
    wide = dataclasses.replace(RULES, distance_band_km=5)
    assert ranked_ids(candidates, rules=wide) == [
        verified_farther.donor_id,
        unverified_near.donor_id,
    ]  # 5 km bands


def test_a_full_ranking_example():
    a = make(blood_type=B.A_POS, verification_status=V.VERIFIED, **spot(0.5))
    b = make(blood_type=B.O_NEG, verification_status=V.VERIFIED, **spot(1.5))
    c = make(blood_type=B.A_POS, **spot(0.8))
    d = make(blood_type=B.O_NEG, **spot(0.3))
    e = make(blood_type=B.A_POS, verification_status=V.VERIFIED, **spot(3))
    f = make(blood_type=B.A_POS, **spot(9))
    shuffled = [f, d, b, e, c, a]
    assert ranked_ids(shuffled, requested=B.A_POS) == [
        item.donor_id for item in (a, b, c, d, e, f)
    ]


def test_the_input_order_never_changes_the_result():
    candidates = [make(**spot(km)) for km in (3, 8, 12, 17, 22)]
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
        make(date_of_birth=date(1950, 1, 1)),
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
        Rejection.TOO_OLD: 1,
        Rejection.UNDERWEIGHT: 1,
        Rejection.DONATED_RECENTLY: 1,
        Rejection.TOO_FAR: 1,
    }


def test_no_candidates_gives_an_empty_result():
    evaluation = evaluate([])
    assert evaluation.ranked == []
    assert dict(evaluation.rejections) == {}


def test_the_distance_is_measured_from_the_hospital():
    [item] = evaluate([make(**spot(5))]).ranked
    assert item.distance_km == pytest.approx(5.0, abs=0.05)


def test_the_exact_match_verified_and_band_are_set():
    exact_verified = make(blood_type=B.O_POS, verification_status=V.VERIFIED, **spot(5))
    compatible_unverified = make(blood_type=B.O_NEG, **spot(1))
    by_id = {
        item.candidate.donor_id: item
        for item in evaluate([exact_verified, compatible_unverified]).ranked
    }
    first, second = (
        by_id[exact_verified.donor_id],
        by_id[compatible_unverified.donor_id],
    )
    assert (first.exact_match, first.verified, first.band) == (True, True, 2)
    assert (second.exact_match, second.verified, second.band) == (False, False, 0)


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
    candidates = [make(**spot(km)) for km in (9, 4, 14)]
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
    return evaluate([make(**spot(km)) for km in (1, 2, 3, 4, 5)]).ranked


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
    assert rules.upper_age_limit_years == settings.UPPER_AGE_LIMIT_YEARS
    assert rules.min_weight_kg == settings.MIN_WEIGHT_KG
    assert rules.min_days_male == settings.MIN_DAYS_BETWEEN_DONATIONS_MALE
    assert rules.min_days_female == settings.MIN_DAYS_BETWEEN_DONATIONS_FEMALE
    assert rules.max_radius_km == settings.MAX_MATCHING_RADIUS_KM
    assert rules.distance_band_km == settings.DISTANCE_BAND_KM


@pytest.mark.parametrize(
    "changes",
    [
        {"min_age_years": 0},
        {"upper_age_limit_years": 18},
        {"upper_age_limit_years": 10},
        {"min_weight_kg": 0},
        {"min_days_male": -1},
        {"min_days_female": -1},
        {"max_radius_km": 0},
        {"distance_band_km": 0},
        {"distance_band_km": -2},
    ],
    ids=[
        "age",
        "upper limit equal to minimum",
        "upper limit below minimum",
        "weight",
        "male waiting period",
        "female waiting period",
        "radius",
        "band zero",
        "band negative",
    ],
)
def test_nonsense_rules_are_refused(changes):
    with pytest.raises(ValueError):
        dataclasses.replace(RULES, **changes)


def test_the_rules_cannot_be_changed_after_they_are_made():
    with pytest.raises(dataclasses.FrozenInstanceError):
        RULES.max_radius_km = 100  # type: ignore[misc]
