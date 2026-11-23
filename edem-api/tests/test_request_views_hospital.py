import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import get_settings
from app.models.enums import ApprovalStatus, MatchStatus, RequestStatus, UserRole
from tests.factories import (
    auth_headers,
    make_blood_request,
    make_donor,
    make_history,
    make_hospital,
    make_match,
    make_user,
)

URL = "/v1/hospitals/requests"
BASE = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)

APPROVAL_STATES = [ApprovalStatus.PENDING, ApprovalStatus.SUSPENDED]
OTHER_ROLES = [UserRole.DONOR, UserRole.BLOOD_BANK, UserRole.ADMIN]
VISIBLE = [
    MatchStatus.ACCEPTED,
    MatchStatus.ARRIVED,
    MatchStatus.DONATED,
    MatchStatus.DEFERRED,
]
HIDDEN = [
    MatchStatus.NOTIFIED,
    MatchStatus.DECLINED,
    MatchStatus.EXPIRED,
    MatchStatus.NO_SHOW,
    MatchStatus.RELEASED,
]


def hospital_account(db, approval=ApprovalStatus.APPROVED):
    user = make_user(db, UserRole.HOSPITAL)
    return user, make_hospital(db, user=user, approval_status=approval)


def fetch(client, user, path=""):
    return client.get(f"{URL}{path}", headers=auth_headers(user))


def error_code(response) -> str:
    return response.json()["error"]["code"]


def item_ids(response) -> list[str]:
    return [item["id"] for item in response.json()["data"]["items"]]


# ============================================================ GET /requests


def test_the_list_shows_own_requests_newest_first(client, db):
    user, hospital = hospital_account(db)
    oldest = make_blood_request(db, hospital=hospital, created_at=BASE)
    middle = make_blood_request(
        db, hospital=hospital, created_at=BASE + timedelta(minutes=5)
    )
    newest = make_blood_request(
        db, hospital=hospital, created_at=BASE + timedelta(minutes=10)
    )
    assert item_ids(fetch(client, user)) == [
        str(newest.id),
        str(middle.id),
        str(oldest.id),
    ]


def test_the_list_never_includes_another_hospitals_requests(client, db):
    user, hospital = hospital_account(db)
    mine = make_blood_request(db, hospital=hospital)
    make_blood_request(db)  # another hospital's request
    assert item_ids(fetch(client, user)) == [str(mine.id)]


def test_an_empty_list_has_the_standard_shape(client, db):
    user, _ = hospital_account(db)
    response = fetch(client, user)
    assert response.status_code == 200
    assert response.json()["data"] == {
        "items": [],
        "page": 1,
        "page_size": get_settings().DEFAULT_PAGE_SIZE,
        "total": 0,
    }


def test_the_list_is_paginated_and_reports_the_total(client, db):
    user, hospital = hospital_account(db)
    requests = [
        make_blood_request(
            db, hospital=hospital, created_at=BASE + timedelta(minutes=minute)
        )
        for minute in range(5)
    ]
    newest_first = [str(request.id) for request in reversed(requests)]
    first = fetch(client, user, "?page=1&page_size=2")
    second = fetch(client, user, "?page=2&page_size=2")
    third = fetch(client, user, "?page=3&page_size=2")
    assert item_ids(first) == newest_first[:2]
    assert item_ids(second) == newest_first[2:4]
    assert item_ids(third) == newest_first[4:]
    assert first.json()["data"]["total"] == 5


def test_the_list_can_be_filtered_by_status(client, db):
    user, hospital = hospital_account(db)
    matching = make_blood_request(
        db, hospital=hospital, status=RequestStatus.MATCHING_DONORS
    )
    make_blood_request(db, hospital=hospital, status=RequestStatus.PENDING_BLOOD_BANK)
    make_blood_request(db, hospital=hospital, status=RequestStatus.FULFILLED)
    response = fetch(client, user, "?status=matching_donors")
    assert item_ids(response) == [str(matching.id)]
    assert response.json()["data"]["total"] == 1


def test_an_unknown_status_filter_is_rejected(client, db):
    user, _ = hospital_account(db)
    response = fetch(client, user, "?status=bogus")
    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"
    assert "status" in [item["field"] for item in response.json()["error"]["details"]]


def test_each_item_carries_the_counters_and_the_units_still_needed(client, db):
    user, hospital = hospital_account(db)
    make_blood_request(
        db, hospital=hospital, units_needed=3, units_from_inventory=1, units_confirmed=1
    )
    [item] = fetch(client, user).json()["data"]["items"]
    assert item["units_needed"] == 3
    assert item["units_from_inventory"] == 1
    assert item["units_confirmed"] == 1
    assert item["units_remaining"] == 1
    for field in (
        "id",
        "status",
        "urgency",
        "blood_type",
        "response_deadline",
        "current_batch",
        "created_at",
    ):
        assert field in item


@pytest.mark.parametrize("approval", APPROVAL_STATES)
def test_a_hospital_that_is_not_approved_cannot_list_requests(client, db, approval):
    user, _ = hospital_account(db, approval)
    response = fetch(client, user)
    assert response.status_code == 403
    assert error_code(response) == "ACCOUNT_NOT_APPROVED"


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_other_roles_cannot_list_hospital_requests(client, db, role):
    response = fetch(client, make_user(db, role))
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_listing_requires_a_login(client, db):
    assert client.get(URL).status_code == 401


def test_the_detail_view_also_reports_the_units_still_needed(client, db):
    user, hospital = hospital_account(db)
    blood_request = make_blood_request(
        db, hospital=hospital, units_needed=4, units_confirmed=1
    )
    data = fetch(client, user, f"/{blood_request.id}").json()["data"]
    assert data["units_remaining"] == 3


# ================================================= GET /requests/{id}/history


def test_the_timeline_is_listed_oldest_first_with_its_details(client, db):
    user, hospital = hospital_account(db)
    blood_request = make_blood_request(db, hospital=hospital)
    make_history(
        db,
        blood_request,
        None,
        RequestStatus.PENDING_BLOOD_BANK,
        changed_by=user,
        note="Request created",
        created_at=BASE,
    )
    make_history(
        db,
        blood_request,
        RequestStatus.PENDING_BLOOD_BANK,
        RequestStatus.MATCHING_DONORS,
        note="Blood bank response timeout",
        created_at=BASE + timedelta(minutes=10),
    )
    items = fetch(client, user, f"/{blood_request.id}/history").json()["data"]["items"]
    assert [(item["from_status"], item["to_status"]) for item in items] == [
        (None, "pending_blood_bank"),
        ("pending_blood_bank", "matching_donors"),
    ]
    assert [item["note"] for item in items] == [
        "Request created",
        "Blood bank response timeout",
    ]


def test_the_actor_is_system_when_nobody_made_the_change(client, db):
    user, hospital = hospital_account(db)
    blood_request = make_blood_request(db, hospital=hospital)
    make_history(
        db,
        blood_request,
        RequestStatus.PENDING_BLOOD_BANK,
        RequestStatus.MATCHING_DONORS,
    )
    [item] = fetch(client, user, f"/{blood_request.id}/history").json()["data"]["items"]
    assert item["actor"] == "system"


@pytest.mark.parametrize(
    "role", [UserRole.HOSPITAL, UserRole.BLOOD_BANK, UserRole.ADMIN]
)
def test_the_actor_is_the_role_of_the_person_who_made_the_change(client, db, role):
    user, hospital = hospital_account(db)
    blood_request = make_blood_request(db, hospital=hospital)
    make_history(
        db,
        blood_request,
        RequestStatus.PENDING_BLOOD_BANK,
        RequestStatus.MATCHING_DONORS,
        changed_by=make_user(db, role),
    )
    [item] = fetch(client, user, f"/{blood_request.id}/history").json()["data"]["items"]
    assert item["actor"] == role.value


def test_a_timeline_entry_exposes_no_user_ids(client, db):
    user, hospital = hospital_account(db)
    blood_request = make_blood_request(db, hospital=hospital)
    make_history(
        db, blood_request, None, RequestStatus.PENDING_BLOOD_BANK, changed_by=user
    )
    [item] = fetch(client, user, f"/{blood_request.id}/history").json()["data"]["items"]
    assert set(item) == {"from_status", "to_status", "actor", "note", "created_at"}


def test_a_request_without_history_gives_an_empty_timeline(client, db):
    user, hospital = hospital_account(db)
    blood_request = make_blood_request(db, hospital=hospital)
    assert fetch(client, user, f"/{blood_request.id}/history").json()["data"] == {
        "items": []
    }


def test_another_hospitals_timeline_is_forbidden(client, db):
    user, _ = hospital_account(db)
    others = make_blood_request(db)
    response = fetch(client, user, f"/{others.id}/history")
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_an_unknown_request_has_no_timeline(client, db):
    user, _ = hospital_account(db)
    response = fetch(client, user, f"/{uuid.uuid4()}/history")
    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


@pytest.mark.parametrize("approval", APPROVAL_STATES)
def test_a_hospital_that_is_not_approved_cannot_read_a_timeline(client, db, approval):
    user, hospital = hospital_account(db, approval)
    blood_request = make_blood_request(db, hospital=hospital)
    response = fetch(client, user, f"/{blood_request.id}/history")
    assert response.status_code == 403
    assert error_code(response) == "ACCOUNT_NOT_APPROVED"


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_other_roles_cannot_read_a_timeline(client, db, role):
    blood_request = make_blood_request(db)
    response = fetch(client, make_user(db, role), f"/{blood_request.id}/history")
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_a_timeline_requires_a_login(client, db):
    blood_request = make_blood_request(db)
    assert client.get(f"{URL}/{blood_request.id}/history").status_code == 401


def test_a_malformed_request_id_is_rejected_for_the_timeline(client, db):
    user, _ = hospital_account(db)
    assert fetch(client, user, "/not-a-uuid/history").status_code == 422


# ================================================ GET /requests/{id}/matches


def test_matches_are_listed_by_batch_and_then_by_distance(client, db):
    user, hospital = hospital_account(db)
    blood_request = make_blood_request(db, hospital=hospital)
    second_batch = make_match(
        db, blood_request=blood_request, batch_number=2, distance_km=1.0
    )
    far = make_match(db, blood_request=blood_request, batch_number=1, distance_km=5.0)
    near = make_match(db, blood_request=blood_request, batch_number=1, distance_km=2.0)
    items = fetch(client, user, f"/{blood_request.id}/matches").json()["data"]["items"]
    assert [item["match_id"] for item in items] == [
        str(near.id),
        str(far.id),
        str(second_batch.id),
    ]


@pytest.mark.parametrize("match_status", VISIBLE)
def test_a_hospital_sees_the_details_of_donors_it_deals_with_in_person(
    client, db, match_status
):
    user, hospital = hospital_account(db)
    blood_request = make_blood_request(db, hospital=hospital)
    donor = make_donor(db, full_name="Abebe Kebede")
    make_match(db, blood_request=blood_request, donor=donor, status=match_status)
    [item] = fetch(client, user, f"/{blood_request.id}/matches").json()["data"]["items"]
    assert item["status"] == match_status.value
    assert item["donor"] == {
        "full_name": "Abebe Kebede",
        "blood_type": "O+",
        "phone": "+251911234567",
    }


@pytest.mark.parametrize("match_status", HIDDEN)
def test_a_hospital_does_not_see_the_details_of_other_donors(client, db, match_status):
    user, hospital = hospital_account(db)
    blood_request = make_blood_request(db, hospital=hospital)
    make_match(db, blood_request=blood_request, status=match_status)
    [item] = fetch(client, user, f"/{blood_request.id}/matches").json()["data"]["items"]
    assert item["status"] == match_status.value
    assert item["donor"] is None


def test_a_match_exposes_nothing_beyond_what_the_hospital_needs(client, db):
    user, hospital = hospital_account(db)
    blood_request = make_blood_request(db, hospital=hospital)
    make_match(db, blood_request=blood_request, status=MatchStatus.ACCEPTED)
    [item] = fetch(client, user, f"/{blood_request.id}/matches").json()["data"]["items"]
    assert set(item) == {
        "match_id",
        "batch_number",
        "status",
        "distance_km",
        "notified_at",
        "responded_at",
        "arrived_at",
        "donated_at",
        "donor",
    }
    assert set(item["donor"]) == {"full_name", "blood_type", "phone"}


def test_the_matches_come_with_a_count_per_status(client, db):
    user, hospital = hospital_account(db)
    blood_request = make_blood_request(db, hospital=hospital)
    for match_status in (
        MatchStatus.ACCEPTED,
        MatchStatus.ACCEPTED,
        MatchStatus.DECLINED,
    ):
        make_match(db, blood_request=blood_request, status=match_status)
    data = fetch(client, user, f"/{blood_request.id}/matches").json()["data"]
    assert data["counts"] == {"accepted": 2, "declined": 1}


def test_a_request_without_matches_gives_empty_results(client, db):
    user, hospital = hospital_account(db)
    blood_request = make_blood_request(db, hospital=hospital)
    assert fetch(client, user, f"/{blood_request.id}/matches").json()["data"] == {
        "items": [],
        "counts": {},
    }


def test_matches_of_other_requests_are_not_listed(client, db):
    user, hospital = hospital_account(db)
    blood_request = make_blood_request(db, hospital=hospital)
    other_request = make_blood_request(db, hospital=hospital)
    make_match(db, blood_request=other_request)
    assert (
        fetch(client, user, f"/{blood_request.id}/matches").json()["data"]["items"]
        == []
    )


def test_another_hospitals_matches_are_forbidden(client, db):
    user, _ = hospital_account(db)
    others = make_blood_request(db)
    make_match(db, blood_request=others, status=MatchStatus.ACCEPTED)
    response = fetch(client, user, f"/{others.id}/matches")
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_an_unknown_request_has_no_matches(client, db):
    user, _ = hospital_account(db)
    response = fetch(client, user, f"/{uuid.uuid4()}/matches")
    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


@pytest.mark.parametrize("approval", APPROVAL_STATES)
def test_a_hospital_that_is_not_approved_cannot_read_matches(client, db, approval):
    user, hospital = hospital_account(db, approval)
    blood_request = make_blood_request(db, hospital=hospital)
    response = fetch(client, user, f"/{blood_request.id}/matches")
    assert response.status_code == 403
    assert error_code(response) == "ACCOUNT_NOT_APPROVED"


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_other_roles_cannot_read_matches(client, db, role):
    blood_request = make_blood_request(db)
    response = fetch(client, make_user(db, role), f"/{blood_request.id}/matches")
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_matches_require_a_login(client, db):
    blood_request = make_blood_request(db)
    assert client.get(f"{URL}/{blood_request.id}/matches").status_code == 401
