import uuid

import pytest

from app.api.deps import ApprovedBloodBank, ApprovedHospital, DbSession
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.enums import ApprovalStatus, UserRole
from app.services.ownership import (
    get_donor_for_blood_bank,
    get_match_for_donor,
    get_match_for_hospital,
    get_request_for_blood_bank,
    get_request_for_hospital,
)
from tests.factories import (
    auth_headers,
    make_blood_bank,
    make_blood_request,
    make_donor,
    make_hospital,
    make_match,
    make_user,
)

# ===================================================================
# The helper functions, called directly
# ===================================================================


def test_hospital_gets_its_own_request(db):
    hospital = make_hospital(db)
    blood_request = make_blood_request(db, hospital=hospital)
    assert (
        get_request_for_hospital(db, blood_request.id, hospital).id == blood_request.id
    )


def test_hospital_cannot_get_another_hospitals_request(db):
    mine = make_hospital(db)
    others_request = make_blood_request(db, hospital=make_hospital(db))
    with pytest.raises(ForbiddenException):
        get_request_for_hospital(db, others_request.id, mine)


def test_hospital_request_that_does_not_exist_is_not_found(db):
    with pytest.raises(NotFoundException):
        get_request_for_hospital(db, uuid.uuid4(), make_hospital(db))


def test_blood_bank_gets_a_request_assigned_to_it(db):
    bank = make_blood_bank(db)
    blood_request = make_blood_request(db, hospital=make_hospital(db, blood_bank=bank))
    assert get_request_for_blood_bank(db, blood_request.id, bank).id == blood_request.id


def test_blood_bank_cannot_get_a_request_assigned_to_another_bank(db):
    bank = make_blood_bank(db)
    other_banks_request = make_blood_request(db, hospital=make_hospital(db))
    with pytest.raises(ForbiddenException):
        get_request_for_blood_bank(db, other_banks_request.id, bank)


def test_blood_bank_request_that_does_not_exist_is_not_found(db):
    with pytest.raises(NotFoundException):
        get_request_for_blood_bank(db, uuid.uuid4(), make_blood_bank(db))


def test_blood_bank_gets_its_own_donor(db):
    bank = make_blood_bank(db)
    donor = make_donor(db, blood_bank=bank)
    assert get_donor_for_blood_bank(db, donor.id, bank).id == donor.id


def test_blood_bank_cannot_get_another_banks_donor(db):
    bank = make_blood_bank(db)
    other_banks_donor = make_donor(db, blood_bank=make_blood_bank(db))
    with pytest.raises(ForbiddenException):
        get_donor_for_blood_bank(db, other_banks_donor.id, bank)


def test_donor_that_does_not_exist_is_not_found(db):
    with pytest.raises(NotFoundException):
        get_donor_for_blood_bank(db, uuid.uuid4(), make_blood_bank(db))


def test_donor_gets_their_own_match(db):
    donor = make_donor(db)
    match = make_match(db, donor=donor)
    assert get_match_for_donor(db, match.id, donor).id == match.id


def test_donor_cannot_get_another_donors_match(db):
    donor = make_donor(db)
    others_match = make_match(db, donor=make_donor(db))
    with pytest.raises(ForbiddenException):
        get_match_for_donor(db, others_match.id, donor)


def test_match_that_does_not_exist_is_not_found_for_a_donor(db):
    with pytest.raises(NotFoundException):
        get_match_for_donor(db, uuid.uuid4(), make_donor(db))


def test_hospital_gets_a_match_of_its_own_request(db):
    hospital = make_hospital(db)
    blood_request = make_blood_request(db, hospital=hospital)
    match = make_match(db, blood_request=blood_request)
    found_request, found_match = get_match_for_hospital(
        db, blood_request.id, match.id, hospital
    )
    assert found_request.id == blood_request.id
    assert found_match.id == match.id


def test_match_from_another_request_of_the_same_hospital_is_not_found(db):
    hospital = make_hospital(db)
    first = make_blood_request(db, hospital=hospital)
    second = make_blood_request(db, hospital=hospital)
    match_of_second = make_match(db, blood_request=second)
    with pytest.raises(NotFoundException):
        get_match_for_hospital(db, first.id, match_of_second.id, hospital)


def test_match_of_another_hospitals_request_is_not_found_through_your_own_request(db):
    mine = make_hospital(db)
    my_request = make_blood_request(db, hospital=mine)
    others_match = make_match(db, blood_request=make_blood_request(db))
    with pytest.raises(NotFoundException):
        get_match_for_hospital(db, my_request.id, others_match.id, mine)


def test_hospital_cannot_reach_matches_through_another_hospitals_request(db):
    mine = make_hospital(db)
    others_request = make_blood_request(db)
    others_match = make_match(db, blood_request=others_request)
    with pytest.raises(ForbiddenException):
        get_match_for_hospital(db, others_request.id, others_match.id, mine)


def test_match_that_does_not_exist_is_not_found_for_a_hospital(db):
    hospital = make_hospital(db)
    blood_request = make_blood_request(db, hospital=hospital)
    with pytest.raises(NotFoundException):
        get_match_for_hospital(db, blood_request.id, uuid.uuid4(), hospital)


# ===================================================================
# The whole chain over HTTP: login, role, approval, then ownership
# ===================================================================


def _hospital_request(request_id: uuid.UUID, hospital: ApprovedHospital, db: DbSession):
    return {"id": str(get_request_for_hospital(db, request_id, hospital).id)}


def _hospital_match(
    request_id: uuid.UUID,
    match_id: uuid.UUID,
    hospital: ApprovedHospital,
    db: DbSession,
):
    _, match = get_match_for_hospital(db, request_id, match_id, hospital)
    return {"id": str(match.id)}


def _bank_request(request_id: uuid.UUID, blood_bank: ApprovedBloodBank, db: DbSession):
    return {"id": str(get_request_for_blood_bank(db, request_id, blood_bank).id)}


def _bank_donor(donor_id: uuid.UUID, blood_bank: ApprovedBloodBank, db: DbSession):
    return {"id": str(get_donor_for_blood_bank(db, donor_id, blood_bank).id)}


@pytest.fixture()
def guarded(app, client):
    """The test client, plus throw-away routes that use the ownership helpers."""
    app.add_api_route(
        "/_test/hospital-requests/{request_id}", _hospital_request, methods=["GET"]
    )
    app.add_api_route(
        "/_test/hospital-requests/{request_id}/matches/{match_id}",
        _hospital_match,
        methods=["GET"],
    )
    app.add_api_route(
        "/_test/bank-requests/{request_id}", _bank_request, methods=["GET"]
    )
    app.add_api_route("/_test/bank-donors/{donor_id}", _bank_donor, methods=["GET"])
    return client


def hospital_account(db, approval_status=ApprovalStatus.APPROVED):
    user = make_user(db, UserRole.HOSPITAL)
    return user, make_hospital(db, user=user, approval_status=approval_status)


def bank_account(db):
    user = make_user(db, UserRole.BLOOD_BANK)
    return user, make_blood_bank(db, user=user)


def test_hospital_reads_its_own_request_over_http(guarded, db):
    user, hospital = hospital_account(db)
    blood_request = make_blood_request(db, hospital=hospital)
    response = guarded.get(
        f"/_test/hospital-requests/{blood_request.id}", headers=auth_headers(user)
    )
    assert response.status_code == 200
    assert response.json() == {"id": str(blood_request.id)}


def test_hospital_gets_403_for_another_hospitals_request(guarded, db):
    user, _ = hospital_account(db)
    others_request = make_blood_request(db)
    response = guarded.get(
        f"/_test/hospital-requests/{others_request.id}", headers=auth_headers(user)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_unknown_request_id_gives_404(guarded, db):
    user, _ = hospital_account(db)
    response = guarded.get(
        f"/_test/hospital-requests/{uuid.uuid4()}", headers=auth_headers(user)
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_malformed_id_gives_422(guarded, db):
    user, _ = hospital_account(db)
    response = guarded.get(
        "/_test/hospital-requests/not-a-uuid", headers=auth_headers(user)
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_approval_check_comes_before_the_ownership_check(guarded, db):
    user, hospital = hospital_account(db, ApprovalStatus.PENDING)
    own_request = make_blood_request(db, hospital=hospital)
    response = guarded.get(
        f"/_test/hospital-requests/{own_request.id}", headers=auth_headers(user)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_NOT_APPROVED"


def test_missing_token_gives_401(guarded, db):
    blood_request = make_blood_request(db)
    response = guarded.get(f"/_test/hospital-requests/{blood_request.id}")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_hospital_match_route_returns_a_match_of_its_own_request(guarded, db):
    user, hospital = hospital_account(db)
    blood_request = make_blood_request(db, hospital=hospital)
    match = make_match(db, blood_request=blood_request)
    response = guarded.get(
        f"/_test/hospital-requests/{blood_request.id}/matches/{match.id}",
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    assert response.json() == {"id": str(match.id)}


def test_hospital_match_route_hides_a_match_of_another_request(guarded, db):
    user, hospital = hospital_account(db)
    first = make_blood_request(db, hospital=hospital)
    second = make_blood_request(db, hospital=hospital)
    match_of_second = make_match(db, blood_request=second)
    response = guarded.get(
        f"/_test/hospital-requests/{first.id}/matches/{match_of_second.id}",
        headers=auth_headers(user),
    )
    assert response.status_code == 404


def test_hospital_match_route_hides_another_hospitals_match_behind_your_own_request(
    guarded, db
):
    user, hospital = hospital_account(db)
    my_request = make_blood_request(db, hospital=hospital)
    others_match = make_match(db, blood_request=make_blood_request(db))
    response = guarded.get(
        f"/_test/hospital-requests/{my_request.id}/matches/{others_match.id}",
        headers=auth_headers(user),
    )
    assert response.status_code == 404


def test_hospital_match_route_refuses_another_hospitals_request(guarded, db):
    user, _ = hospital_account(db)
    others_request = make_blood_request(db)
    others_match = make_match(db, blood_request=others_request)
    response = guarded.get(
        f"/_test/hospital-requests/{others_request.id}/matches/{others_match.id}",
        headers=auth_headers(user),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_blood_bank_reads_a_request_assigned_to_it(guarded, db):
    user, bank = bank_account(db)
    blood_request = make_blood_request(db, hospital=make_hospital(db, blood_bank=bank))
    response = guarded.get(
        f"/_test/bank-requests/{blood_request.id}", headers=auth_headers(user)
    )
    assert response.status_code == 200
    assert response.json() == {"id": str(blood_request.id)}


def test_blood_bank_gets_403_for_another_banks_request(guarded, db):
    user, _ = bank_account(db)
    others_request = make_blood_request(db)
    response = guarded.get(
        f"/_test/bank-requests/{others_request.id}", headers=auth_headers(user)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_blood_bank_reads_its_own_donor(guarded, db):
    user, bank = bank_account(db)
    donor = make_donor(db, blood_bank=bank)
    response = guarded.get(f"/_test/bank-donors/{donor.id}", headers=auth_headers(user))
    assert response.status_code == 200
    assert response.json() == {"id": str(donor.id)}


def test_blood_bank_gets_403_for_another_banks_donor(guarded, db):
    user, _ = bank_account(db)
    others_donor = make_donor(db)
    response = guarded.get(
        f"/_test/bank-donors/{others_donor.id}", headers=auth_headers(user)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
