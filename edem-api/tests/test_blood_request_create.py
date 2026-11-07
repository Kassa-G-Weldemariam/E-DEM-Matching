import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models.blood_request import BloodRequest
from app.models.enums import ApprovalStatus, BloodType, RequestStatus, Urgency, UserRole
from app.models.request_status_history import RequestStatusHistory
from app.schemas.blood_request import BloodRequestCreate
from app.services.blood_requests import create_blood_request
from tests.factories import (
    auth_headers,
    make_blood_bank,
    make_blood_request,
    make_hospital,
    make_user,
)

URL = "/v1/hospitals/requests"
NOW = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)


def body(drop=(), **overrides) -> dict:
    data = {"blood_type": "O+", "units_needed": 2, "urgency": "urgent"}
    data.update(overrides)
    for key in drop:
        data.pop(key, None)
    return data


def data_for(**overrides: Any) -> BloodRequestCreate:
    values: dict[str, Any] = {
        "blood_type": BloodType.O_POS,
        "units_needed": 2,
        "urgency": Urgency.URGENT,
    }
    values.update(overrides)
    return BloodRequestCreate(**values)


def hospital_account(db, approval=ApprovalStatus.APPROVED, **hospital_options):
    user = make_user(db, UserRole.HOSPITAL)
    return user, make_hospital(
        db, user=user, approval_status=approval, **hospital_options
    )


def post(client, user, **overrides):
    return client.post(URL, json=body(**overrides), headers=auth_headers(user))


def error_fields(response) -> list[str]:
    return [item["field"] for item in response.json()["error"]["details"]]


def error_code(response) -> str:
    return response.json()["error"]["code"]


def request_count(db) -> int:
    return db.scalar(select(func.count()).select_from(BloodRequest))


def history_of(db, blood_request) -> list[RequestStatusHistory]:
    return list(
        db.scalars(
            select(RequestStatusHistory).where(
                RequestStatusHistory.request_id == blood_request.id
            )
        )
    )


@pytest.fixture()
def matching_calls(monkeypatch):
    """Replaces the matching stub and records which requests it was started for."""
    calls = []
    monkeypatch.setattr(
        "app.services.blood_requests.start_matching",
        lambda db, request: calls.append(request.id),
    )
    return calls


# ======================================================= the service itself


def test_a_request_stores_its_details_and_starts_pending(db, matching_calls):
    hospital = make_hospital(db)
    blood_request = create_blood_request(
        db,
        hospital,
        data_for(
            blood_type=BloodType.A_NEG, units_needed=3, notes="Surgery in progress"
        ),
        now=NOW,
    )
    assert blood_request.hospital_id == hospital.id
    assert blood_request.blood_bank_id == hospital.blood_bank_id
    assert blood_request.blood_type == BloodType.A_NEG
    assert blood_request.units_needed == 3
    assert blood_request.urgency == Urgency.URGENT
    assert blood_request.notes == "Surgery in progress"
    assert blood_request.status == RequestStatus.PENDING_BLOOD_BANK
    assert blood_request.latitude == hospital.latitude
    assert blood_request.longitude == hospital.longitude
    assert blood_request.units_from_inventory == 0
    assert blood_request.units_confirmed == 0
    assert blood_request.current_batch == 0
    assert blood_request.donor_deadline is None
    assert blood_request.response_deadline.tzinfo is not None


@pytest.mark.parametrize("urgency", list(Urgency))
def test_the_response_deadline_is_now_plus_the_blood_bank_timeout(
    db, matching_calls, urgency
):
    blood_request = create_blood_request(
        db, make_hospital(db), data_for(urgency=urgency), now=NOW
    )
    assert blood_request.response_deadline == NOW + get_settings().blood_bank_timeout(
        urgency.value
    )


def test_the_first_history_row_is_written(db, matching_calls):
    hospital = make_hospital(db)
    blood_request = create_blood_request(db, hospital, data_for(), now=NOW)
    rows = history_of(db, blood_request)
    assert len(rows) == 1
    assert rows[0].from_status is None
    assert rows[0].to_status == RequestStatus.PENDING_BLOOD_BANK
    assert rows[0].changed_by == hospital.user_id
    assert rows[0].note == "Request created"


@pytest.mark.parametrize(
    "bank_options",
    [{"is_active": False}, {"approval_status": ApprovalStatus.SUSPENDED}],
    ids=["paused", "suspended"],
)
def test_an_unavailable_blood_bank_sends_the_request_straight_to_matching(
    db, matching_calls, bank_options
):
    hospital = make_hospital(db, blood_bank=make_blood_bank(db, **bank_options))
    blood_request = create_blood_request(db, hospital, data_for(), now=NOW)
    assert blood_request.status == RequestStatus.MATCHING_DONORS
    assert blood_request.response_deadline is None
    rows = history_of(db, blood_request)
    assert len(rows) == 1
    assert rows[0].to_status == RequestStatus.MATCHING_DONORS
    assert "unavailable" in rows[0].note
    assert matching_calls == [blood_request.id]


def test_an_available_blood_bank_does_not_start_matching_yet(db, matching_calls):
    create_blood_request(db, make_hospital(db), data_for(), now=NOW)
    assert matching_calls == []


def test_a_matching_failure_does_not_undo_the_request(db, monkeypatch):
    def broken(db, request):
        raise RuntimeError("matching crashed")

    monkeypatch.setattr("app.services.blood_requests.start_matching", broken)
    hospital = make_hospital(db, blood_bank=make_blood_bank(db, is_active=False))
    blood_request = create_blood_request(db, hospital, data_for(), now=NOW)
    assert blood_request.status == RequestStatus.MATCHING_DONORS
    assert request_count(db) == 1


def test_exactly_one_request_and_one_history_row_are_created(db, matching_calls):
    create_blood_request(db, make_hospital(db), data_for(), now=NOW)
    assert request_count(db) == 1
    assert db.scalar(select(func.count()).select_from(RequestStatusHistory)) == 1


# =========================================================== POST over HTTP


def test_an_approved_hospital_creates_a_request(client, db):
    user, hospital = hospital_account(db)
    before = datetime.now(UTC)
    response = post(client, user, notes="Car accident")
    after = datetime.now(UTC)

    assert response.status_code == 201
    assert response.json()["success"] is True
    data = response.json()["data"]
    assert data["id"]
    assert data["hospital_id"] == str(hospital.id)
    assert data["blood_bank_id"] == str(hospital.blood_bank_id)
    assert data["blood_type"] == "O+"
    assert data["units_needed"] == 2
    assert data["urgency"] == "urgent"
    assert data["status"] == "pending_blood_bank"
    assert data["notes"] == "Car accident"
    assert data["units_from_inventory"] == 0 and data["units_confirmed"] == 0
    assert data["current_batch"] == 0 and data["donor_deadline"] is None

    timeout = get_settings().blood_bank_timeout("urgent")
    deadline = datetime.fromisoformat(data["response_deadline"])
    assert before + timeout <= deadline <= after + timeout


@pytest.mark.parametrize("approval", [ApprovalStatus.PENDING, ApprovalStatus.SUSPENDED])
def test_a_hospital_that_is_not_approved_cannot_create_requests(client, db, approval):
    user, _ = hospital_account(db, approval)
    response = post(client, user)
    assert response.status_code == 403
    assert error_code(response) == "ACCOUNT_NOT_APPROVED"
    assert request_count(db) == 0


def test_a_hospital_without_a_profile_is_asked_to_create_one(client, db):
    response = post(client, make_user(db, UserRole.HOSPITAL))
    assert response.status_code == 403
    assert error_code(response) == "ACCOUNT_NOT_APPROVED"
    assert "profile" in response.json()["error"]["message"]


@pytest.mark.parametrize("role", [UserRole.DONOR, UserRole.BLOOD_BANK, UserRole.ADMIN])
def test_other_roles_cannot_create_requests(client, db, role):
    response = post(client, make_user(db, role))
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"
    assert request_count(db) == 0


def test_creating_a_request_requires_a_token(client, db):
    response = client.post(URL, json=body())
    assert response.status_code == 401
    assert error_code(response) == "UNAUTHORIZED"


@pytest.mark.parametrize(
    "field",
    [
        "status",
        "hospital_id",
        "blood_bank_id",
        "response_deadline",
        "units_confirmed",
        "current_batch",
        "id",
    ],
)
def test_fields_the_client_must_not_set_are_rejected(client, db, field):
    values = {
        "status": "fulfilled",
        "hospital_id": str(uuid.uuid4()),
        "blood_bank_id": str(uuid.uuid4()),
        "response_deadline": "2030-01-01T00:00:00Z",
        "units_confirmed": 1,
        "current_batch": 1,
        "id": str(uuid.uuid4()),
    }
    user, _ = hospital_account(db)
    response = post(client, user, **{field: values[field]})
    assert response.status_code == 422
    assert field in error_fields(response)
    assert request_count(db) == 0


@pytest.mark.parametrize("missing", ["blood_type", "units_needed", "urgency"])
def test_missing_required_fields_are_rejected(client, db, missing):
    user, _ = hospital_account(db)
    response = client.post(URL, json=body(drop=(missing,)), headers=auth_headers(user))
    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"
    assert missing in error_fields(response)


@pytest.mark.parametrize(
    "field,value",
    [
        ("units_needed", 0),
        ("units_needed", -1),
        ("units_needed", 21),
        ("units_needed", "abc"),
        ("blood_type", "Z+"),
        ("urgency", "extreme"),
        ("notes", "x" * 1001),
    ],
)
def test_invalid_values_are_rejected(client, db, field, value):
    user, _ = hospital_account(db)
    response = post(client, user, **{field: value})
    assert response.status_code == 422
    assert field in error_fields(response)
    assert request_count(db) == 0


@pytest.mark.parametrize("units", [1, 20])
def test_units_at_the_limits_are_accepted(client, db, units):
    user, _ = hospital_account(db)
    assert post(client, user, units_needed=units).status_code == 201


@pytest.mark.parametrize(
    "sent,stored",
    [("  Need O+ urgently  ", "Need O+ urgently"), ("   ", None), ("", None)],
    ids=["trimmed", "blank spaces", "empty"],
)
def test_notes_are_trimmed_and_blank_notes_become_none(client, db, sent, stored):
    user, _ = hospital_account(db)
    assert post(client, user, notes=sent).json()["data"]["notes"] == stored


def test_a_critical_request_gets_a_shorter_deadline_than_a_normal_one(client, db):
    user, _ = hospital_account(db)
    normal = post(client, user, urgency="normal").json()["data"]["response_deadline"]
    critical = post(client, user, urgency="critical").json()["data"][
        "response_deadline"
    ]
    gap = datetime.fromisoformat(normal) - datetime.fromisoformat(critical)
    settings = get_settings()
    expected = settings.blood_bank_timeout("normal") - settings.blood_bank_timeout(
        "critical"
    )
    assert expected > timedelta(0)
    assert abs(gap - expected) < timedelta(seconds=30)


def test_a_request_to_an_unavailable_blood_bank_goes_straight_to_matching_over_http(
    client, db
):
    user = make_user(db, UserRole.HOSPITAL)
    make_hospital(
        db,
        user=user,
        blood_bank=make_blood_bank(db, approval_status=ApprovalStatus.SUSPENDED),
    )
    response = post(client, user)
    assert response.status_code == 201
    assert response.json()["data"]["status"] == "matching_donors"
    assert response.json()["data"]["response_deadline"] is None


# ============================================================ GET over HTTP


def test_a_hospital_reads_its_own_request(client, db):
    user, hospital = hospital_account(db)
    blood_request = make_blood_request(db, hospital=hospital, units_needed=3)
    response = client.get(f"{URL}/{blood_request.id}", headers=auth_headers(user))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == str(blood_request.id)
    assert data["units_needed"] == 3
    assert data["status"] == "pending_blood_bank"


def test_a_hospital_cannot_read_another_hospitals_request(client, db):
    user, _ = hospital_account(db)
    others = make_blood_request(db)
    response = client.get(f"{URL}/{others.id}", headers=auth_headers(user))
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_an_unknown_request_id_gives_404(client, db):
    user, _ = hospital_account(db)
    response = client.get(f"{URL}/{uuid.uuid4()}", headers=auth_headers(user))
    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_a_hospital_that_is_not_approved_cannot_read_requests(client, db):
    user, hospital = hospital_account(db, ApprovalStatus.PENDING)
    blood_request = make_blood_request(db, hospital=hospital)
    response = client.get(f"{URL}/{blood_request.id}", headers=auth_headers(user))
    assert response.status_code == 403
    assert error_code(response) == "ACCOUNT_NOT_APPROVED"


@pytest.mark.parametrize("role", [UserRole.DONOR, UserRole.BLOOD_BANK, UserRole.ADMIN])
def test_other_roles_cannot_read_a_hospital_request(client, db, role):
    blood_request = make_blood_request(db)
    response = client.get(
        f"{URL}/{blood_request.id}", headers=auth_headers(make_user(db, role))
    )
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_reading_a_request_requires_a_token(client, db):
    blood_request = make_blood_request(db)
    assert client.get(f"{URL}/{blood_request.id}").status_code == 401
