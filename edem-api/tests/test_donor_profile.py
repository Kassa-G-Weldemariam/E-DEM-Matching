import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.api.deps import CurrentDonor, DbSession
from app.core.config import get_settings
from app.models.donor import Donor
from app.models.enums import ApprovalStatus, UserRole, VerificationStatus
from app.services.ownership import get_match_for_donor
from tests.factories import (
    auth_headers,
    make_blood_bank,
    make_donor,
    make_match,
    make_user,
)

URL = "/v1/donors/profile"
AVAILABILITY_URL = "/v1/donors/availability"

REQUIRED_FIELDS = [
    "blood_bank_id",
    "full_name",
    "blood_type",
    "gender",
    "date_of_birth",
    "weight_kg",
    "latitude",
    "longitude",
]
TOMORROW = (date.today() + timedelta(days=1)).isoformat()


def years_ago(years: int) -> date:
    today = date.today()
    try:
        return today.replace(year=today.year - years)
    except ValueError:  # today is 29 February and that year has no 29 February
        return today.replace(year=today.year - years, day=28)


@pytest.fixture()
def bank(db):
    """An approved, active blood bank that donors may choose."""
    return make_blood_bank(db, name="Central Blood Bank")


def payload(bank, drop=(), **overrides) -> dict:
    data = {
        "blood_bank_id": str(bank.id),
        "full_name": "Abebe Kebede",
        "blood_type": "O+",
        "gender": "male",
        "date_of_birth": "1995-04-12",
        "weight_kg": 68.5,
        "latitude": 9.03,
        "longitude": 38.74,
    }
    data.update(overrides)
    for key in drop:
        data.pop(key, None)
    return data


def update_payload(drop=(), **overrides) -> dict:
    data = {
        "full_name": "Abebe Kebede",
        "blood_type": "O+",
        "gender": "male",
        "date_of_birth": "1995-04-12",
        "weight_kg": 68.5,
        "latitude": 9.03,
        "longitude": 38.74,
    }
    data.update(overrides)
    for key in drop:
        data.pop(key, None)
    return data


def donor_user(db):
    return make_user(db, UserRole.DONOR)


def create(client, user, bank, **overrides):
    return client.post(URL, json=payload(bank, **overrides), headers=auth_headers(user))


def update(client, user, **overrides):
    return client.put(URL, json=update_payload(**overrides), headers=auth_headers(user))


def error_fields(response) -> list[str]:
    return [item["field"] for item in response.json()["error"]["details"]]


def error_code(response) -> str:
    return response.json()["error"]["code"]


def stored(db, user) -> Donor | None:
    return db.scalar(select(Donor).where(Donor.user_id == user.id))


def donor_count(db) -> int:
    return db.scalar(select(func.count()).select_from(Donor))


# ------------------------------------------------------------------- create


def test_donor_creates_their_profile(client, db, bank):
    response = create(client, donor_user(db), bank)
    assert response.status_code == 201
    assert response.json()["success"] is True
    data = response.json()["data"]
    assert data["id"]
    assert data["full_name"] == "Abebe Kebede"
    assert data["blood_type"] == "O+"
    assert data["gender"] == "male"
    assert data["date_of_birth"] == "1995-04-12"
    assert data["weight_kg"] == 68.5
    assert data["blood_bank_id"] == str(bank.id)
    assert data["blood_bank_name"] == "Central Blood Bank"
    assert data["verification_status"] == "unverified"
    assert data["is_available"] is True
    assert data["last_donation_date"] is None
    assert data["suspension_reason"] is None


def test_new_profile_is_unverified_available_and_linked_to_the_user(client, db, bank):
    user = donor_user(db)
    create(client, user, bank)
    donor = stored(db, user)
    assert donor is not None
    assert donor.verification_status == VerificationStatus.UNVERIFIED
    assert donor.is_available is True
    assert donor.blood_bank_id == bank.id
    assert donor.full_name == "Abebe Kebede"


def test_response_does_not_expose_internal_fields(client, db, bank):
    data = create(client, donor_user(db), bank).json()["data"]
    assert "user_id" not in data
    assert "suspended_by" not in data


@pytest.mark.parametrize(
    "field",
    [
        "verification_status",
        "is_available",
        "user_id",
        "id",
        "suspended_by",
        "suspension_reason",
    ],
)
def test_fields_the_client_must_not_set_are_rejected(client, db, bank, field):
    values = {
        "verification_status": "verified",
        "is_available": False,
        "user_id": str(uuid.uuid4()),
        "id": str(uuid.uuid4()),
        "suspended_by": str(uuid.uuid4()),
        "suspension_reason": "x",
    }
    user = donor_user(db)
    response = create(client, user, bank, **{field: values[field]})
    assert response.status_code == 422
    assert field in error_fields(response)
    assert stored(db, user) is None


def test_a_second_profile_is_refused(client, db, bank):
    user = donor_user(db)
    assert create(client, user, bank).status_code == 201
    response = create(client, user, bank, full_name="Another Name")
    assert response.status_code == 409
    assert error_code(response) == "PROFILE_ALREADY_EXISTS"
    assert donor_count(db) == 1
    assert stored(db, user).full_name == "Abebe Kebede"


@pytest.mark.parametrize(
    "role", [UserRole.HOSPITAL, UserRole.BLOOD_BANK, UserRole.ADMIN]
)
def test_other_roles_cannot_create_a_donor_profile(client, db, bank, role):
    response = create(client, make_user(db, role), bank)
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"
    assert donor_count(db) == 0


def test_creating_a_profile_requires_a_token(client, db, bank):
    response = client.post(URL, json=payload(bank))
    assert response.status_code == 401
    assert error_code(response) == "UNAUTHORIZED"


def test_a_deactivated_user_cannot_create_a_profile(client, db, bank):
    user = make_user(db, UserRole.DONOR, is_active=False)
    response = create(client, user, bank)
    assert response.status_code == 403
    assert "deactivated" in response.json()["error"]["message"]
    assert donor_count(db) == 0


def test_the_name_is_trimmed(client, db, bank):
    data = create(client, donor_user(db), bank, full_name="  Abebe Kebede  ").json()[
        "data"
    ]
    assert data["full_name"] == "Abebe Kebede"


@pytest.mark.parametrize("missing", REQUIRED_FIELDS)
def test_missing_required_fields_are_rejected(client, db, bank, missing):
    response = client.post(
        URL, json=payload(bank, drop=(missing,)), headers=auth_headers(donor_user(db))
    )
    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"
    assert missing in error_fields(response)


@pytest.mark.parametrize(
    "field,value",
    [
        ("full_name", ""),
        ("full_name", "   "),
        ("full_name", "x" * 256),
        ("blood_type", "Z+"),
        ("blood_type", ""),
        ("gender", "other"),
        ("date_of_birth", "not-a-date"),
        ("date_of_birth", "2999-01-01"),
        ("date_of_birth", "1850-01-01"),
        ("weight_kg", 19),
        ("weight_kg", 301),
        ("weight_kg", 0),
        ("weight_kg", -5),
        ("latitude", 91),
        ("longitude", -181),
        ("blood_bank_id", "not-a-uuid"),
    ],
)
def test_invalid_values_are_rejected(client, db, bank, field, value):
    response = create(client, donor_user(db), bank, **{field: value})
    assert response.status_code == 422
    assert field in error_fields(response)
    assert donor_count(db) == 0


@pytest.mark.parametrize("weight", [20, 49.9, 300])
def test_weight_at_the_limits_is_accepted_even_below_the_donation_minimum(
    client, db, bank, weight
):
    assert create(client, donor_user(db), bank, weight_kg=weight).status_code == 201


def test_a_donor_exactly_at_the_minimum_age_is_accepted(client, db, bank):
    born = years_ago(get_settings().MIN_AGE_YEARS)
    assert (
        create(client, donor_user(db), bank, date_of_birth=born.isoformat()).status_code
        == 201
    )


def test_a_donor_one_day_short_of_the_minimum_age_is_refused(client, db, bank):
    born = years_ago(get_settings().MIN_AGE_YEARS) + timedelta(days=1)
    response = create(client, donor_user(db), bank, date_of_birth=born.isoformat())
    assert response.status_code == 422
    assert "date_of_birth" in error_fields(response)
    assert "at least" in response.json()["error"]["details"][0]["message"]
    assert donor_count(db) == 0


def test_a_last_donation_date_can_be_given_at_registration(client, db, bank):
    data = create(client, donor_user(db), bank, last_donation_date="2024-01-15").json()[
        "data"
    ]
    assert data["last_donation_date"] == "2024-01-15"


@pytest.mark.parametrize(
    "bad_date", [TOMORROW, "1990-01-01"], ids=["in the future", "before birth"]
)
def test_an_impossible_last_donation_date_is_rejected(client, db, bank, bad_date):
    response = create(client, donor_user(db), bank, last_donation_date=bad_date)
    assert response.status_code == 422
    assert "last_donation_date" in error_fields(response)
    assert donor_count(db) == 0


def test_an_unknown_blood_bank_is_refused(client, db, bank):
    response = create(client, donor_user(db), bank, blood_bank_id=str(uuid.uuid4()))
    assert response.status_code == 400
    assert error_code(response) == "BAD_REQUEST"
    assert "not available" in response.json()["error"]["message"]
    assert donor_count(db) == 0


@pytest.mark.parametrize(
    "bank_options",
    [
        {"approval_status": ApprovalStatus.PENDING},
        {"approval_status": ApprovalStatus.SUSPENDED},
        {"is_active": False},
    ],
    ids=["pending", "suspended", "paused"],
)
def test_a_blood_bank_that_is_not_available_is_refused(client, db, bank, bank_options):
    unavailable = make_blood_bank(db, **bank_options)
    response = create(client, donor_user(db), bank, blood_bank_id=str(unavailable.id))
    assert response.status_code == 400
    assert error_code(response) == "BAD_REQUEST"
    assert donor_count(db) == 0


# --------------------------------------------------------------------- read


def test_donor_reads_their_own_profile(client, db, bank):
    user = donor_user(db)
    make_donor(db, user=user, blood_bank=bank, full_name="My Name")
    response = client.get(URL, headers=auth_headers(user))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["full_name"] == "My Name"
    assert data["blood_bank_name"] == "Central Blood Bank"
    assert data["verification_status"] == "unverified"
    assert data["suspension_reason"] is None


def test_reading_before_creating_a_profile_gives_404(client, db):
    response = client.get(URL, headers=auth_headers(donor_user(db)))
    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_each_donor_sees_only_their_own_profile(client, db, bank):
    first, second = donor_user(db), donor_user(db)
    make_donor(db, user=first, blood_bank=bank, full_name="First Donor")
    make_donor(db, user=second, blood_bank=bank, full_name="Second Donor")
    assert (
        client.get(URL, headers=auth_headers(first)).json()["data"]["full_name"]
        == "First Donor"
    )
    assert (
        client.get(URL, headers=auth_headers(second)).json()["data"]["full_name"]
        == "Second Donor"
    )


@pytest.mark.parametrize("verification", list(VerificationStatus))
def test_a_donor_can_read_their_profile_in_every_verification_status(
    client, db, bank, verification
):
    user = donor_user(db)
    make_donor(db, user=user, blood_bank=bank, verification_status=verification)
    response = client.get(URL, headers=auth_headers(user))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["verification_status"] == verification.value
    if verification == VerificationStatus.SUSPENDED:
        assert data["suspension_reason"] == "test reason"
        assert data["suspended_at"] is not None
    else:
        assert data["suspension_reason"] is None


@pytest.mark.parametrize(
    "role", [UserRole.HOSPITAL, UserRole.BLOOD_BANK, UserRole.ADMIN]
)
def test_other_roles_cannot_read_a_donor_profile(client, db, role):
    response = client.get(URL, headers=auth_headers(make_user(db, role)))
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_reading_a_profile_requires_a_token(client, db):
    assert client.get(URL).status_code == 401


# ------------------------------------------------------------------- update


def test_donor_updates_their_profile(client, db, bank):
    user = donor_user(db)
    donor = make_donor(db, user=user, blood_bank=bank)
    response = update(
        client,
        user,
        full_name="New Name",
        blood_type="A+",
        gender="female",
        date_of_birth="1990-02-03",
        weight_kg=72.0,
        latitude=8.54,
        longitude=39.27,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["full_name"] == "New Name"
    assert data["blood_type"] == "A+"
    assert data["gender"] == "female"
    assert data["date_of_birth"] == "1990-02-03"
    assert data["weight_kg"] == 72.0
    assert data["latitude"] == 8.54
    db.refresh(donor)
    assert donor.full_name == "New Name"
    assert donor.longitude == 39.27


def test_an_update_never_changes_verification_availability_or_blood_bank(
    client, db, bank
):
    user = donor_user(db)
    donor = make_donor(
        db,
        user=user,
        blood_bank=bank,
        verification_status=VerificationStatus.VERIFIED,
        is_available=False,
    )
    response = update(client, user, full_name="Renamed")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["verification_status"] == "verified"
    assert data["is_available"] is False
    assert data["blood_bank_id"] == str(bank.id)
    db.refresh(donor)
    assert donor.verification_status == VerificationStatus.VERIFIED
    assert donor.is_available is False


def test_updating_before_creating_a_profile_gives_404(client, db):
    response = update(client, donor_user(db))
    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_an_update_only_changes_the_callers_own_profile(client, db, bank):
    first, second = donor_user(db), donor_user(db)
    make_donor(db, user=first, blood_bank=bank, full_name="First Donor")
    other = make_donor(db, user=second, blood_bank=bank, full_name="Second Donor")
    update(client, first, full_name="First Renamed")
    db.refresh(other)
    assert other.full_name == "Second Donor"


@pytest.mark.parametrize(
    "field", ["blood_bank_id", "verification_status", "is_available", "user_id"]
)
def test_update_rejects_fields_the_client_must_not_set(client, db, bank, field):
    values = {
        "blood_bank_id": str(bank.id),
        "verification_status": "verified",
        "is_available": False,
        "user_id": str(uuid.uuid4()),
    }
    user = donor_user(db)
    make_donor(db, user=user, blood_bank=bank)
    response = update(client, user, **{field: values[field]})
    assert response.status_code == 422
    assert field in error_fields(response)
    assert stored(db, user).verification_status == VerificationStatus.UNVERIFIED


@pytest.mark.parametrize("missing", ["full_name", "date_of_birth", "weight_kg"])
def test_update_needs_every_required_field(client, db, bank, missing):
    user = donor_user(db)
    make_donor(db, user=user, blood_bank=bank)
    response = client.put(
        URL, json=update_payload(drop=(missing,)), headers=auth_headers(user)
    )
    assert response.status_code == 422
    assert missing in error_fields(response)


@pytest.mark.parametrize(
    "field,value",
    [("weight_kg", 19), ("date_of_birth", TOMORROW), ("latitude", 91)],
)
def test_update_validates_values_like_create(client, db, bank, field, value):
    user = donor_user(db)
    make_donor(db, user=user, blood_bank=bank)
    response = update(client, user, **{field: value})
    assert response.status_code == 422
    assert field in error_fields(response)


def test_updating_requires_a_token(client, db):
    assert client.put(URL, json=update_payload()).status_code == 401


@pytest.mark.parametrize(
    "role", [UserRole.HOSPITAL, UserRole.BLOOD_BANK, UserRole.ADMIN]
)
def test_other_roles_cannot_update_a_donor_profile(client, db, role):
    response = update(client, make_user(db, role))
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_a_suspended_donor_can_edit_their_details_but_stays_suspended(client, db, bank):
    user = donor_user(db)
    donor = make_donor(
        db, user=user, blood_bank=bank, verification_status=VerificationStatus.SUSPENDED
    )
    response = update(client, user, full_name="Renamed")
    assert response.status_code == 200
    assert response.json()["data"]["verification_status"] == "suspended"
    db.refresh(donor)
    assert donor.full_name == "Renamed"
    assert donor.verification_status == VerificationStatus.SUSPENDED


# ------------------------------------------- last donation date on update


def test_a_first_last_donation_date_can_be_set(client, db, bank):
    user = donor_user(db)
    donor = make_donor(db, user=user, blood_bank=bank)
    response = update(client, user, last_donation_date="2024-03-01")
    assert response.status_code == 200
    assert response.json()["data"]["last_donation_date"] == "2024-03-01"
    db.refresh(donor)
    assert donor.last_donation_date == date(2024, 3, 1)


def test_the_last_donation_date_can_move_forward(client, db, bank):
    user = donor_user(db)
    donor = make_donor(
        db, user=user, blood_bank=bank, last_donation_date=date(2024, 1, 1)
    )
    assert update(client, user, last_donation_date="2024-06-01").status_code == 200
    db.refresh(donor)
    assert donor.last_donation_date == date(2024, 6, 1)


def test_the_last_donation_date_cannot_move_earlier(client, db, bank):
    user = donor_user(db)
    donor = make_donor(
        db, user=user, blood_bank=bank, last_donation_date=date(2024, 6, 1)
    )
    response = update(client, user, last_donation_date="2024-01-01")
    assert response.status_code == 400
    assert error_code(response) == "BAD_REQUEST"
    assert "earlier" in response.json()["error"]["message"]
    db.refresh(donor)
    assert donor.last_donation_date == date(2024, 6, 1)


def test_leaving_the_date_out_keeps_the_recorded_one(client, db, bank):
    user = donor_user(db)
    donor = make_donor(
        db, user=user, blood_bank=bank, last_donation_date=date(2024, 6, 1)
    )
    response = update(client, user, full_name="Renamed")
    assert response.status_code == 200
    assert response.json()["data"]["last_donation_date"] == "2024-06-01"
    db.refresh(donor)
    assert donor.last_donation_date == date(2024, 6, 1)


def test_sending_null_does_not_erase_the_recorded_date(client, db, bank):
    user = donor_user(db)
    donor = make_donor(
        db, user=user, blood_bank=bank, last_donation_date=date(2024, 6, 1)
    )
    response = update(client, user, last_donation_date=None)
    assert response.status_code == 200
    db.refresh(donor)
    assert donor.last_donation_date == date(2024, 6, 1)


def test_sending_the_same_date_again_is_accepted(client, db, bank):
    user = donor_user(db)
    make_donor(db, user=user, blood_bank=bank, last_donation_date=date(2024, 6, 1))
    assert update(client, user, last_donation_date="2024-06-01").status_code == 200


# ------------------------------------------------------------- availability


def test_a_donor_turns_availability_off_and_on(client, db, bank):
    user = donor_user(db)
    donor = make_donor(db, user=user, blood_bank=bank)
    off = client.patch(
        AVAILABILITY_URL, json={"is_available": False}, headers=auth_headers(user)
    )
    assert off.status_code == 200
    assert off.json()["data"]["is_available"] is False
    db.refresh(donor)
    assert donor.is_available is False

    on = client.patch(
        AVAILABILITY_URL, json={"is_available": True}, headers=auth_headers(user)
    )
    assert on.json()["data"]["is_available"] is True
    db.refresh(donor)
    assert donor.is_available is True


@pytest.mark.parametrize(
    "body",
    [
        {"is_available": "yes"},
        {"is_available": "false"},
        {"is_available": 1},
        {},
        {"is_available": None},
        {"is_available": True, "verification_status": "verified"},
    ],
    ids=["yes", "string false", "number", "empty body", "null", "extra field"],
)
def test_availability_only_accepts_a_real_true_or_false(client, db, bank, body):
    user = donor_user(db)
    make_donor(db, user=user, blood_bank=bank)
    response = client.patch(AVAILABILITY_URL, json=body, headers=auth_headers(user))
    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_availability_before_creating_a_profile_gives_404(client, db):
    response = client.patch(
        AVAILABILITY_URL,
        json={"is_available": False},
        headers=auth_headers(donor_user(db)),
    )
    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


@pytest.mark.parametrize(
    "role", [UserRole.HOSPITAL, UserRole.BLOOD_BANK, UserRole.ADMIN]
)
def test_other_roles_cannot_change_availability(client, db, role):
    response = client.patch(
        AVAILABILITY_URL,
        json={"is_available": False},
        headers=auth_headers(make_user(db, role)),
    )
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_changing_availability_requires_a_token(client, db):
    assert (
        client.patch(AVAILABILITY_URL, json={"is_available": False}).status_code == 401
    )


def test_changing_availability_leaves_everything_else_alone(client, db, bank):
    user = donor_user(db)
    make_donor(
        db, user=user, blood_bank=bank, verification_status=VerificationStatus.VERIFIED
    )
    data = client.patch(
        AVAILABILITY_URL, json={"is_available": False}, headers=auth_headers(user)
    ).json()["data"]
    assert data["verification_status"] == "verified"
    assert data["blood_type"] == "O+"


def test_availability_only_changes_the_callers_own_profile(client, db, bank):
    first, second = donor_user(db), donor_user(db)
    make_donor(db, user=first, blood_bank=bank)
    other = make_donor(db, user=second, blood_bank=bank)
    client.patch(
        AVAILABILITY_URL, json={"is_available": False}, headers=auth_headers(first)
    )
    db.refresh(other)
    assert other.is_available is True


# ------------------------------------------------- the CurrentDonor dependency


def _me(donor: CurrentDonor):
    return {"id": str(donor.id), "verification_status": donor.verification_status.value}


def _my_match(match_id: uuid.UUID, donor: CurrentDonor, db: DbSession):
    return {"id": str(get_match_for_donor(db, match_id, donor).id)}


@pytest.fixture()
def donor_routes(app, client):
    """The test client, plus throw-away routes that use CurrentDonor."""
    app.add_api_route("/_test/donor-me", _me, methods=["GET"])
    app.add_api_route("/_test/donor-matches/{match_id}", _my_match, methods=["GET"])
    return client


def test_current_donor_is_the_callers_own_profile(donor_routes, db, bank):
    user = donor_user(db)
    donor = make_donor(db, user=user, blood_bank=bank)
    response = donor_routes.get("/_test/donor-me", headers=auth_headers(user))
    assert response.status_code == 200
    assert response.json()["id"] == str(donor.id)


def test_current_donor_without_a_profile_gives_404(donor_routes, db):
    response = donor_routes.get("/_test/donor-me", headers=auth_headers(donor_user(db)))
    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


@pytest.mark.parametrize(
    "role", [UserRole.HOSPITAL, UserRole.BLOOD_BANK, UserRole.ADMIN]
)
def test_current_donor_is_for_donors_only(donor_routes, db, role):
    response = donor_routes.get(
        "/_test/donor-me", headers=auth_headers(make_user(db, role))
    )
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_current_donor_requires_a_token(donor_routes):
    assert donor_routes.get("/_test/donor-me").status_code == 401


def test_a_donor_reads_their_own_match_through_current_donor(donor_routes, db, bank):
    user = donor_user(db)
    donor = make_donor(db, user=user, blood_bank=bank)
    match = make_match(db, donor=donor)
    response = donor_routes.get(
        f"/_test/donor-matches/{match.id}", headers=auth_headers(user)
    )
    assert response.status_code == 200
    assert response.json() == {"id": str(match.id)}


def test_a_donor_cannot_read_another_donors_match(donor_routes, db, bank):
    user = donor_user(db)
    make_donor(db, user=user, blood_bank=bank)
    others_match = make_match(db, donor=make_donor(db, blood_bank=bank))
    response = donor_routes.get(
        f"/_test/donor-matches/{others_match.id}", headers=auth_headers(user)
    )
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_current_donor_does_not_block_suspended_donors(donor_routes, db, bank):
    user = donor_user(db)
    make_donor(
        db, user=user, blood_bank=bank, verification_status=VerificationStatus.SUSPENDED
    )
    response = donor_routes.get("/_test/donor-me", headers=auth_headers(user))
    assert response.status_code == 200
    assert response.json()["verification_status"] == "suspended"
