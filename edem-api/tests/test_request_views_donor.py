import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import get_settings
from app.models.enums import MatchStatus as M
from app.models.enums import RequestStatus as R
from app.models.enums import UserRole, VerificationStatus
from tests.factories import (
    auth_headers,
    make_blood_request,
    make_donor,
    make_hospital,
    make_match,
    make_user,
)

URL = "/v1/donors/requests"
BASE = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)

OTHER_ROLES = [UserRole.HOSPITAL, UserRole.BLOOD_BANK, UserRole.ADMIN]

# (match status, request status, included when only open requests are asked for)
OPEN_CASES = [
    (M.NOTIFIED, R.MATCHING_DONORS, True),
    (M.ACCEPTED, R.MATCHING_DONORS, True),
    (M.ARRIVED, R.MATCHING_DONORS, True),
    (M.DECLINED, R.MATCHING_DONORS, False),
    (M.EXPIRED, R.MATCHING_DONORS, False),
    (M.DONATED, R.MATCHING_DONORS, False),
    (M.DEFERRED, R.MATCHING_DONORS, False),
    (M.NO_SHOW, R.MATCHING_DONORS, False),
    (M.RELEASED, R.MATCHING_DONORS, False),
    (M.NOTIFIED, R.FULFILLED, False),
    (M.NOTIFIED, R.CANCELLED, False),
    (M.NOTIFIED, R.UNFULFILLED, False),
]

# (match status, request status, donor verification, can the donor respond?)
RESPOND_CASES = [
    (M.NOTIFIED, R.MATCHING_DONORS, VerificationStatus.UNVERIFIED, True),
    (M.NOTIFIED, R.MATCHING_DONORS, VerificationStatus.VERIFIED, True),
    (M.NOTIFIED, R.MATCHING_DONORS, VerificationStatus.SUSPENDED, False),
    (M.NOTIFIED, R.FULFILLED, VerificationStatus.UNVERIFIED, False),
    (M.NOTIFIED, R.CANCELLED, VerificationStatus.UNVERIFIED, False),
    (M.ACCEPTED, R.MATCHING_DONORS, VerificationStatus.UNVERIFIED, False),
    (M.DECLINED, R.MATCHING_DONORS, VerificationStatus.UNVERIFIED, False),
    (M.EXPIRED, R.MATCHING_DONORS, VerificationStatus.UNVERIFIED, False),
]


def donor_account(db, **options):
    user = make_user(db, UserRole.DONOR)
    return user, make_donor(db, user=user, **options)


def hospital_request(db, status=R.MATCHING_DONORS, **options):
    hospital = make_hospital(db, name="Tikur Anbessa Hospital")
    return make_blood_request(db, hospital=hospital, status=status, **options)


def fetch(client, user, path=""):
    return client.get(f"{URL}{path}", headers=auth_headers(user))


def error_code(response) -> str:
    return response.json()["error"]["code"]


def match_ids(response) -> list[str]:
    return [item["match_id"] for item in response.json()["data"]["items"]]


# ============================================================ GET /requests


def test_the_list_shows_the_requests_sent_to_the_donor_with_the_hospital_details(
    client, db
):
    user, donor = donor_account(db)
    blood_request = hospital_request(
        db, units_needed=3, units_confirmed=1, urgency="critical"
    )
    match = make_match(db, blood_request=blood_request, donor=donor, distance_km=4.2)

    [item] = fetch(client, user).json()["data"]["items"]
    assert item["match_id"] == str(match.id)
    assert item["match_status"] == "notified"
    assert item["distance_km"] == 4.2
    assert item["can_respond"] is True
    assert item["request"]["id"] == str(blood_request.id)
    assert item["request"]["blood_type"] == "O+"
    assert item["request"]["units_needed"] == 3
    assert item["request"]["units_confirmed"] == 1
    assert item["request"]["units_remaining"] == 2
    assert item["request"]["urgency"] == "critical"
    assert item["request"]["status"] == "matching_donors"
    assert item["hospital"]["name"] == "Tikur Anbessa Hospital"
    assert item["hospital"]["address"] == "Bole Road"
    assert item["hospital"]["city"] == "Addis Ababa"
    assert item["hospital"]["contact_phone"] == "+251111234568"
    assert "latitude" in item["hospital"] and "longitude" in item["hospital"]


def test_a_donor_never_sees_requests_sent_to_other_donors(client, db):
    user, donor = donor_account(db)
    mine = make_match(db, blood_request=hospital_request(db), donor=donor)
    make_match(db, blood_request=hospital_request(db), donor=make_donor(db))
    assert match_ids(fetch(client, user)) == [str(mine.id)]


def test_the_newest_request_comes_first(client, db):
    user, donor = donor_account(db)
    old = make_match(
        db, blood_request=hospital_request(db), donor=donor, notified_at=BASE
    )
    new = make_match(
        db,
        blood_request=hospital_request(db),
        donor=donor,
        notified_at=BASE + timedelta(minutes=9),
    )
    assert match_ids(fetch(client, user)) == [str(new.id), str(old.id)]


@pytest.mark.parametrize("match_status,request_status,in_open_list", OPEN_CASES)
def test_the_open_only_filter_keeps_requests_still_in_progress(
    client, db, match_status, request_status, in_open_list
):
    user, donor = donor_account(db)
    match = make_match(
        db,
        blood_request=hospital_request(db, status=request_status),
        donor=donor,
        status=match_status,
    )
    assert match_ids(fetch(client, user)) == [
        str(match.id)
    ]  # everything is listed by default
    open_ids = match_ids(fetch(client, user, "?open_only=true"))
    assert (str(match.id) in open_ids) is in_open_list


def test_the_list_is_paginated_and_reports_the_total(client, db):
    user, donor = donor_account(db)
    matches = [
        make_match(
            db,
            blood_request=hospital_request(db),
            donor=donor,
            notified_at=BASE + timedelta(minutes=minute),
        )
        for minute in range(5)
    ]
    newest_first = [str(match.id) for match in reversed(matches)]
    first = fetch(client, user, "?page=1&page_size=2")
    third = fetch(client, user, "?page=3&page_size=2")
    assert match_ids(first) == newest_first[:2]
    assert match_ids(third) == newest_first[4:]
    assert first.json()["data"]["total"] == 5


def test_a_donor_sees_nothing_beyond_what_they_need(client, db):
    user, donor = donor_account(db)
    make_match(
        db,
        blood_request=hospital_request(db, notes="Patient: confidential details"),
        donor=donor,
    )
    response = fetch(client, user)
    [item] = response.json()["data"]["items"]
    assert set(item) == {
        "match_id",
        "match_status",
        "distance_km",
        "notified_at",
        "responded_at",
        "can_respond",
        "request",
        "hospital",
    }
    assert set(item["request"]) == {
        "id",
        "blood_type",
        "units_needed",
        "units_confirmed",
        "units_remaining",
        "urgency",
        "status",
        "created_at",
    }
    assert set(item["hospital"]) == {
        "name",
        "address",
        "city",
        "latitude",
        "longitude",
        "contact_phone",
    }
    assert "confidential" not in response.text


@pytest.mark.parametrize(
    "match_status,request_status,verification,expected", RESPOND_CASES
)
def test_can_respond_is_true_only_when_the_donor_can_still_answer(
    client, db, match_status, request_status, verification, expected
):
    user, donor = donor_account(db, verification_status=verification)
    make_match(
        db,
        blood_request=hospital_request(db, status=request_status),
        donor=donor,
        status=match_status,
    )
    [item] = fetch(client, user).json()["data"]["items"]
    assert item["can_respond"] is expected


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_other_roles_cannot_list_donor_requests(client, db, role):
    response = fetch(client, make_user(db, role))
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_listing_requires_a_login(client, db):
    assert client.get(URL).status_code == 401


def test_a_donor_without_a_profile_is_told_to_create_one(client, db):
    response = fetch(client, make_user(db, UserRole.DONOR))
    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_a_suspended_donor_can_still_read_their_requests(client, db):
    user, donor = donor_account(db, verification_status=VerificationStatus.SUSPENDED)
    make_match(db, blood_request=hospital_request(db), donor=donor)
    response = fetch(client, user)
    assert response.status_code == 200
    assert len(response.json()["data"]["items"]) == 1


def test_a_donor_with_no_requests_gets_an_empty_list(client, db):
    user, _ = donor_account(db)
    assert fetch(client, user).json()["data"] == {
        "items": [],
        "page": 1,
        "page_size": get_settings().DEFAULT_PAGE_SIZE,
        "total": 0,
    }


def test_invalid_page_values_are_rejected(client, db):
    user, _ = donor_account(db)
    response = fetch(client, user, "?page=0")
    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


# ====================================================== GET /requests/{match_id}


def test_a_donor_reads_one_request_with_its_progress_and_hospital(client, db):
    user, donor = donor_account(db)
    blood_request = hospital_request(db, units_needed=2)
    match = make_match(db, blood_request=blood_request, donor=donor)
    data = fetch(client, user, f"/{match.id}").json()["data"]
    assert data["match_id"] == str(match.id)
    assert data["request"]["units_needed"] == 2
    assert data["request"]["units_remaining"] == 2
    assert data["hospital"]["name"] == "Tikur Anbessa Hospital"
    assert data["can_respond"] is True


def test_the_progress_is_live(client, db):
    user, donor = donor_account(db)
    blood_request = hospital_request(db, units_needed=2)
    match = make_match(db, blood_request=blood_request, donor=donor)
    blood_request.units_confirmed = 1
    db.commit()
    data = fetch(client, user, f"/{match.id}").json()["data"]
    assert data["request"]["units_confirmed"] == 1
    assert data["request"]["units_remaining"] == 1


def test_the_detail_matches_the_item_in_the_list(client, db):
    user, donor = donor_account(db)
    match = make_match(db, blood_request=hospital_request(db), donor=donor)
    detail = fetch(client, user, f"/{match.id}").json()["data"]
    [listed] = fetch(client, user).json()["data"]["items"]
    assert detail == listed


def test_can_respond_turns_false_once_the_request_is_fulfilled(client, db):
    user, donor = donor_account(db)
    blood_request = hospital_request(db)
    match = make_match(db, blood_request=blood_request, donor=donor)
    assert fetch(client, user, f"/{match.id}").json()["data"]["can_respond"] is True
    blood_request.status = R.FULFILLED
    db.commit()
    assert fetch(client, user, f"/{match.id}").json()["data"]["can_respond"] is False


def test_another_donors_request_is_forbidden(client, db):
    user, _ = donor_account(db)
    others = make_match(db, blood_request=hospital_request(db), donor=make_donor(db))
    response = fetch(client, user, f"/{others.id}")
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_an_unknown_match_gives_404(client, db):
    user, _ = donor_account(db)
    response = fetch(client, user, f"/{uuid.uuid4()}")
    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_a_malformed_match_id_is_rejected(client, db):
    user, _ = donor_account(db)
    response = fetch(client, user, "/not-a-uuid")
    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_reading_one_request_requires_a_login(client, db):
    match = make_match(db, blood_request=hospital_request(db), donor=make_donor(db))
    assert client.get(f"{URL}/{match.id}").status_code == 401


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_other_roles_cannot_read_a_donor_request(client, db, role):
    match = make_match(db, blood_request=hospital_request(db), donor=make_donor(db))
    response = fetch(client, make_user(db, role), f"/{match.id}")
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_a_donor_without_a_profile_cannot_read_a_request(client, db):
    match = make_match(db, blood_request=hospital_request(db), donor=make_donor(db))
    response = fetch(client, make_user(db, UserRole.DONOR), f"/{match.id}")
    assert response.status_code == 404
