import pytest

from app.api.deps import ApprovedBloodBank, ApprovedHospital
from app.models.enums import ApprovalStatus, UserRole
from tests.factories import auth_headers, make_blood_bank, make_hospital, make_user

HOSPITAL_PATH = "/_test/approved-hospital"
BANK_PATH = "/_test/approved-blood-bank"

# kind -> (role, route, profile factory)
KINDS = {
    "hospital": (UserRole.HOSPITAL, HOSPITAL_PATH, make_hospital),
    "blood_bank": (UserRole.BLOOD_BANK, BANK_PATH, make_blood_bank),
}


def _approved_hospital(hospital: ApprovedHospital):
    return {"id": str(hospital.id), "name": hospital.name}


def _approved_blood_bank(blood_bank: ApprovedBloodBank):
    return {"id": str(blood_bank.id), "name": blood_bank.name}


@pytest.fixture()
def guarded(app, client):
    """The test client, plus throw-away routes that use the approval guards."""
    app.add_api_route(HOSPITAL_PATH, _approved_hospital, methods=["GET"])
    app.add_api_route(BANK_PATH, _approved_blood_bank, methods=["GET"])
    return client


def account(db, kind, approval_status=ApprovalStatus.APPROVED, *, with_profile=True):
    role, path, factory = KINDS[kind]
    user = make_user(db, role)
    profile = (
        factory(db, user=user, approval_status=approval_status)
        if with_profile
        else None
    )
    return user, profile, path


def call(client, user, path):
    return client.get(path, headers=auth_headers(user))


def error_of(response) -> dict:
    return response.json()["error"]


@pytest.mark.parametrize("kind", KINDS)
def test_an_approved_account_gets_through_with_its_own_profile(guarded, db, kind):
    user, profile, path = account(db, kind)
    response = call(guarded, user, path)
    assert response.status_code == 200
    assert response.json() == {"id": str(profile.id), "name": profile.name}


@pytest.mark.parametrize("kind", KINDS)
def test_a_pending_account_is_refused_with_a_clear_message(guarded, db, kind):
    user, _, path = account(db, kind, ApprovalStatus.PENDING)
    response = call(guarded, user, path)
    assert response.status_code == 403
    assert error_of(response)["code"] == "ACCOUNT_NOT_APPROVED"
    assert "waiting for Admin approval" in error_of(response)["message"]


@pytest.mark.parametrize("kind", KINDS)
def test_a_suspended_account_is_refused(guarded, db, kind):
    user, _, path = account(db, kind, ApprovalStatus.SUSPENDED)
    response = call(guarded, user, path)
    assert response.status_code == 403
    assert error_of(response)["code"] == "ACCOUNT_NOT_APPROVED"
    assert "suspended" in error_of(response)["message"]


@pytest.mark.parametrize("kind", KINDS)
def test_an_account_without_a_profile_is_asked_to_create_one(guarded, db, kind):
    user, _, path = account(db, kind, with_profile=False)
    response = call(guarded, user, path)
    assert response.status_code == 403
    assert error_of(response)["code"] == "ACCOUNT_NOT_APPROVED"
    assert "profile" in error_of(response)["message"]


@pytest.mark.parametrize(
    "path,role",
    [
        (HOSPITAL_PATH, UserRole.DONOR),
        (HOSPITAL_PATH, UserRole.BLOOD_BANK),
        (HOSPITAL_PATH, UserRole.ADMIN),
        (BANK_PATH, UserRole.DONOR),
        (BANK_PATH, UserRole.HOSPITAL),
        (BANK_PATH, UserRole.ADMIN),
    ],
)
def test_the_wrong_role_gets_forbidden_not_an_approval_error(guarded, db, path, role):
    user = make_user(db, role)
    response = call(guarded, user, path)
    assert response.status_code == 403
    assert error_of(response)["code"] == "FORBIDDEN"


@pytest.mark.parametrize("path", [HOSPITAL_PATH, BANK_PATH])
def test_a_missing_token_gives_401(guarded, path):
    response = guarded.get(path)
    assert response.status_code == 401
    assert error_of(response)["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize("kind", KINDS)
def test_approval_changes_take_effect_on_the_very_next_request(guarded, db, kind):
    user, profile, path = account(db, kind, ApprovalStatus.PENDING)
    assert call(guarded, user, path).status_code == 403

    profile.approval_status = ApprovalStatus.APPROVED
    db.commit()
    assert call(guarded, user, path).status_code == 200

    profile.approval_status = ApprovalStatus.SUSPENDED
    db.commit()
    assert call(guarded, user, path).status_code == 403


@pytest.mark.parametrize("kind", KINDS)
def test_a_deactivated_user_is_refused_even_with_an_approved_profile(guarded, db, kind):
    user, _, path = account(db, kind)
    user.is_active = False
    db.commit()
    response = call(guarded, user, path)
    assert response.status_code == 403
    assert "deactivated" in error_of(response)["message"]


@pytest.mark.parametrize("kind", KINDS)
def test_each_user_gets_their_own_profile(guarded, db, kind):
    first_user, first_profile, path = account(db, kind)
    second_user, second_profile, _ = account(db, kind)
    assert call(guarded, first_user, path).json()["id"] == str(first_profile.id)
    assert call(guarded, second_user, path).json()["id"] == str(second_profile.id)


@pytest.mark.parametrize("kind", KINDS)
def test_another_accounts_approval_does_not_help(guarded, db, kind):
    pending_user, _, path = account(db, kind, ApprovalStatus.PENDING)
    account(
        db, kind, ApprovalStatus.APPROVED
    )  # an approved account of the same kind exists
    assert call(guarded, pending_user, path).status_code == 403


def test_an_approved_blood_bank_that_is_not_operating_can_still_act(guarded, db):
    # is_active means "currently receiving requests"; it is separate from Admin approval.
    user = make_user(db, UserRole.BLOOD_BANK)
    make_blood_bank(db, user=user, is_active=False)
    assert call(guarded, user, BANK_PATH).status_code == 200
