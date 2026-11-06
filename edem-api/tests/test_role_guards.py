from typing import Annotated

import pytest
from fastapi import Depends

from app.api.deps import (
    AdminUser,
    BloodBankUser,
    DonorUser,
    HospitalUser,
    require_roles,
)
from app.core.security import create_refresh_token
from app.models.enums import UserRole
from app.models.user import User
from tests.factories import auth_headers, make_user

BankOrAdmin = Annotated[
    User, Depends(require_roles(UserRole.BLOOD_BANK, UserRole.ADMIN))
]


def _donor_only(user: DonorUser):
    return {"role": user.role.value, "email": user.email}


def _hospital_only(user: HospitalUser):
    return {"role": user.role.value, "email": user.email}


def _blood_bank_only(user: BloodBankUser):
    return {"role": user.role.value, "email": user.email}


def _admin_only(user: AdminUser):
    return {"role": user.role.value, "email": user.email}


def _bank_or_admin(user: BankOrAdmin):
    return {"role": user.role.value, "email": user.email}


@pytest.fixture()
def guarded(app, client):
    """The test client, plus throw-away routes that use each guard."""
    routes = {
        "/_test/donor-only": _donor_only,
        "/_test/hospital-only": _hospital_only,
        "/_test/blood_bank-only": _blood_bank_only,
        "/_test/admin-only": _admin_only,
        "/_test/bank-or-admin": _bank_or_admin,
    }
    for path, endpoint in routes.items():
        app.add_api_route(path, endpoint, methods=["GET"])
    return client


@pytest.mark.parametrize("guard", ["donor", "hospital", "blood_bank", "admin"])
@pytest.mark.parametrize("role", list(UserRole))
def test_each_guard_lets_in_only_its_own_role(guarded, db, guard, role):
    user = make_user(db, role)
    response = guarded.get(f"/_test/{guard}-only", headers=auth_headers(user))

    if role.value == guard:
        assert response.status_code == 200
        assert response.json() == {"role": role.value, "email": user.email}
    else:
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize(
    "path",
    [
        "/_test/donor-only",
        "/_test/hospital-only",
        "/_test/blood_bank-only",
        "/_test/admin-only",
        "/_test/bank-or-admin",
    ],
)
def test_a_missing_token_gives_401_not_403(guarded, path):
    response = guarded.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize(
    "role,expected_status",
    [
        (UserRole.BLOOD_BANK, 200),
        (UserRole.ADMIN, 200),
        (UserRole.DONOR, 403),
        (UserRole.HOSPITAL, 403),
    ],
)
def test_a_guard_can_allow_several_roles(guarded, db, role, expected_status):
    user = make_user(db, role)
    response = guarded.get("/_test/bank-or-admin", headers=auth_headers(user))
    assert response.status_code == expected_status


def test_forbidden_response_uses_the_standard_error_format(guarded, db):
    donor = make_user(db, UserRole.DONOR)
    body = guarded.get("/_test/admin-only", headers=auth_headers(donor)).json()
    assert body["success"] is False
    assert body["error"]["code"] == "FORBIDDEN"
    assert "permission" in body["error"]["message"]


def test_deactivated_user_with_the_right_role_is_still_forbidden(guarded, db):
    donor = make_user(db, UserRole.DONOR, is_active=False)
    response = guarded.get("/_test/donor-only", headers=auth_headers(donor))
    assert response.status_code == 403
    assert "deactivated" in response.json()["error"]["message"]


def test_role_change_takes_effect_on_the_very_next_request(guarded, db):
    user = make_user(db, UserRole.DONOR)
    headers = auth_headers(user)  # the token is issued while the user is a donor
    assert guarded.get("/_test/donor-only", headers=headers).status_code == 200

    user.role = UserRole.HOSPITAL
    db.commit()

    assert guarded.get("/_test/donor-only", headers=headers).status_code == 403
    assert guarded.get("/_test/hospital-only", headers=headers).status_code == 200


def test_a_refresh_token_cannot_pass_a_guard(guarded, db):
    donor = make_user(db, UserRole.DONOR)
    headers = {"Authorization": f"Bearer {create_refresh_token(donor.id)}"}
    assert guarded.get("/_test/donor-only", headers=headers).status_code == 401


def test_a_guard_without_roles_fails_at_start_up():
    with pytest.raises(ValueError):
        require_roles()
