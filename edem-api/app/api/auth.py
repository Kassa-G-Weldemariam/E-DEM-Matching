from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.core.responses import success_response
from app.schemas.auth import (
    AccessTokenResponse,
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, db: DbSession):
    user = auth_service.register_user(db, data)
    return success_response(
        UserResponse.model_validate(user).model_dump(mode="json"),
        "Account created successfully",
    )


@router.post("/login")
def login(data: LoginRequest, db: DbSession):
    user = auth_service.authenticate_user(db, data.email, data.password)
    tokens = auth_service.issue_tokens(user)
    body = TokenResponse(**tokens, user=UserResponse.model_validate(user))
    return success_response(body.model_dump(mode="json"), "Login successful")


@router.post("/refresh")
def refresh(data: RefreshRequest, db: DbSession):
    tokens = auth_service.refresh_access_token(db, data.refresh_token)
    return success_response(AccessTokenResponse(**tokens).model_dump(mode="json"))


@router.get("/me")
def me(current_user: CurrentUser):
    return success_response(
        UserResponse.model_validate(current_user).model_dump(mode="json")
    )


@router.post("/change-password")
def change_password(
    data: ChangePasswordRequest, current_user: CurrentUser, db: DbSession
):
    auth_service.change_password(
        db, current_user, data.current_password, data.new_password
    )
    return success_response(None, "Password changed successfully")
